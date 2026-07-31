from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager


def utc_now():
    """Return a naive UTC timestamp for the existing database columns."""

    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    # Werkzeug's default scrypt hashes are longer than the historical
    # 128-character column on databases that enforce VARCHAR lengths.
    password_hash = db.Column(db.String(512), nullable=False)

    months = db.relationship("Month", back_populates="user", cascade="all, delete-orphan")
    oidc_identities = db.relationship(
        "OidcIdentity",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class OidcIdentity(db.Model):
    __tablename__ = "oidc_identity"
    __table_args__ = (
        db.UniqueConstraint("issuer", "subject", name="uq_oidc_identity_issuer_subject"),
        db.UniqueConstraint("user_id", "issuer", name="uq_oidc_identity_user_issuer"),
    )

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer,
        db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    issuer = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    email = db.Column(db.String(320), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    last_login_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", back_populates="oidc_identities")


class RegistrationGate(db.Model):
    """Single-row database guard for first-user registration."""

    id = db.Column(db.Integer, primary_key=True)
    claimed_at = db.Column(db.DateTime, nullable=False, default=utc_now)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


class Month(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(50), nullable=False)
    archived = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utc_now)

    user = db.relationship("User", back_populates="months")
    accounts = db.relationship("Account", backref="month", lazy=True, cascade="all, delete-orphan")


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    month_id = db.Column(db.Integer, db.ForeignKey("month.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    pos_x = db.Column(db.Integer, default=0)
    pos_y = db.Column(db.Integer, default=0)
    width = db.Column(db.Integer, default=400)
    height = db.Column(db.Integer, default=350)
    created_at = db.Column(db.DateTime, default=utc_now)

    bills = db.relationship(
        "Bill",
        foreign_keys="Bill.account_id",
        backref="account",
        lazy=True,
        cascade="all, delete-orphan",
    )
    incomes = db.relationship("Income", backref="account", lazy=True, cascade="all, delete-orphan")


class Bill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    linked_income_id = db.Column(db.Integer, db.ForeignKey("income.id"), nullable=True)
    transfer_account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=True, index=True)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    due_date = db.Column(db.Date, nullable=True)
    category = db.Column(db.String(50), default="general")
    is_paid = db.Column(db.Boolean, default=False)
    owner = db.Column(db.String(50), default="Shared")
    created_at = db.Column(db.DateTime, default=utc_now)

    linked_income = db.relationship("Income", foreign_keys=[linked_income_id], uselist=False)
    transfer_account = db.relationship("Account", foreign_keys=[transfer_account_id])


class Income(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    contributor = db.Column(db.String(50), default="Unknown")
    created_at = db.Column(db.DateTime, default=utc_now)
