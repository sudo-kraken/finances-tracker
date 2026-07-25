from decimal import Decimal

from dateutil.relativedelta import relativedelta
from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .forms import AccountForm, BillForm, IncomeForm, LoginForm, MonthForm, RegistrationForm
from .models import Account, Bill, Income, Month, RegistrationGate, User
from .schema_migrations import (
    LEGACY_OWNER_PASSWORD_HASH,
    LEGACY_OWNER_USERNAME,
    is_legacy_owner,
)

bp = Blueprint("main", __name__)

CANVAS_WIDTH = 1200
CARD_WIDTH = 400
CARD_HEIGHT = 350
CARD_X_STEP = 420
CARD_Y_STEP = 370
MAX_CARD_HEIGHT = 1200
MAX_CANVAS_Y = 10000
MONTH_NAME_MAX_LENGTH = 50
INCOME_NAME_MAX_LENGTH = 100


def _registration_open():
    if current_app.config["ALLOW_REGISTRATION"]:
        return True
    if db.session.get(RegistrationGate, 1) is not None:
        return False
    users = db.session.execute(db.select(User.username, User.password_hash)).all()
    return not any(not is_legacy_owner(username, password_hash) for username, password_hash in users)


def _transfer_income_name(source_name):
    return f"Transfer from {source_name}"[:INCOME_NAME_MAX_LENGTH]


def _month_copy_name(name):
    suffix = " (Copy)"
    return f"{name[: MONTH_NAME_MAX_LENGTH - len(suffix)].rstrip()}{suffix}"


def _claim_first_registration():
    db.session.add(RegistrationGate(id=1))
    try:
        db.session.flush()
    except IntegrityError:
        db.session.rollback()
        return False
    return True


def _owned_month_or_404(month_id):
    month = db.session.scalar(db.select(Month).where(Month.id == month_id, Month.user_id == current_user.id))
    if month is None:
        abort(404)
    return month


def _owned_account_or_404(account_id):
    account = db.session.scalar(
        db.select(Account)
        .join(Month, Account.month_id == Month.id)
        .where(Account.id == account_id, Month.user_id == current_user.id)
    )
    if account is None:
        abort(404)
    return account


def _owned_bill_or_404(bill_id):
    bill = db.session.scalar(
        db.select(Bill)
        .join(Account, Bill.account_id == Account.id)
        .join(Month, Account.month_id == Month.id)
        .where(Bill.id == bill_id, Month.user_id == current_user.id)
    )
    if bill is None:
        abort(404)
    return bill


def _owned_income_or_404(income_id):
    income = db.session.scalar(
        db.select(Income)
        .join(Account, Income.account_id == Account.id)
        .join(Month, Account.month_id == Month.id)
        .where(Income.id == income_id, Month.user_id == current_user.id)
    )
    if income is None:
        abort(404)
    return income


