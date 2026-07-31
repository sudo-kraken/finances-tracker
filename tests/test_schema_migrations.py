import importlib
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import Column, ForeignKey, Integer, MetaData, String, Table, create_engine, inspect, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def migrations(app_module):
    return importlib.import_module("app.schema_migrations")


def _sqlite_engine(path):
    return create_engine(
        URL.create("sqlite", database=str(path)),
        connect_args={"check_same_thread": False},
    )


def _create_legacy_schema(engine, *, include_users, include_geometry=False):
    geometry_columns = """
                , pos_x INTEGER
                , pos_y INTEGER
                , width INTEGER
                , height INTEGER
    """
    if not include_geometry:
        geometry_columns = ""

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE user (
                id INTEGER NOT NULL PRIMARY KEY,
                username VARCHAR(64) NOT NULL UNIQUE,
                password_hash VARCHAR(128) NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE month (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(50) NOT NULL,
                archived BOOLEAN,
                created_at DATETIME
            )
            """
        )
        connection.exec_driver_sql(
            f"""
            CREATE TABLE account (
                id INTEGER NOT NULL PRIMARY KEY,
                month_id INTEGER NOT NULL REFERENCES month (id),
                name VARCHAR(100) NOT NULL
                {geometry_columns}
            )
            """
        )
        if include_users:
            connection.execute(
                text("INSERT INTO user (id, username, password_hash) VALUES (8, 'second', '!'), (3, 'first', '!')")
            )
        connection.execute(
            text("INSERT INTO month (id, name, archived) VALUES (11, 'January', 0), (12, 'February', 1)")
        )
        if include_geometry:
            connection.execute(
                text(
                    "INSERT INTO account "
                    "(id, month_id, name, pos_x, pos_y, width, height) "
                    "VALUES (20, 11, 'Current', 0, 0, 300, 250)"
                )
            )
        else:
            connection.execute(text("INSERT INTO account (id, month_id, name) VALUES (20, 11, 'Current')"))


def test_existing_rows_are_preserved_and_assigned_to_first_user(tmp_path, migrations):
    engine = _sqlite_engine(tmp_path / "legacy-with-users.db")
    _create_legacy_schema(engine, include_users=True)

    migrations.upgrade_schema(engine)
    migrations.upgrade_schema(engine)

    assert "user_id" in {column["name"] for column in inspect(engine).get_columns("month")}
    assert "ix_month_user_id" in {index["name"] for index in inspect(engine).get_indexes("month")}
    with engine.connect() as connection:
        months = connection.execute(text("SELECT id, name, user_id FROM month ORDER BY id")).all()
        accounts = connection.execute(text("SELECT id, month_id, name FROM account")).all()
        users = connection.execute(text("SELECT id, username FROM user ORDER BY id")).all()
        versions = connection.execute(text("SELECT version FROM schema_migration")).all()

    assert months == [(11, "January", 3), (12, "February", 3)]
    assert accounts == [(20, 11, "Current")]
    assert users == [(3, "first"), (8, "second")]
    assert versions == [(1,), (2,), (3,), (4,), (5,), (6,), (7,)]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM registration_gate")).scalars().all() == [1]
    engine.dispose()


def test_database_without_users_gets_an_unloginable_legacy_owner(tmp_path, migrations):
    engine = _sqlite_engine(tmp_path / "legacy-without-users.db")
    _create_legacy_schema(engine, include_users=False)

    migrations.upgrade_schema(engine)
    migrations.upgrade_schema(engine)

    with engine.connect() as connection:
        users = connection.execute(text("SELECT id, username, password_hash FROM user")).all()
        owner_ids = connection.execute(text("SELECT DISTINCT user_id FROM month")).scalars().all()

    assert len(users) == 1
    owner_id, username, password_hash = users[0]
    assert migrations.is_legacy_owner(username, password_hash)
    assert owner_ids == [owner_id]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM registration_gate")).scalar_one() == 0
    engine.dispose()


def test_fresh_database_stays_free_of_legacy_owner(tmp_path, migrations):
    engine = _sqlite_engine(tmp_path / "fresh.db")
    metadata = MetaData()
    Table(
        "user",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("username", String(64), nullable=False, unique=True),
        Column("password_hash", String(512), nullable=False),
    )
    Table(
        "month",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("name", String(50), nullable=False),
        Column("user_id", Integer, ForeignKey("user.id"), nullable=False),
    )

    migrations.upgrade_schema(engine, metadata)
    migrations.upgrade_schema(engine, metadata)

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM user")).scalar_one() == 0
        assert connection.execute(text("SELECT version FROM schema_migration")).scalars().all() == [
            1,
            2,
            3,
            4,
            5,
            6,
            7,
        ]
        assert connection.execute(text("SELECT COUNT(*) FROM registration_gate")).scalar_one() == 0
    engine.dispose()


def test_oidc_identity_table_is_added_without_changing_existing_users(tmp_path, migrations):
    engine = _sqlite_engine(tmp_path / "legacy-oidc.db")
    _create_legacy_schema(engine, include_users=True)
    with engine.connect() as connection:
        users_before = connection.execute(text("SELECT id, username, password_hash FROM user ORDER BY id")).all()

    migrations.upgrade_schema(engine)
    migrations.upgrade_schema(engine)

    inspector = inspect(engine)
    columns = {column["name"]: column for column in inspector.get_columns("oidc_identity")}
    unique_constraints = {
        tuple(constraint["column_names"]) for constraint in inspector.get_unique_constraints("oidc_identity")
    }
    foreign_keys = inspector.get_foreign_keys("oidc_identity")
    indexes = {index["name"] for index in inspector.get_indexes("oidc_identity")}

    assert set(columns) == {
        "id",
        "user_id",
        "issuer",
        "subject",
        "email",
        "created_at",
        "last_login_at",
    }
    assert columns["user_id"]["nullable"] is False
    assert columns["issuer"]["nullable"] is False
    assert columns["subject"]["nullable"] is False
    assert columns["created_at"]["nullable"] is False
    assert ("issuer", "subject") in unique_constraints
    assert ("user_id", "issuer") in unique_constraints
    assert "ix_oidc_identity_user_id" in indexes
    assert any(
        foreign_key.get("referred_table") == "user" and foreign_key.get("constrained_columns") == ["user_id"]
        for foreign_key in foreign_keys
    )

    with engine.connect() as connection:
        users_after = connection.execute(text("SELECT id, username, password_hash FROM user ORDER BY id")).all()
        versions = connection.execute(text("SELECT version FROM schema_migration ORDER BY version")).scalars().all()

    assert users_after == users_before
    assert versions == [1, 2, 3, 4, 5, 6, 7]
    engine.dispose()


def test_parallel_startup_only_migrates_once(tmp_path, migrations):
    engine = _sqlite_engine(tmp_path / "parallel.db")
    _create_legacy_schema(engine, include_users=False)

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(migrations.upgrade_schema, engine) for _ in range(4)]
        for future in futures:
            future.result()

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migration")).scalar_one() == 7
        assert connection.execute(text("SELECT COUNT(*) FROM user")).scalar_one() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM month WHERE user_id IS NULL")).scalar_one() == 0
    engine.dispose()


def test_legacy_account_geometry_is_preserved_and_normalized(tmp_path, migrations):
    engine = _sqlite_engine(tmp_path / "legacy-geometry.db")
    _create_legacy_schema(engine, include_users=True, include_geometry=True)
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE account
                SET pos_x = -50, pos_y = -20, width = 200, height = 100
                WHERE id = 20
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO account (id, month_id, name, pos_x, pos_y, width, height)
                VALUES
                    (21, 11, 'Right edge', 1100, 10, 300, 1300),
                    (22, 11, 'Oversized', 900, 0, 5000, 900),
                    (23, 11, 'Already valid', 100, 50, 600, 700),
                    (24, 11, 'Missing geometry', NULL, NULL, NULL, NULL)
                """
            )
        )

    migrations.upgrade_schema(engine)
    with engine.connect() as connection:
        normalized_once = connection.execute(
            text("SELECT id, name, pos_x, pos_y, width, height FROM account ORDER BY id")
        ).all()

    migrations.upgrade_schema(engine)
    with engine.connect() as connection:
        normalized_twice = connection.execute(
            text("SELECT id, name, pos_x, pos_y, width, height FROM account ORDER BY id")
        ).all()
        versions = connection.execute(text("SELECT version FROM schema_migration ORDER BY version")).scalars().all()

    assert normalized_once == [
        (20, "Current", 0, 0, 400, 350),
        (21, "Right edge", 800, 10, 400, 1200),
        (22, "Oversized", 0, 0, 1200, 900),
        (23, "Already valid", 100, 50, 600, 700),
        (24, "Missing geometry", 0, 0, 400, 350),
    ]
    assert normalized_twice == normalized_once
    assert versions == [1, 2, 3, 4, 5, 6, 7]
    engine.dispose()


