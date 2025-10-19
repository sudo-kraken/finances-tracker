from dateutil.relativedelta import relativedelta
from flask import Blueprint, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from .extensions import db
from .forms import AccountForm, BillForm, IncomeForm, LoginForm, MonthForm, RegistrationForm
from .models import Account, Bill, Income, Month, User

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("main.months"))
    return redirect(url_for("main.login"))


@bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.months"))
    form = RegistrationForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash("Username already taken.")
            return redirect(url_for("main.register"))
        user = User(username=form.username.data)
        user.set_password(form.password.data)
        db.session.add(user)
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
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash("Invalid username or password.")
            return redirect(url_for("main.login"))
        login_user(user)
        return redirect(url_for("main.months"))
    return render_template("login.html", form=form)


@bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("main.login"))


@bp.route("/months", methods=["GET", "POST"])
@login_required
def months():
    form = MonthForm()
    if form.validate_on_submit():
        m = Month(name=form.name.data)
        db.session.add(m)
        db.session.commit()
        flash("Month created.")
        return redirect(url_for("main.months"))
    months_list = Month.query.order_by(Month.created_at.desc()).all()
    return render_template("months.html", form=form, months=months_list, month_edit_form=MonthForm())


@bp.route("/months/<int:month_id>", methods=["GET", "POST"])
@login_required
def month_details(month_id):
    month = Month.query.get_or_404(month_id)
    account_form = AccountForm(prefix="account")
    bill_form = BillForm(prefix="bill")
    income_form = IncomeForm(prefix="income")

    # Create edit forms for modal popups:
    month_edit_form = MonthForm(obj=month)
    account_edit_form = AccountForm()  # Will be used in each account modal (values set in template)
    bill_edit_form = BillForm()  # Will be used in each bill modal
    income_edit_form = IncomeForm()  # Will be used in each income modal

    # Gather all accounts for this month
    accounts = Account.query.filter_by(month_id=month.id).all()

    # Compute totals for each account
    for acc in accounts:
        total_bills = 0
        total_incomes = 0
        for b in acc.bills:
            try:
                total_bills += float(b.amount or 0)
            except Exception:
                total_bills += 0
        for i in acc.incomes:
            try:
                total_incomes += float(i.amount or 0)
            except Exception:
                total_incomes += 0
        acc.total_bills = total_bills
        acc.total_incomes = total_incomes
        acc.remainder = total_incomes - total_bills

    # Populate BillForm destination_account choices
    dest_choices = [(0, "-- No Transfer --")]
    for acc in accounts:
        dest_choices.append((acc.id, acc.name))
    bill_form.destination_account.choices = dest_choices
    bill_edit_form.destination_account.choices = dest_choices

    if account_form.validate_on_submit() and "account-submit" in request.form:
        new_acc = Account(month_id=month.id, name=account_form.name.data)
        db.session.add(new_acc)
        db.session.commit()
        flash("Account added.")
        return redirect(url_for("main.month_details", month_id=month.id))

    if bill_form.validate_on_submit() and "bill-submit" in request.form:
        account_id = request.form.get("account_id")
        acc = Account.query.get(account_id)
        if acc and acc.month_id == month.id:
            new_bill = Bill(
                account_id=acc.id,
                name=bill_form.name.data,
                amount=bill_form.amount.data,
                due_date=bill_form.due_date.data,
                category=bill_form.category.data,
                owner=bill_form.owner.data,
                is_paid=bill_form.is_paid.data,
            )
            db.session.add(new_bill)
            db.session.commit()
            # Transfer logic...
            if bill_form.transfer.data and bill_form.is_paid.data:
                dest_id = bill_form.destination_account.data
                if dest_id != 0 and dest_id != acc.id:
                    dest_acc = Account.query.get(dest_id)
                    if dest_acc and dest_acc.month_id == month.id:
                        new_income = Income(
                            account_id=dest_acc.id,
                            name=f"Transfer from {acc.name}",
                            amount=bill_form.amount.data,
                            contributor=bill_form.owner.data,
                        )
                        db.session.add(new_income)
                        db.session.commit()
                        new_bill.linked_income_id = new_income.id
                        db.session.commit()
            flash("Bill added.")
        return redirect(url_for("main.month_details", month_id=month.id))

    if income_form.validate_on_submit() and "income-submit" in request.form:
        account_id = request.form.get("account_id")
        acc = Account.query.get(account_id)
        if acc and acc.month_id == month.id:
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

    return render_template(
        "month_details.html",
        month=month,
        accounts=accounts,
        account_form=account_form,
        bill_form=bill_form,
        income_form=income_form,
        month_edit_form=month_edit_form,
        account_edit_form=account_edit_form,
        bill_edit_form=bill_edit_form,
        income_edit_form=income_edit_form,
    )


