# models.py
from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db, login_manager


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class Month(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    archived = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    accounts = db.relationship("Account", backref="month", lazy=True, cascade="all, delete-orphan")


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    month_id = db.Column(db.Integer, db.ForeignKey("month.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    pos_x = db.Column(db.Integer, default=0)
    pos_y = db.Column(db.Integer, default=0)
    width = db.Column(db.Integer, default=300)
    height = db.Column(db.Integer, default=250)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    bills = db.relationship("Bill", backref="account", lazy=True, cascade="all, delete-orphan")
    incomes = db.relationship("Income", backref="account", lazy=True, cascade="all, delete-orphan")


class Bill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    linked_income_id = db.Column(db.Integer, db.ForeignKey("income.id"), nullable=True)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    due_date = db.Column(db.Date, nullable=True)
    category = db.Column(db.String(50), default="general")
    is_paid = db.Column(db.Boolean, default=False)
    owner = db.Column(db.String(50), default="Shared")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    linked_income = db.relationship("Income", foreign_keys=[linked_income_id], uselist=False)


class Income(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    account_id = db.Column(db.Integer, db.ForeignKey("account.id"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    contributor = db.Column(db.String(50), default="Unknown")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
