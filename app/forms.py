import re
from decimal import Decimal, InvalidOperation

from flask_wtf import FlaskForm
from wtforms import BooleanField, DateField, DecimalField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, EqualTo, Length, Optional, ValidationError


class RegistrationForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired(), Length(min=3, max=64)])
    password = PasswordField("Password", validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField("Confirm Password", validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Register")


class LoginForm(FlaskForm):
    username = StringField("Username", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")


class MonthForm(FlaskForm):
    name = StringField("Month Name", validators=[DataRequired()])
    submit = SubmitField("Create Month")


class AccountForm(FlaskForm):
    name = StringField("Account Name", validators=[DataRequired()])
    submit = SubmitField("Save Account")


def destination_coerce(val):
    """
    Custom coerce function for destination_account.
    - If val is '' or None, return 0
    - Otherwise, convert to int
    """
    if not val:
        return 0
    return int(val)


class BillForm(FlaskForm):
    name = StringField("Bill Name", validators=[DataRequired()])
    amount = DecimalField("Amount", validators=[DataRequired()])
    due_date = DateField("Due Date (YYYY-MM-DD)", format="%Y-%m-%d", validators=[Optional()])
    category = StringField("Category")
    owner = StringField("Owner")
    is_paid = BooleanField("Mark as Paid?")
    transfer = BooleanField("Is Transfer?")
    destination_account = SelectField(
        "Destination Account", choices=[], coerce=destination_coerce, validators=[Optional()]
    )
    submit = SubmitField("Save Bill")

    def validate_amount(self, field):
        raw = str(field.data)
        cleaned = re.sub(r"[^\d\.]+", "", raw)
        try:
            field.data = Decimal(cleaned)
        except (ValueError, InvalidOperation):
            raise ValidationError("Please enter a valid numeric amount (e.g. 2503.50).") from None


class IncomeForm(FlaskForm):
    name = StringField("Income Name", validators=[DataRequired()])
    amount = DecimalField("Amount", validators=[DataRequired()])
    contributor = StringField("Contributor")
    submit = SubmitField("Save Income")

    def validate_amount(self, field):
        raw = str(field.data)
        cleaned = re.sub(r"[^\d\.]+", "", raw)
        try:
            field.data = Decimal(cleaned)
        except (ValueError, InvalidOperation):
            raise ValidationError("Please enter a valid numeric amount (e.g. 1500.00).") from None