@bp.route("/account/<int:account_id>/update_position", methods=["POST"])
@login_required
def update_account_position(account_id):
    account = Account.query.get_or_404(account_id)
    data = request.get_json()
    if not data:
        return jsonify({"error": "No JSON data provided"}), 400
    try:
        new_x = int(data.get("x"))
        new_y = int(data.get("y"))
        new_w = int(data.get("width"))
        new_h = int(data.get("height"))
    except (TypeError, ValueError):
        return jsonify({"error": "Invalid numeric data"}), 400

    account.pos_x = new_x
    account.pos_y = new_y
    account.width = new_w
    account.height = new_h
    db.session.commit()
    return jsonify({"success": True})


@bp.route("/months/<int:month_id>/delete", methods=["POST"])
@login_required
def delete_month(month_id):
    month = Month.query.get_or_404(month_id)
    db.session.delete(month)
    db.session.commit()
    flash("Month deleted.")
    return redirect(url_for("main.months"))


@bp.route("/months/<int:month_id>/duplicate", methods=["POST"])
@login_required
def duplicate_month(month_id):
    month = Month.query.get_or_404(month_id)
    new_month = Month(name=month.name + " (Copy)")
    db.session.add(new_month)
    db.session.commit()
    for acc in month.accounts:
        new_acc = Account(
            month_id=new_month.id, name=acc.name, pos_x=acc.pos_x, pos_y=acc.pos_y, width=acc.width, height=acc.height
        )
        db.session.add(new_acc)
        db.session.commit()
        for b in acc.bills:
            new_due_date = b.due_date + relativedelta(months=1) if b.due_date else None
            copy_bill = Bill(
                account_id=new_acc.id,
                name=b.name,
                amount=b.amount,
                due_date=new_due_date,
                category=b.category,
                is_paid=b.is_paid,
                owner=b.owner,
            )
            db.session.add(copy_bill)
        for i in acc.incomes:
            copy_income = Income(account_id=new_acc.id, name=i.name, amount=i.amount, contributor=i.contributor)
            db.session.add(copy_income)
    db.session.commit()
    flash("Month duplicated successfully.")
    return redirect(url_for("main.months"))


@bp.route("/months/<int:month_id>/edit", methods=["GET", "POST"])
@login_required
def edit_month(month_id):
    from .forms import MonthForm

    month = Month.query.get_or_404(month_id)
    form = MonthForm(obj=month)
    if form.validate_on_submit():
        month.name = form.name.data
        db.session.commit()
        flash("Month updated.")
        return redirect(url_for("main.month_details", month_id=month.id))
    return render_template("edit_month.html", form=form, month=month)


@bp.route("/account/<int:account_id>/delete", methods=["POST"])
@login_required
def delete_account(account_id):
    account = Account.query.get_or_404(account_id)
    month_id = account.month_id
    db.session.delete(account)
    db.session.commit()
    flash("Account deleted.")
    return redirect(url_for("main.month_details", month_id=month_id))


@bp.route("/account/<int:account_id>/edit", methods=["GET", "POST"])
@login_required
def edit_account(account_id):
    from .forms import AccountForm

    account = Account.query.get_or_404(account_id)
    form = AccountForm(obj=account)
    if form.validate_on_submit():
        account.name = form.name.data
        db.session.commit()
        flash("Account updated.")
        return redirect(url_for("main.month_details", month_id=account.month_id))
    return render_template("edit_account.html", form=form, account=account)