def _flash_form_errors(form):
    for field_name, errors in form.errors.items():
        field = getattr(form, field_name, None)
        label = field.label.text if field is not None else field_name.replace("_", " ").title()
        for error in errors:
            flash(f"{label}: {error}", "error")


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.months"))
    return redirect(url_for("main.login"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.months"))
    if not _registration_open():
        flash("Registration is disabled. Ask the administrator to create an account.")
        return redirect(url_for("main.login"))

    form = RegistrationForm()
    if form.validate_on_submit():
        existing_user = User.query.filter(db.func.lower(User.username) == form.username.data.lower()).first()
        if existing_user:
            flash("Username already taken.")
            return redirect(url_for("main.register"))

        user = User(username=form.username.data)
        user.set_password(form.password.data)
        if not current_app.config["ALLOW_REGISTRATION"] and not _claim_first_registration():
            flash("Registration is disabled. Ask the administrator to create an account.")
            return redirect(url_for("main.login"))

        db.session.add(user)
        db.session.flush()

        legacy_owner = User.query.filter_by(
            username=LEGACY_OWNER_USERNAME,
            password_hash=LEGACY_OWNER_PASSWORD_HASH,
        ).first()
        if legacy_owner and is_legacy_owner(legacy_owner.username, legacy_owner.password_hash):
            Month.query.filter_by(user_id=legacy_owner.id).update({"user_id": user.id})
            db.session.delete(legacy_owner)

        db.session.commit()
        flash("User registered successfully.")
        return redirect(url_for("main.login"))
    return render_template("register.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.months"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter(db.func.lower(User.username) == form.username.data.lower()).first()
        if user is None or not user.check_password(form.password.data):
            flash("Invalid username or password.")
            return redirect(url_for("main.login"))
        login_user(user)
        return redirect(url_for("main.months"))
    return render_template("login.html", form=form, registration_open=_registration_open())


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.login"))


@bp.route("/months", methods=["GET", "POST"])
@login_required
def months():
    form = MonthForm()
    if form.validate_on_submit():
        m = Month(name=form.name.data, user_id=current_user.id)
        db.session.add(m)
        db.session.commit()
        flash("Month created.")
        return redirect(url_for("main.months"))
    if request.method == "POST":
        _flash_form_errors(form)

    months_list = Month.query.filter_by(user_id=current_user.id).order_by(Month.created_at.desc()).all()
    return render_template("months.html", form=form, months=months_list, month_edit_form=MonthForm())


@bp.route("/months/<int:month_id>", methods=["GET", "POST"])
@login_required
def month_details(month_id):
    month = _owned_month_or_404(month_id)
    account_form = AccountForm(prefix="account")
    bill_form = BillForm(prefix="bill")
    income_form = IncomeForm(prefix="income")

    # Create edit forms for modal popups:
    month_edit_form = MonthForm(obj=month)
    accounts = Account.query.filter_by(month_id=month.id).order_by(Account.created_at, Account.id).all()

    # Compute totals for each account
    for acc in accounts:
        total_bills = sum((b.amount or Decimal("0") for b in acc.bills), Decimal("0"))
        total_incomes = sum((i.amount or Decimal("0") for i in acc.incomes), Decimal("0"))
        acc.total_bills = total_bills
        acc.total_incomes = total_incomes
        acc.remainder = total_incomes - total_bills

    dest_choices = [(0, "-- No Transfer --"), *((acc.id, acc.name) for acc in accounts)]
    bill_form.destination_account.choices = dest_choices

    account_edit_forms = {}
    bill_edit_forms = {}
    income_edit_forms = {}
    for account in accounts:
        account_edit_forms[account.id] = AccountForm(formdata=None, obj=account)
        for bill in account.bills:
            edit_form = BillForm(formdata=None, obj=bill)
            edit_form.destination_account.choices = dest_choices
            edit_form.transfer.data = bool(bill.transfer_account_id or bill.linked_income_id)
            edit_form.destination_account.data = bill.transfer_account_id or (
                bill.linked_income.account_id if bill.linked_income else 0
            )
            bill_edit_forms[bill.id] = edit_form
        for income in account.incomes:
            income_edit_forms[income.id] = IncomeForm(formdata=None, obj=income)

    if "account-submit" in request.form:
        if account_form.validate_on_submit():
            account_count = len(accounts)
            column = account_count % 2
            row = account_count // 2
            new_acc = Account(
                month_id=month.id,
                name=account_form.name.data,
                pos_x=column * CARD_X_STEP,
                pos_y=row * CARD_Y_STEP,
                width=CARD_WIDTH,
                height=CARD_HEIGHT,
            )
            db.session.add(new_acc)
            db.session.commit()
            flash("Account added.")
            return redirect(url_for("main.month_details", month_id=month.id))
        else:
            _flash_form_errors(account_form)

    if "bill-submit" in request.form:
        if bill_form.validate_on_submit():
            account_id = request.form.get("account_id", type=int)
            acc = next((account for account in accounts if account.id == account_id), None)
            if acc is None:
                abort(404)
            if bill_form.transfer.data and bill_form.destination_account.data == acc.id:
                bill_form.destination_account.errors.append("A transfer must use a different destination account.")
                _flash_form_errors(bill_form)
            else:
                destination = None
                if bill_form.transfer.data:
                    destination = next(
                        (account for account in accounts if account.id == bill_form.destination_account.data),
                        None,
                    )
                    if destination is None:
                        abort(404)

                new_bill = Bill(
                    account_id=acc.id,
                    transfer_account_id=destination.id if destination else None,
                    name=bill_form.name.data,
                    amount=bill_form.amount.data,
                    due_date=bill_form.due_date.data,
                    category=bill_form.category.data,
                    owner=bill_form.owner.data,
                    is_paid=bill_form.is_paid.data,
                )
                db.session.add(new_bill)
                if destination and bill_form.is_paid.data:
                    new_income = Income(
                        account_id=destination.id,
                        name=_transfer_income_name(acc.name),
                        amount=bill_form.amount.data,
                        contributor=bill_form.owner.data,
                    )
                    db.session.add(new_income)
                    new_bill.linked_income = new_income
                db.session.commit()
                flash("Bill added.")
                return redirect(url_for("main.month_details", month_id=month.id))
        else:
            _flash_form_errors(bill_form)

    if "income-submit" in request.form:
        if income_form.validate_on_submit():
            account_id = request.form.get("account_id", type=int)
            acc = next((account for account in accounts if account.id == account_id), None)
            if acc is None:
                abort(404)
            new_income = Income(
                account_id=acc.id,
                name=income_form.name.data,
                amount=income_form.amount.data,
                contributor=income_form.contributor.data,
            )
            db.session.add(new_income)
            db.session.commit()
            flash("Income added.")
            return redirect(url_for("main.month_details", month_id=month.id))
        else:
            _flash_form_errors(income_form)

    canvas_height = max(
        1200,
        max((account.pos_y + account.height + 100 for account in accounts), default=0),
    )
    return render_template(
        "month_details.html",
        month=month,
        accounts=accounts,
        account_form=account_form,
        bill_form=bill_form,
        income_form=income_form,
        month_edit_form=month_edit_form,
        account_edit_forms=account_edit_forms,
        bill_edit_forms=bill_edit_forms,
        income_edit_forms=income_edit_forms,
        canvas_height=canvas_height,
    )


@bp.route("/account/<int:account_id>/update_position", methods=["POST"])
@login_required
def update_account_position(account_id):
    account = _owned_account_or_404(account_id)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "No JSON data provided"}), 400
    try:
        new_x = int(data.get("x"))
        new_y = int(data.get("y"))
        new_w = int(data.get("width"))
        new_h = int(data.get("height"))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid numeric data"}), 400

    if (
        new_x < 0
        or new_y < 0
        or new_w < CARD_WIDTH
        or new_h < CARD_HEIGHT
        or new_w > CANVAS_WIDTH
        or new_h > MAX_CARD_HEIGHT
        or new_x + new_w > CANVAS_WIDTH
        or new_y > MAX_CANVAS_Y
    ):
        return jsonify({"error": "Position or size is outside the allowed workspace"}), 400

    account.pos_x = new_x
    account.pos_y = new_y
    account.width = new_w
    account.height = new_h
    db.session.commit()
    return jsonify({"success": True})


@bp.route("/months/<int:month_id>/delete", methods=["POST"])
@login_required
def delete_month(month_id):
    month = _owned_month_or_404(month_id)
    db.session.delete(month)
    db.session.commit()
    flash("Month deleted.")
    return redirect(url_for("main.months"))


@bp.route("/months/<int:month_id>/duplicate", methods=["POST"])
@login_required
def duplicate_month(month_id):
    month = _owned_month_or_404(month_id)
    new_month = Month(name=_month_copy_name(month.name), user_id=current_user.id)
    db.session.add(new_month)
    db.session.flush()

    account_map = {}
    for acc in month.accounts:
        new_acc = Account(
            month_id=new_month.id, name=acc.name, pos_x=acc.pos_x, pos_y=acc.pos_y, width=acc.width, height=acc.height
        )
        db.session.add(new_acc)
        account_map[acc.id] = new_acc
    db.session.flush()

    income_map = {}
    for acc in month.accounts:
        for income in acc.incomes:
            copy_income = Income(
                account_id=account_map[acc.id].id,
                name=income.name,
                amount=income.amount,
                contributor=income.contributor,
            )
            db.session.add(copy_income)
            income_map[income.id] = copy_income
    db.session.flush()

    for acc in month.accounts:
        for b in acc.bills:
            new_due_date = b.due_date + relativedelta(months=1) if b.due_date else None
            copy_bill = Bill(
                account_id=account_map[acc.id].id,
                name=b.name,
                amount=b.amount,
                due_date=new_due_date,
                category=b.category,
                is_paid=b.is_paid,
                owner=b.owner,
                linked_income=income_map.get(b.linked_income_id),
                transfer_account=account_map.get(b.transfer_account_id),
            )
            db.session.add(copy_bill)
    db.session.commit()
    flash("Month duplicated successfully.")
    return redirect(url_for("main.months"))


@bp.route("/months/<int:month_id>/edit", methods=["POST"])
@login_required
def edit_month(month_id):
    month = _owned_month_or_404(month_id)
    form = MonthForm(obj=month)
    if form.validate_on_submit():
        month.name = form.name.data
        db.session.commit()
        flash("Month updated.")
        return redirect(url_for("main.month_details", month_id=month.id))
    _flash_form_errors(form)
    return redirect(url_for("main.month_details", month_id=month.id))


@bp.route("/account/<int:account_id>/delete", methods=["POST"])
@login_required
def delete_account(account_id):
    account = _owned_account_or_404(account_id)
    month_id = account.month_id

    for income in account.incomes:
        for linked_bill in Bill.query.filter_by(linked_income_id=income.id).all():
            linked_bill.linked_income = None
            linked_bill.transfer_account_id = None
    for transfer_bill in Bill.query.filter_by(transfer_account_id=account.id).all():
        transfer_bill.transfer_account_id = None
    for bill in account.bills:
        if bill.linked_income and bill.linked_income.account_id != account.id:
            db.session.delete(bill.linked_income)

    db.session.delete(account)
    db.session.commit()
    flash("Account deleted.")
    return redirect(url_for("main.month_details", month_id=month_id))


@bp.route("/account/<int:account_id>/edit", methods=["POST"])
@login_required
def edit_account(account_id):
    account = _owned_account_or_404(account_id)
    form = AccountForm(obj=account)
    if form.validate_on_submit():
        account.name = form.name.data
        for bill in account.bills:
            if bill.linked_income:
                bill.linked_income.name = _transfer_income_name(account.name)
        db.session.commit()
        flash("Account updated.")
        return redirect(url_for("main.month_details", month_id=account.month_id))
    _flash_form_errors(form)
    return redirect(url_for("main.month_details", month_id=account.month_id))


@bp.route("/bill/<int:bill_id>/delete", methods=["POST"])
@login_required
def delete_bill(bill_id):
    bill = _owned_bill_or_404(bill_id)
    month_id = bill.account.month_id
    if bill.linked_income_id:
        inc = db.session.get(Income, bill.linked_income_id)
        if inc:
            db.session.delete(inc)
    db.session.delete(bill)
    db.session.commit()
    flash("Bill deleted.")
    return redirect(url_for("main.month_details", month_id=month_id))


@bp.route("/bill/<int:bill_id>/edit", methods=["POST"])
@login_required
def edit_bill(bill_id):
    bill = _owned_bill_or_404(bill_id)
    form = BillForm(obj=bill)

    # Populate destination account choices for transfers:
    accounts = Account.query.filter_by(month_id=bill.account.month_id).all()
    dest_choices = [(0, "-- No Transfer --"), *((acc.id, acc.name) for acc in accounts)]
    form.destination_account.choices = dest_choices

    if form.validate_on_submit():
        if form.transfer.data and form.destination_account.data == bill.account_id:
            form.destination_account.errors.append("A transfer must use a different destination account.")
            _flash_form_errors(form)
            return redirect(url_for("main.month_details", month_id=bill.account.month_id))

        destination = None
        if form.transfer.data:
            destination = next(
                (account for account in accounts if account.id == form.destination_account.data),
                None,
            )
            if destination is None:
                abort(404)

        # Update basic fields
        bill.name = form.name.data
        bill.amount = form.amount.data
        bill.due_date = form.due_date.data
        bill.category = form.category.data
        bill.owner = form.owner.data
        bill.is_paid = form.is_paid.data
        bill.transfer_account_id = destination.id if destination else None
        if destination and bill.is_paid:
            if bill.linked_income_id:
                inc = db.session.get(Income, bill.linked_income_id)
                if inc:
                    inc.account_id = destination.id
                    inc.amount = bill.amount
                    inc.contributor = bill.owner
                    inc.name = _transfer_income_name(bill.account.name)
            else:
                new_inc = Income(
                    account_id=destination.id,
                    name=_transfer_income_name(bill.account.name),
                    amount=bill.amount,
                    contributor=bill.owner,
                )
                db.session.add(new_inc)
                bill.linked_income = new_inc
        else:
            if bill.linked_income_id:
                inc = db.session.get(Income, bill.linked_income_id)
                if inc:
                    db.session.delete(inc)
                bill.linked_income = None

        db.session.commit()
        flash("Bill updated.")
        return redirect(url_for("main.month_details", month_id=bill.account.month_id))
    _flash_form_errors(form)
    return redirect(url_for("main.month_details", month_id=bill.account.month_id))


@bp.route("/income/<int:income_id>/delete", methods=["POST"])
@login_required
def delete_income(income_id):
    income = _owned_income_or_404(income_id)
    month_id = income.account.month_id
    linked_bills = Bill.query.filter_by(linked_income_id=income_id).all()
    for b in linked_bills:
        b.linked_income_id = None
        b.transfer_account_id = None
    db.session.delete(income)
    db.session.commit()
    flash("Income deleted.")
    return redirect(url_for("main.month_details", month_id=month_id))


@bp.route("/income/<int:income_id>/edit", methods=["POST"])
@login_required
def edit_income(income_id):
    income = _owned_income_or_404(income_id)
    form = IncomeForm(obj=income)
    if form.validate_on_submit():
        income.name = form.name.data
        income.amount = form.amount.data
        income.contributor = form.contributor.data
        db.session.commit()
        flash("Income updated.")
        return redirect(url_for("main.month_details", month_id=income.account.month_id))
    _flash_form_errors(form)
    return redirect(url_for("main.month_details", month_id=income.account.month_id))


@bp.route("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        return {"status": "healthy"}, 200
    except Exception:
        current_app.logger.exception("Database health check failed")
        return {"status": "unhealthy"}, 503