def test_transfer_destination_is_added_and_backfilled(tmp_path, migrations):
    engine = _sqlite_engine(tmp_path / "legacy-transfer.db")
    _create_legacy_schema(engine, include_users=True)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE income (
                id INTEGER NOT NULL PRIMARY KEY,
                account_id INTEGER NOT NULL REFERENCES account (id),
                name VARCHAR(100) NOT NULL,
                amount NUMERIC(12, 2) NOT NULL,
                contributor VARCHAR(50)
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE bill (
                id INTEGER NOT NULL PRIMARY KEY,
                account_id INTEGER NOT NULL REFERENCES account (id),
                linked_income_id INTEGER REFERENCES income (id),
                name VARCHAR(100) NOT NULL,
                amount NUMERIC(12, 2) NOT NULL
            )
            """
        )
        connection.execute(
            text(
                "INSERT INTO income (id, account_id, name, amount, contributor) "
                "VALUES (30, 20, 'Transfer from Current', 25.00, 'Alice')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO bill (id, account_id, linked_income_id, name, amount) "
                "VALUES (40, 20, 30, 'Transfer', 25.00)"
            )
        )

    migrations.upgrade_schema(engine)
    migrations.upgrade_schema(engine)

    bill_columns = {column["name"] for column in inspect(engine).get_columns("bill")}
    bill_indexes = {index["name"] for index in inspect(engine).get_indexes("bill")}
    bill_foreign_keys = inspect(engine).get_foreign_keys("bill")
    with engine.connect() as connection:
        bill = connection.execute(
            text("SELECT id, account_id, linked_income_id, transfer_account_id, name FROM bill")
        ).one()
        income = connection.execute(text("SELECT id, account_id, name FROM income")).one()

    assert "transfer_account_id" in bill_columns
    assert "ix_bill_transfer_account_id" in bill_indexes
    assert any(
        foreign_key.get("referred_table") == "account"
        and foreign_key.get("constrained_columns") == ["transfer_account_id"]
        for foreign_key in bill_foreign_keys
    )
    assert bill == (40, 20, 30, 20, "Transfer")
    assert income == (30, 20, "Transfer from Current")
    engine.dispose()


def test_legacy_sqlite_owner_constraints_are_enforced(tmp_path, migrations):
    engine = _sqlite_engine(tmp_path / "legacy-owner-constraints.db")
    _create_legacy_schema(engine, include_users=True)
    migrations.upgrade_schema(engine)

    with pytest.raises(IntegrityError, match="month.user_id must reference user"), engine.begin() as connection:
        connection.execute(text("INSERT INTO month (id, name, user_id) VALUES (13, 'Unowned', NULL)"))

    with pytest.raises(IntegrityError, match="month.user_id must reference user"), engine.begin() as connection:
        connection.execute(text("INSERT INTO month (id, name, user_id) VALUES (14, 'Unknown', 999)"))

    with pytest.raises(IntegrityError, match="user is referenced by month"), engine.begin() as connection:
        connection.execute(text("DELETE FROM user WHERE id = 3"))

    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM month")).scalar_one() == 2
        assert connection.execute(text("SELECT COUNT(*) FROM user")).scalar_one() == 2
    engine.dispose()