@bp.route("/bill/<int:bill_id>/delete", methods=["POST"])
@login_required
def delete_bill(bill_id):
    bill = Bill.query.get_or_404(bill_id)
    month_id = bill.account.month_id
    if bill.linked_income_id:
        inc = Income.query.get(bill.linked_income_id)
        if inc:
            db.session.delete(inc)
    db.session.delete(bill)
    db.session.commit()
    flash("Bill deleted.")
    return redirect(url_for("main.month_details", month_id=month_id))


@bp.route("/bill/<int:bill_id>/edit", methods=["GET", "POST"])
@login_required
def edit_bill(bill_id):
    from .forms import BillForm

    bill = Bill.query.get_or_404(bill_id)
    form = BillForm(obj=bill)

    # Populate destination account choices for transfers:
    accounts = Account.query.filter_by(month_id=bill.account.month_id).all()
    dest_choices = [(0, "-- No Transfer --")]
    for acc in accounts:
        dest_choices.append((acc.id, acc.name))
    form.destination_account.choices = dest_choices

    if form.validate_on_submit():
        # Update basic fields
        bill.name = form.name.data
        bill.amount = form.amount.data
        bill.due_date = form.due_date.data
        bill.category = form.category.data
        bill.owner = form.owner.data
        bill.is_paid = form.is_paid.data
        db.session.commit()

        # Process transfer logic:
        if form.transfer.data and bill.is_paid:
            dest_id = form.destination_account.data
            if dest_id != 0 and dest_id != bill.account_id:
                if bill.linked_income_id:
                    inc = Income.query.get(bill.linked_income_id)
                    if inc:
                        if inc.account_id != dest_id:
                            inc.account_id = dest_id
                        inc.amount = bill.amount
                        inc.contributor = bill.owner
                        inc.name = f"Transfer from {bill.account.name}"
                        db.session.commit()
                else:
                    dest_acc = Account.query.get(dest_id)
                    if dest_acc and dest_acc.month_id == bill.account.month_id:
                        new_inc = Income(
                            account_id=dest_acc.id,
                            name=f"Transfer from {bill.account.name}",
                            amount=bill.amount,
                            contributor=bill.owner,
                        )
                        db.session.add(new_inc)
                        db.session.commit()
                        bill.linked_income_id = new_inc.id
                        db.session.commit()
            else:
                if bill.linked_income_id:
                    inc = Income.query.get(bill.linked_income_id)
                    if inc:
                        db.session.delete(inc)
                    bill.linked_income_id = None
                    db.session.commit()
        else:
            if bill.linked_income_id:
                inc = Income.query.get(bill.linked_income_id)
                if inc:
                    db.session.delete(inc)
                bill.linked_income_id = None
                db.session.commit()

        flash("Bill updated.")
        return redirect(url_for("main.month_details", month_id=bill.account.month_id))
    else:
        print("DEBUG: Bill form did NOT validate.")
        print("DEBUG: form.errors =", form.errors)

    return render_template("edit_bill.html", form=form, bill=bill)


@bp.route("/income/<int:income_id>/delete", methods=["POST"])
@login_required
def delete_income(income_id):
    income = Income.query.get_or_404(income_id)
    month_id = income.account.month_id
    linked_bills = Bill.query.filter_by(linked_income_id=income_id).all()
    for b in linked_bills:
        b.linked_income_id = None
    db.session.delete(income)
    db.session.commit()
    flash("Income deleted.")
    return redirect(url_for("main.month_details", month_id=month_id))


@bp.route("/income/<int:income_id>/edit", methods=["GET", "POST"])
@login_required
def edit_income(income_id):
    from .forms import IncomeForm

    income = Income.query.get_or_404(income_id)
    form = IncomeForm(obj=income)
    if form.validate_on_submit():
        income.name = form.name.data
        income.amount = form.amount.data
        income.contributor = form.contributor.data
        db.session.commit()
        flash("Income updated.")
        return redirect(url_for("main.month_details", month_id=income.account.month_id))
    return render_template("edit_income.html", form=form, income=income)


@bp.route("/health")
def health():
    try:
        # Test database connection
        db.session.execute(db.text("SELECT 1"))
        return {"status": "healthy"}, 200
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}, 500
