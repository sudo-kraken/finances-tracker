"""Small, automatic database migrations for self-hosted installations.

The application historically used ``create_all()``, which creates a fresh
schema but cannot add columns to an existing database.  These migrations run
at application startup and deliberately use SQLAlchemy primitives rather than
requiring a separate migration command.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Connection, Engine

LEGACY_OWNER_USERNAME = "_legacy_data_owner"
LEGACY_OWNER_PASSWORD_HASH = "!"

_MIGRATION_LOCK_NAME = "finances_tracker_schema_migrations"
_POSTGRES_LOCK_NAMESPACE = 1179535694

_migration_metadata = MetaData()
_migration_table = Table(
    "schema_migration",
    _migration_metadata,
    Column("version", Integer, primary_key=True),
    Column("applied_at", DateTime(timezone=True), nullable=False),
)
_registration_gate_table = Table(
    "registration_gate",
    _migration_metadata,
    Column("id", Integer, primary_key=True),
    Column("claimed_at", DateTime, nullable=False),
)

Migration = tuple[int, Callable[[Connection], None]]


def upgrade_schema(engine: Engine, app_metadata: MetaData | None = None) -> None:
    """Create a fresh schema or upgrade an existing one in place.

    Passing the application's model metadata makes schema creation part of the
    same database lock as migration.  This is important when several Gunicorn
    workers start against a new database at the same time.
    """

    dialect = engine.dialect.name
    if dialect == "sqlite":
        _upgrade_sqlite(engine, app_metadata)
    elif dialect == "postgresql":
        _upgrade_postgresql(engine, app_metadata)
    elif dialect in {"mysql", "mariadb"}:
        _upgrade_mysql(engine, app_metadata)
    else:
        with engine.begin() as connection:
            _run_upgrades(connection, app_metadata)


def is_legacy_owner(username: str, password_hash: str) -> bool:
    """Return whether credentials identify the migration-only owner."""

    return username == LEGACY_OWNER_USERNAME and password_hash == LEGACY_OWNER_PASSWORD_HASH


def _upgrade_sqlite(engine: Engine, app_metadata: MetaData | None) -> None:
    with engine.connect() as connection:
        # SQLite locks are database-wide.  BEGIN IMMEDIATE serialises startup
        # migrations before any worker inspects or alters the schema.
        connection.exec_driver_sql("PRAGMA busy_timeout = 30000")
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            _run_upgrades(connection, app_metadata)
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()


def _upgrade_postgresql(engine: Engine, app_metadata: MetaData | None) -> None:
    with engine.begin() as connection:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:namespace)"),
            {"namespace": _POSTGRES_LOCK_NAMESPACE},
        )
        _run_upgrades(connection, app_metadata)


def _upgrade_mysql(engine: Engine, app_metadata: MetaData | None) -> None:
    # MySQL named locks survive the implicit commits caused by DDL.
    with engine.connect() as connection:
        acquired = connection.execute(
            text("SELECT GET_LOCK(:lock_name, 30)"),
            {"lock_name": _MIGRATION_LOCK_NAME},
        ).scalar_one()
        if acquired != 1:
            raise RuntimeError("Could not acquire the database migration lock")

        try:
            _run_upgrades(connection, app_metadata)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.execute(
                text("SELECT RELEASE_LOCK(:lock_name)"),
                {"lock_name": _MIGRATION_LOCK_NAME},
            )
            connection.commit()


def _run_upgrades(connection: Connection, app_metadata: MetaData | None) -> None:
    if app_metadata is not None:
        app_metadata.create_all(bind=connection, checkfirst=True)

    _migration_metadata.create_all(bind=connection, checkfirst=True)
    applied_versions = set(connection.execute(select(_migration_table.c.version)).scalars())

    for version, migration in _MIGRATIONS:
        if version in applied_versions:
            continue
        migration(connection)
        connection.execute(
            _migration_table.insert().values(
                version=version,
                applied_at=datetime.now(timezone.utc),
            )
        )


def _add_month_owner(connection: Connection) -> None:
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if "month" not in table_names or "user" not in table_names:
        return

    month_table = _quote(connection, "month")
    user_table = _quote(connection, "user")
    user_id_column = _quote(connection, "user_id")
    id_column = _quote(connection, "id")

    month_columns = {column["name"] for column in inspector.get_columns("month")}
    if "user_id" not in month_columns:
        connection.exec_driver_sql(f"ALTER TABLE {month_table} ADD COLUMN {user_id_column} INTEGER")

    reflected_metadata = MetaData()
    reflected_month = Table("month", reflected_metadata, autoload_with=connection)
    Index("ix_month_user_id", reflected_month.c.user_id).create(bind=connection, checkfirst=True)

    unowned_month = connection.execute(
        text(f"SELECT {id_column} FROM {month_table} WHERE {user_id_column} IS NULL")
    ).first()
    if unowned_month is None:
        return

    owner_id = connection.execute(text(f"SELECT {id_column} FROM {user_table} ORDER BY {id_column}")).scalar()
    if owner_id is None:
        username_column = _quote(connection, "username")
        password_hash_column = _quote(connection, "password_hash")
        connection.execute(
            text(
                f"INSERT INTO {user_table} ({username_column}, {password_hash_column}) "
                "VALUES (:username, :password_hash)"
            ),
            {
                "username": LEGACY_OWNER_USERNAME,
                "password_hash": LEGACY_OWNER_PASSWORD_HASH,
            },
        )
        owner_id = connection.execute(
            text(f"SELECT {id_column} FROM {user_table} WHERE {username_column} = :username"),
            {"username": LEGACY_OWNER_USERNAME},
        ).scalar_one()

    connection.execute(
        text(f"UPDATE {month_table} SET {user_id_column} = :owner_id WHERE {user_id_column} IS NULL"),
        {"owner_id": owner_id},
    )


def _add_transfer_destination(connection: Connection) -> None:
    """Persist transfer intent independently of a generated paid income."""

    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())
    if not {"account", "bill", "income"}.issubset(table_names):
        return

    bill_table = _quote(connection, "bill")
    account_table = _quote(connection, "account")
    income_table = _quote(connection, "income")
    transfer_account_id = _quote(connection, "transfer_account_id")
    linked_income_id = _quote(connection, "linked_income_id")
    account_id = _quote(connection, "account_id")
    id_column = _quote(connection, "id")

    bill_columns = {column["name"] for column in inspector.get_columns("bill")}
    if "transfer_account_id" not in bill_columns:
        reference = f" REFERENCES {account_table} ({id_column})" if connection.dialect.name == "sqlite" else ""
        connection.exec_driver_sql(f"ALTER TABLE {bill_table} ADD COLUMN {transfer_account_id} INTEGER{reference}")

    reflected_metadata = MetaData()
    reflected_bill = Table("bill", reflected_metadata, autoload_with=connection)
    Index(
        "ix_bill_transfer_account_id",
        reflected_bill.c.transfer_account_id,
    ).create(bind=connection, checkfirst=True)

    connection.execute(
        text(
            f"""
            UPDATE {bill_table}
            SET {transfer_account_id} = (
                SELECT {account_id}
                FROM {income_table}
                WHERE {income_table}.{id_column} = {bill_table}.{linked_income_id}
            )
            WHERE {linked_income_id} IS NOT NULL
              AND {transfer_account_id} IS NULL
            """
        )
    )

    if connection.dialect.name not in {"postgresql", "mysql", "mariadb"}:
        return

    foreign_keys = inspect(connection).get_foreign_keys("bill")
    has_transfer_foreign_key = any(
        foreign_key.get("referred_table") == "account"
        and foreign_key.get("constrained_columns") == ["transfer_account_id"]
        for foreign_key in foreign_keys
    )
    if not has_transfer_foreign_key:
        constraint = _quote(connection, "fk_bill_transfer_account_id_account")
        connection.exec_driver_sql(
            f"ALTER TABLE {bill_table} ADD CONSTRAINT {constraint} "
            f"FOREIGN KEY ({transfer_account_id}) REFERENCES {account_table} ({id_column})"
        )


def _widen_password_hash(connection: Connection) -> None:
    inspector = inspect(connection)
    if "user" not in set(inspector.get_table_names()):
        return

    password_column = next(
        (column for column in inspector.get_columns("user") if column["name"] == "password_hash"),
        None,
    )
    if password_column is None:
        return

    current_length = getattr(password_column["type"], "length", None)
    if current_length is None or current_length >= 512:
        return

    user_table = _quote(connection, "user")
    password_hash = _quote(connection, "password_hash")
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(f"ALTER TABLE {user_table} ALTER COLUMN {password_hash} TYPE VARCHAR(512)")
    elif connection.dialect.name in {"mysql", "mariadb"}:
        nullability = "NULL" if password_column["nullable"] else "NOT NULL"
        connection.exec_driver_sql(f"ALTER TABLE {user_table} MODIFY COLUMN {password_hash} VARCHAR(512) {nullability}")
    # SQLite does not enforce the declared VARCHAR length, so existing tables
    # already accept current hashes without a risky table rebuild.


def _enforce_month_owner_constraints(connection: Connection) -> None:
    """Make the legacy owner column mandatory on every supported dialect."""

    inspector = inspect(connection)
    if not {"month", "user"}.issubset(set(inspector.get_table_names())):
        return

    user_id = next(
        (column for column in inspector.get_columns("month") if column["name"] == "user_id"),
        None,
    )
    if user_id is None:
        return

    month_table = _quote(connection, "month")
    user_table = _quote(connection, "user")
    user_id_column = _quote(connection, "user_id")
    id_column = _quote(connection, "id")

    foreign_keys = inspector.get_foreign_keys("month")
    has_user_foreign_key = any(
        foreign_key.get("referred_table") == "user" and foreign_key.get("constrained_columns") == ["user_id"]
        for foreign_key in foreign_keys
    )

    if connection.dialect.name == "sqlite":
        _add_sqlite_month_owner_triggers(
            connection,
            require_not_null=user_id["nullable"],
            require_foreign_key=not has_user_foreign_key,
        )
        return

    if connection.dialect.name == "postgresql" and user_id["nullable"]:
        connection.exec_driver_sql(f"ALTER TABLE {month_table} ALTER COLUMN {user_id_column} SET NOT NULL")
    elif connection.dialect.name in {"mysql", "mariadb"} and user_id["nullable"]:
        connection.exec_driver_sql(f"ALTER TABLE {month_table} MODIFY COLUMN {user_id_column} INTEGER NOT NULL")

    if connection.dialect.name in {"postgresql", "mysql", "mariadb"} and not has_user_foreign_key:
        constraint = _quote(connection, "fk_month_user_id_user")
        connection.exec_driver_sql(
            f"ALTER TABLE {month_table} ADD CONSTRAINT {constraint} "
            f"FOREIGN KEY ({user_id_column}) REFERENCES {user_table} ({id_column})"
        )


def _add_sqlite_month_owner_triggers(
    connection: Connection,
    *,
    require_not_null: bool,
    require_foreign_key: bool,
) -> None:
    if not require_not_null and not require_foreign_key:
        return

    month_table = _quote(connection, "month")
    user_table = _quote(connection, "user")
    insert_trigger = _quote(connection, "finances_tracker_month_owner_insert")
    update_trigger = _quote(connection, "finances_tracker_month_owner_update")
    delete_trigger = _quote(connection, "finances_tracker_month_owner_user_delete")

    invalid_reference = (
        f'NEW."user_id" IS NULL OR NOT EXISTS (SELECT 1 FROM {user_table} WHERE {user_table}."id" = NEW."user_id")'
    )
    connection.exec_driver_sql(
        f"""
        CREATE TRIGGER IF NOT EXISTS {insert_trigger}
        BEFORE INSERT ON {month_table}
        FOR EACH ROW WHEN {invalid_reference}
        BEGIN
            SELECT RAISE(ABORT, 'month.user_id must reference user');
        END
        """
    )
    connection.exec_driver_sql(
        f"""
        CREATE TRIGGER IF NOT EXISTS {update_trigger}
        BEFORE UPDATE OF "user_id" ON {month_table}
        FOR EACH ROW WHEN {invalid_reference}
        BEGIN
            SELECT RAISE(ABORT, 'month.user_id must reference user');
        END
        """
    )
    if require_foreign_key:
        connection.exec_driver_sql(
            f"""
            CREATE TRIGGER IF NOT EXISTS {delete_trigger}
            BEFORE DELETE ON {user_table}
            FOR EACH ROW WHEN EXISTS (
                SELECT 1 FROM {month_table} WHERE {month_table}."user_id" = OLD."id"
            )
            BEGIN
                SELECT RAISE(ABORT, 'user is referenced by month');
            END
            """
        )


def _seed_registration_gate(connection: Connection) -> None:
    """Close first-user registration for databases that already have a user."""

    if "user" not in set(inspect(connection).get_table_names()):
        return
    if connection.execute(select(_registration_gate_table.c.id).limit(1)).first():
        return

    reflected_user = Table("user", MetaData(), autoload_with=connection)
    users = connection.execute(select(reflected_user.c.username, reflected_user.c.password_hash)).all()
    if any(not is_legacy_owner(username, password_hash) for username, password_hash in users):
        connection.execute(
            _registration_gate_table.insert().values(
                id=1,
                claimed_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )


def _add_oidc_identity_table(connection: Connection) -> None:
    """Add optional external identities without changing existing users."""

    if "user" not in set(inspect(connection).get_table_names()):
        return

    identity_metadata = MetaData()
    Table("user", identity_metadata, autoload_with=connection)
    oidc_identity = Table(
        "oidc_identity",
        identity_metadata,
        Column("id", Integer, primary_key=True),
        Column(
            "user_id",
            Integer,
            ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        Column("issuer", String(255), nullable=False),
        Column("subject", String(255), nullable=False),
        Column("email", String(320), nullable=True),
        Column("created_at", DateTime, nullable=False),
        Column("last_login_at", DateTime, nullable=True),
        UniqueConstraint("issuer", "subject", name="uq_oidc_identity_issuer_subject"),
        UniqueConstraint("user_id", "issuer", name="uq_oidc_identity_user_issuer"),
    )
    Index("ix_oidc_identity_user_id", oidc_identity.c.user_id)
    oidc_identity.create(bind=connection, checkfirst=True)


def _normalize_account_geometry(connection: Connection) -> None:
    inspector = inspect(connection)
    if "account" not in set(inspector.get_table_names()):
        return

    required_columns = {"width", "height", "pos_x", "pos_y"}
    account_columns = {column["name"] for column in inspector.get_columns("account")}
    if not required_columns.issubset(account_columns):
        return

    account_table = _quote(connection, "account")
    width = _quote(connection, "width")
    height = _quote(connection, "height")
    pos_x = _quote(connection, "pos_x")
    pos_y = _quote(connection, "pos_y")

    connection.execute(
        text(
            f"""
            UPDATE {account_table}
            SET
                {width} = CASE
                    WHEN {width} IS NULL OR {width} < :min_width THEN :min_width
                    WHEN {width} > :max_width THEN :max_width
                    ELSE {width}
                END,
                {height} = CASE
                    WHEN {height} IS NULL OR {height} < :min_height THEN :min_height
                    WHEN {height} > :max_height THEN :max_height
                    ELSE {height}
                END,
                {pos_x} = CASE
                    WHEN {pos_x} IS NULL OR {pos_x} < 0 THEN 0
                    ELSE {pos_x}
                END,
                {pos_y} = CASE
                    WHEN {pos_y} IS NULL OR {pos_y} < 0 THEN 0
                    ELSE {pos_y}
                END
            """
        ),
        {
            "min_width": 400,
            "max_width": 1200,
            "min_height": 350,
            "max_height": 1200,
        },
    )
    connection.execute(
        text(
            f"""
            UPDATE {account_table}
            SET {pos_x} = :workspace_width - {width}
            WHERE {pos_x} + {width} > :workspace_width
            """
        ),
        {"workspace_width": 1200},
    )


def _quote(connection: Connection, identifier: str) -> str:
    return connection.dialect.identifier_preparer.quote_identifier(identifier)


_MIGRATIONS: tuple[Migration, ...] = (
    (1, _add_month_owner),
    (2, _normalize_account_geometry),
    (3, _add_transfer_destination),
    (4, _widen_password_hash),
    (5, _enforce_month_owner_constraints),
    (6, _seed_registration_gate),
    (7, _add_oidc_identity_table),
)
