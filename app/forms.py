from decimal import Decimal

from flask_wtf import FlaskForm
from wtforms import BooleanField, DateField, DecimalField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import (
    DataRequired,
    EqualTo,
    InputRequired,
    Length,
    NumberRange,
    Optional,
    Regexp,
    StopValidation,
    ValidationError,
)


def strip_text(value):
    return value.strip() if value else value


def validate_currency_precision(_form, field):
    value = field.data
    if value is None:
        return
    if not value.is_finite():
        raise StopValidation("Enter a finite amount.")
    if value.as_tuple().exponent < -2:
        raise StopValidation("Use no more than two decimal places.")


amount_validators = [
    InputRequired(),
    validate_currency_precision,
    NumberRange(
        min=Decimal("0.01"), max=Decimal("9999999999.99"), message="Enter an amount between 0.01 and 9999999999.99."
    ),
]


class RegistrationForm(FlaskForm):
    username = StringField(
        "Username",
        filters=[strip_text],
        validators=[
            DataRequired(),
            Length(min=3, max=64),
            Regexp(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", message="Use letters, numbers, dots, hyphens, or underscores."),
        ],
    )
    password = PasswordField("Password", validators=[DataRequired(), Length(min=12, max=128)])
    confirm_password = PasswordField("Confirm Password", validators=[DataRequired(), EqualTo("password")])
    submit = SubmitField("Register")


class LoginForm(FlaskForm):
    username = StringField("Username", filters=[strip_text], validators=[DataRequired(), Length(max=64)])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")


class MonthForm(FlaskForm):
    name = StringField("Month Name", filters=[strip_text], validators=[DataRequired(), Length(max=50)])
    submit = SubmitField("Create Month")


class AccountForm(FlaskForm):
    name = StringField("Account Name", filters=[strip_text], validators=[DataRequired(), Length(max=100)])
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
    name = StringField("Bill Name", filters=[strip_text], validators=[DataRequired(), Length(max=100)])
    amount = DecimalField("Amount", places=2, rounding=None, validators=amount_validators)
    due_date = DateField("Due Date (YYYY-MM-DD)", format="%Y-%m-%d", validators=[Optional()])
    category = StringField("Category", filters=[strip_text], validators=[Optional(), Length(max=50)])
    owner = StringField("Owner", filters=[strip_text], validators=[Optional(), Length(max=50)])
    is_paid = BooleanField("Mark as Paid?")
    transfer = BooleanField("Is Transfer?")
    destination_account = SelectField(
        "Destination Account", choices=[], coerce=destination_coerce, validators=[Optional()]
    )
    submit = SubmitField("Save Bill")

    def validate_destination_account(self, field):
        if self.transfer.data and not field.data:
            raise ValidationError("Choose a destination account for a transfer.")


class IncomeForm(FlaskForm):
    name = StringField("Income Name", filters=[strip_text], validators=[DataRequired(), Length(max=100)])
    amount = DecimalField("Amount", places=2, rounding=None, validators=amount_validators)
    contributor = StringField("Contributor", filters=[strip_text], validators=[Optional(), Length(max=50)])
    submit = SubmitField("Save Income")
