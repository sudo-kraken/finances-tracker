from __future__ import annotations

from contextlib import contextmanager
from decimal import Decimal
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from flask import template_rendered

PASSWORD = "correct-horse-123"


class FormInspector(HTMLParser):
    """Collect enough form metadata to verify the generated HTML."""

    def __init__(self):
        super().__init__()
        self.forms = []
        self.ids = []
        self._form = None
        self._select_name = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        element_id = attributes.get("id")
        if element_id:
            self.ids.append(element_id)

        if tag == "form":
            self._form = {
                "action": attributes.get("action", ""),
                "method": attributes.get("method", "get").lower(),
                "csrf_tokens": [],
                "selected": {},
            }
            self.forms.append(self._form)
        elif tag == "input" and self._form is not None:
            if attributes.get("name", "").endswith("csrf_token"):
                self._form["csrf_tokens"].append(attributes.get("value", ""))
        elif tag == "select" and self._form is not None:
            self._select_name = attributes.get("name")
        elif tag == "option" and self._form is not None and self._select_name:
            if "selected" in attributes:
                self._form["selected"][self._select_name] = attributes.get("value")

    def handle_endtag(self, tag):
        if tag == "select":
            self._select_name = None
        elif tag == "form":
            self._form = None


def inspect_html(response):
    inspector = FormInspector()
    inspector.feed(response.get_data(as_text=True))
    return inspector


def csrf_token_from(response):
    inspector = inspect_html(response)
    tokens = [token for form in inspector.forms for token in form["csrf_tokens"] if token]
    assert tokens, "The rendered page did not contain a CSRF token."
    return tokens[0]


def add_user(db, username):
    from app.models import User

    user = User(username=username)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


def log_in(client, username):
    response = client.post(
        "/login",
        data={"username": username, "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/months")
    return response


def build_finances(db, username="alice"):
    from app.models import Account, Bill, Income, Month

    user = add_user(db, username)
    month = Month(name=f"{username.title()} Month", user_id=user.id)
    db.session.add(month)
    db.session.commit()

    source = Account(month_id=month.id, name=f"{username.title()} Current")
    destination = Account(month_id=month.id, name=f"{username.title()} Savings")
    db.session.add_all([source, destination])
    db.session.commit()

    linked_income = Income(
        account_id=destination.id,
        name=f"Transfer from {source.name}",
        amount=Decimal("25.00"),
        contributor=username.title(),
    )
    ordinary_income = Income(
        account_id=source.id,
        name=f"{username.title()} Salary",
        amount=Decimal("100.00"),
        contributor=username.title(),
    )
    db.session.add_all([linked_income, ordinary_income])
    db.session.commit()

    bill = Bill(
        account_id=source.id,
        linked_income_id=linked_income.id,
        transfer_account_id=destination.id,
        name=f"{username.title()} Transfer",
        amount=Decimal("25.00"),
        category="Savings",
        owner=username.title(),
        is_paid=True,
    )
    db.session.add(bill)
    db.session.commit()

    return SimpleNamespace(
        user=user,
        month=month,
        source=source,
        destination=destination,
        bill=bill,
        linked_income=linked_income,
        ordinary_income=ordinary_income,
    )


@contextmanager
def captured_templates(app):
    rendered = []

    def record(_sender, template, context, **_extra):
        rendered.append((template, context))

    template_rendered.connect(record, app)
    try:
        yield rendered
    finally:
        template_rendered.disconnect(record, app)


@pytest.fixture
def csrf_app(app_module):
    from app.extensions import db

    application = app_module.create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "csrf-integration-test-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "WTF_CSRF_ENABLED": True,
        }
    )
    yield application
    with application.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture
def csrf_client(csrf_app):
    return csrf_app.test_client()


def test_registration_login_and_post_only_logout(client, app, db, monkeypatch):
    from app.models import User

    monkeypatch.setitem(app.config, "ALLOW_REGISTRATION", True)
    registration = client.post(
        "/register",
        data={
            "username": "alice",
            "password": PASSWORD,
            "confirm_password": PASSWORD,
        },
        follow_redirects=False,
    )
    assert registration.status_code == 302
    assert registration.headers["Location"].endswith("/login")

    with app.app_context():
        assert User.query.filter_by(username="alice").count() == 1

    duplicate = client.post(
        "/register",
        data={
            "username": "alice",
            "password": PASSWORD,
            "confirm_password": PASSWORD,
        },
        follow_redirects=True,
    )
    assert duplicate.status_code == 200
    assert b"already taken" in duplicate.data

    bad_login = client.post(
        "/login",
        data={"username": "alice", "password": "incorrect-password"},
        follow_redirects=True,
    )
    assert bad_login.status_code == 200
    assert b"Invalid username or password" in bad_login.data

    log_in(client, "alice")
    assert client.get("/months").status_code == 200
    assert client.get("/logout").status_code == 405


def test_first_registration_claims_legacy_data(client, app, db):
    from app.models import Month, User
    from app.schema_migrations import LEGACY_OWNER_PASSWORD_HASH, LEGACY_OWNER_USERNAME

    legacy_owner = User(username=LEGACY_OWNER_USERNAME, password_hash=LEGACY_OWNER_PASSWORD_HASH)
    db.session.add(legacy_owner)
    db.session.flush()
    legacy_month = Month(name="Preserved legacy month", user_id=legacy_owner.id)
    db.session.add(legacy_month)
    db.session.commit()
    legacy_month_id = legacy_month.id

    response = client.post(
        "/register",
        data={
            "username": "alice",
            "password": PASSWORD,
            "confirm_password": PASSWORD,
        },
    )

    assert response.status_code == 302
    with app.app_context():
        owner = User.query.filter_by(username="alice").one()
        assert db.session.get(Month, legacy_month_id).user_id == owner.id
        assert User.query.filter_by(username=LEGACY_OWNER_USERNAME).count() == 0


def test_registration_closes_after_first_real_user(client, db):
    add_user(db, "alice")

    response = client.get("/register", follow_redirects=True)

    assert response.status_code == 200
    assert b"Registration is disabled" in response.data

    logout = client.post("/logout", follow_redirects=False)
    assert logout.status_code == 302
    assert logout.headers["Location"].startswith("/login")
    assert client.get("/months").status_code == 302


def test_stale_first_registration_form_cannot_create_a_second_user(client, app, db, monkeypatch):
    import app.routes as routes
    from app.models import RegistrationGate, User

    db.session.add(RegistrationGate(id=1))
    db.session.commit()
    monkeypatch.setattr(routes, "_registration_open", lambda: True)

    response = client.post(
        "/register",
        data={
            "username": "racing-user",
            "password": PASSWORD,
            "confirm_password": PASSWORD,
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Registration is disabled" in response.data
    with app.app_context():
        assert User.query.filter_by(username="racing-user").count() == 0


def test_real_user_with_reserved_legacy_name_is_never_claimed(client, app, db, monkeypatch):
    from app.models import Month, User
    from app.schema_migrations import LEGACY_OWNER_USERNAME

    existing_user = add_user(db, LEGACY_OWNER_USERNAME)
    month = Month(name="Existing private data", user_id=existing_user.id)
    db.session.add(month)
    db.session.commit()
    existing_user_id = existing_user.id
    month_id = month.id

    closed = client.get("/register", follow_redirects=True)
    assert b"Registration is disabled" in closed.data

    monkeypatch.setitem(app.config, "ALLOW_REGISTRATION", True)
    response = client.post(
        "/register",
        data={
            "username": "alice",
            "password": PASSWORD,
            "confirm_password": PASSWORD,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        reserved_user = db.session.get(User, existing_user_id)
        assert reserved_user is not None
        assert reserved_user.check_password(PASSWORD)
        assert db.session.get(Month, month_id).user_id == existing_user_id


def test_registration_and_login_work_with_csrf_enabled(csrf_client, csrf_app):
    from app.extensions import db
    from app.models import User

    register_page = csrf_client.get("/register")
    register_token = csrf_token_from(register_page)
    registration = csrf_client.post(
        "/register",
        data={
            "csrf_token": register_token,
            "username": "alice",
            "password": PASSWORD,
            "confirm_password": PASSWORD,
        },
        follow_redirects=False,
    )
    assert registration.status_code == 302

    with csrf_app.app_context():
        assert User.query.filter_by(username="alice").count() == 1

    login_page = csrf_client.get("/login")
    login = csrf_client.post(
        "/login",
        data={
            "csrf_token": csrf_token_from(login_page),
            "username": "alice",
            "password": PASSWORD,
        },
        follow_redirects=False,
    )
    assert login.status_code == 302
    assert login.headers["Location"].endswith("/months")

    with csrf_app.app_context():
        db.session.remove()


def test_months_are_created_for_and_listed_only_to_the_current_user(client, app, db):
    from app.models import Month

    alice = add_user(db, "alice")
    bob = add_user(db, "bob")
    alice_month = Month(name="Alice Private Month", user_id=alice.id)
    bob_month = Month(name="Bob Private Month", user_id=bob.id)
    db.session.add_all([alice_month, bob_month])
    db.session.commit()

    log_in(client, "alice")
    response = client.get("/months")
    assert response.status_code == 200
    assert b"Alice Private Month" in response.data
    assert b"Bob Private Month" not in response.data

    created = client.post("/months", data={"name": "Alice New Month"}, follow_redirects=False)
    assert created.status_code == 302
    with app.app_context():
        new_month = Month.query.filter_by(name="Alice New Month").one()
        assert new_month.user_id == alice.id


@pytest.mark.parametrize(
    ("method", "path_template", "payload_kind"),
    [
        ("GET", "/months/{month_id}", "none"),
        ("POST", "/months/{month_id}/delete", "none"),
        ("POST", "/months/{month_id}/duplicate", "none"),
        ("POST", "/months/{month_id}/edit", "month"),
        ("POST", "/account/{source_id}/delete", "none"),
        ("POST", "/account/{source_id}/edit", "account"),
        ("POST", "/account/{source_id}/update_position", "position"),
        ("POST", "/bill/{bill_id}/delete", "none"),
        ("POST", "/bill/{bill_id}/edit", "bill"),
        ("POST", "/income/{ordinary_income_id}/delete", "none"),
        ("POST", "/income/{ordinary_income_id}/edit", "income"),
    ],
)
def test_foreign_resources_return_404(client, app, db, method, path_template, payload_kind):
    from app.models import Month

    alice = build_finances(db, "alice")
    build_finances(db, "bob")
    log_in(client, "bob")

    identifiers = {
        "month_id": alice.month.id,
        "source_id": alice.source.id,
        "bill_id": alice.bill.id,
        "ordinary_income_id": alice.ordinary_income.id,
    }
    path = path_template.format(**identifiers)
    request_arguments = {}
    if payload_kind == "month":
        request_arguments["data"] = {"name": "Stolen Month"}
    elif payload_kind == "account":
        request_arguments["data"] = {"name": "Stolen Account"}
    elif payload_kind == "position":
        request_arguments["json"] = {"x": 0, "y": 0, "width": 400, "height": 350}
    elif payload_kind == "bill":
        request_arguments["data"] = {
            "name": "Stolen Bill",
            "amount": "1.00",
            "category": "Other",
            "owner": "Bob",
        }
    elif payload_kind == "income":
        request_arguments["data"] = {
            "name": "Stolen Income",
            "amount": "1.00",
            "contributor": "Bob",
        }

    response = client.open(path, method=method, **request_arguments)
    assert response.status_code == 404

    with app.app_context():
        month = db.session.get(Month, identifiers["month_id"])
        assert month.name == "Alice Month"


def test_owned_month_cannot_be_used_to_mutate_a_foreign_account(client, app, db):
    from app.models import Bill

    alice = build_finances(db, "alice")
    bob = build_finances(db, "bob")
    log_in(client, "alice")

    response = client.post(
        f"/months/{alice.month.id}",
        data={
            "account_id": bob.source.id,
            "bill-name": "Injected bill",
            "bill-amount": "10.00",
            "bill-category": "Other",
            "bill-owner": "Alice",
            "bill-submit": "Save Bill",
        },
    )
    assert response.status_code == 404
    with app.app_context():
        assert Bill.query.filter_by(name="Injected bill").count() == 0


def test_transfer_cannot_target_its_source_account(client, app, db):
    from app.models import Bill

    finances = build_finances(db, "alice")
    month_id = finances.month.id
    source_id = finances.source.id
    log_in(client, "alice")

    response = client.post(
        f"/months/{month_id}",
        data={
            "account_id": source_id,
            "bill-name": "Circular transfer",
            "bill-amount": "10.00",
            "bill-is_paid": "y",
            "bill-transfer": "y",
            "bill-destination_account": str(source_id),
            "bill-submit": "Save Bill",
        },
    )

    assert response.status_code == 200
    assert b"different destination account" in response.data
    with app.app_context():
        assert Bill.query.filter_by(name="Circular transfer").count() == 0


def test_unpaid_transfer_preserves_destination_and_creates_income_when_paid(client, app, db):
    from app.models import Bill

    finances = build_finances(db, "alice")
    log_in(client, "alice")

    created = client.post(
        f"/months/{finances.month.id}",
        data={
            "account_id": finances.source.id,
            "bill-name": "Scheduled transfer",
            "bill-amount": "10.25",
            "bill-category": "Savings",
            "bill-owner": "Alice",
            "bill-transfer": "y",
            "bill-destination_account": str(finances.destination.id),
            "bill-submit": "Save Bill",
        },
        follow_redirects=False,
    )
    assert created.status_code == 302

    with app.app_context():
        bill = Bill.query.filter_by(name="Scheduled transfer").one()
        bill_id = bill.id
        assert bill.is_paid is False
        assert bill.transfer_account_id == finances.destination.id
        assert bill.linked_income_id is None

    details = client.get(f"/months/{finances.month.id}")
    edit_form = next(form for form in inspect_html(details).forms if form["action"].endswith(f"/bill/{bill_id}/edit"))
    assert str(finances.destination.id) in edit_form["selected"].values()

    paid = client.post(
        f"/bill/{bill_id}/edit",
        data={
            "name": "Scheduled transfer",
            "amount": "10.25",
            "category": "Savings",
            "owner": "Alice",
            "is_paid": "y",
            "transfer": "y",
            "destination_account": str(finances.destination.id),
        },
        follow_redirects=False,
    )
    assert paid.status_code == 302

    with app.app_context():
        bill = db.session.get(Bill, bill_id)
        assert bill.transfer_account_id == finances.destination.id
        assert bill.linked_income is not None
        assert bill.linked_income.account_id == finances.destination.id
        assert bill.linked_income.amount == Decimal("10.25")


def test_cross_user_transfer_destination_is_rejected(client, app, db):
    from app.models import Bill

    alice = build_finances(db, "alice")
    bob = build_finances(db, "bob")
    original_income_id = alice.bill.linked_income_id
    log_in(client, "alice")

    response = client.post(
        f"/bill/{alice.bill.id}/edit",
        data={
            "name": alice.bill.name,
            "amount": "40.00",
            "category": alice.bill.category,
            "owner": alice.bill.owner,
            "is_paid": "y",
            "transfer": "y",
            "destination_account": str(bob.destination.id),
        },
    )
    assert response.status_code in {302, 400}

    with app.app_context():
        bill = db.session.get(Bill, alice.bill.id)
        assert bill.linked_income_id == original_income_id
        assert bill.linked_income.account_id == alice.destination.id
        assert bill.linked_income.amount == Decimal("25.00")


def test_all_rendered_mutating_forms_include_csrf_tokens(csrf_client, csrf_app):
    from app.extensions import db

    with csrf_app.app_context():
        finances = build_finances(db, "alice")
        month_id = finances.month.id

    login_page = csrf_client.get("/login")
    login = csrf_client.post(
        "/login",
        data={
            "csrf_token": csrf_token_from(login_page),
            "username": "alice",
            "password": PASSWORD,
        },
    )
    assert login.status_code == 302

    for path in ("/months", f"/months/{month_id}"):
        response = csrf_client.get(path)
        assert response.status_code == 200
        inspector = inspect_html(response)
        post_forms = [form for form in inspector.forms if form["method"] == "post"]
        assert post_forms
        assert all(form["csrf_tokens"] for form in post_forms), [
            form["action"] for form in post_forms if not form["csrf_tokens"]
        ]


def test_csrf_rejects_tokenless_html_and_json_mutations(csrf_client, csrf_app):
    from app.extensions import db
    from app.models import Month

    with csrf_app.app_context():
        finances = build_finances(db, "alice")
        account_id = finances.source.id
        month_id = finances.month.id

    login_page = csrf_client.get("/login")
    csrf_client.post(
        "/login",
        data={
            "csrf_token": csrf_token_from(login_page),
            "username": "alice",
            "password": PASSWORD,
        },
    )

    assert csrf_client.post("/months", data={"name": "No Token"}).status_code == 400
    assert (
        csrf_client.post(
            f"/account/{account_id}/update_position",
            json={"x": 0, "y": 0, "width": 400, "height": 350},
        ).status_code
        == 400
    )
    assert csrf_client.post("/logout").status_code == 400

    months_page = csrf_client.get("/months")
    token = csrf_token_from(months_page)
    created = csrf_client.post(
        "/months",
        data={"csrf_token": token, "name": "With Token"},
        follow_redirects=False,
    )
    assert created.status_code == 302

    detail_page = csrf_client.get(f"/months/{month_id}")
    position = csrf_client.post(
        f"/account/{account_id}/update_position",
        json={"x": 50, "y": 50, "width": 400, "height": 350},
        headers={"X-CSRFToken": csrf_token_from(detail_page)},
    )
    assert position.status_code == 200

    with csrf_app.app_context():
        assert Month.query.filter_by(name="No Token").count() == 0
        assert Month.query.filter_by(name="With Token").count() == 1

    assert csrf_client.get("/logout").status_code == 405
    logout_page = csrf_client.get("/months")
    logout = csrf_client.post(
        "/logout",
        data={"csrf_token": csrf_token_from(logout_page)},
        follow_redirects=False,
    )
    assert logout.status_code == 302
    assert logout.headers["Location"].endswith("/login")


@pytest.mark.parametrize("kind", ["bill", "income"])
def test_negative_amount_submissions_are_rejected(client, app, db, kind):
    from app.models import Bill, Income

    finances = build_finances(db, "alice")
    log_in(client, "alice")

    if kind == "bill":
        response = client.post(
            f"/months/{finances.month.id}",
            data={
                "account_id": finances.source.id,
                "bill-name": "Negative bill",
                "bill-amount": "-10.00",
                "bill-category": "Other",
                "bill-owner": "Alice",
                "bill-submit": "Save Bill",
            },
            follow_redirects=True,
        )
        model = Bill
        name = "Negative bill"
    else:
        response = client.post(
            f"/months/{finances.month.id}",
            data={
                "account_id": finances.source.id,
                "income-name": "Negative income",
                "income-amount": "-10.00",
                "income-contributor": "Alice",
                "income-submit": "Save Income",
            },
            follow_redirects=True,
        )
        model = Income
        name = "Negative income"

    assert response.status_code == 200
    assert b"between 0.01" in response.data
    with app.app_context():
        assert model.query.filter_by(name=name).count() == 0


def test_totals_remain_decimal_through_rendering(client, app, db):
    from app.models import Bill, Income

    finances = build_finances(db, "alice")
    source_id = finances.source.id
    month_id = finances.month.id
    db.session.query(Bill).delete()
    db.session.query(Income).delete()
    db.session.commit()
    db.session.remove()
    db.session.add_all(
        [
            Bill(account_id=source_id, name="One", amount=Decimal("0.10")),
            Bill(account_id=source_id, name="Two", amount=Decimal("0.20")),
            Income(
                account_id=source_id,
                name="Exact income",
                amount=Decimal("0.30"),
                contributor="Alice",
            ),
        ]
    )
    db.session.commit()
    log_in(client, "alice")

    with captured_templates(app) as rendered:
        response = client.get(f"/months/{month_id}")

    assert response.status_code == 200
    context = next(context for template, context in rendered if template.name == "month_details.html")
    account = next(account for account in context["accounts"] if account.id == source_id)
    assert isinstance(account.total_bills, Decimal)
    assert isinstance(account.total_incomes, Decimal)
    assert isinstance(account.remainder, Decimal)
    assert account.total_bills == Decimal("0.30")
    assert account.total_incomes == Decimal("0.30")
    assert account.remainder == Decimal("0.00")


def test_transfer_edit_form_selects_current_destination_and_has_unique_ids(client, db):
    from app.models import Bill

    finances = build_finances(db, "alice")
    second_bill = Bill(
        account_id=finances.source.id,
        name="Ordinary bill",
        amount=Decimal("5.00"),
    )
    db.session.add(second_bill)
    db.session.commit()
    log_in(client, "alice")

    response = client.get(f"/months/{finances.month.id}")
    assert response.status_code == 200
    inspector = inspect_html(response)
    assert len(inspector.ids) == len(set(inspector.ids))

    edit_form = next(form for form in inspector.forms if form["action"].endswith(f"/bill/{finances.bill.id}/edit"))
    selected_destinations = {
        value
        for name, value in edit_form["selected"].items()
        if name == "destination_account" or name.endswith("-destination_account")
    }
    assert selected_destinations == {str(finances.destination.id)}


def test_editing_transfer_preserves_and_updates_linked_income(client, app, db):
    from app.models import Bill

    finances = build_finances(db, "alice")
    linked_income_id = finances.linked_income.id
    bill_id = finances.bill.id
    destination_id = finances.destination.id
    source_name = finances.source.name
    log_in(client, "alice")

    response = client.post(
        f"/bill/{bill_id}/edit",
        data={
            "name": "Updated transfer",
            "amount": "40.25",
            "category": "Savings",
            "owner": "Alice Updated",
            "is_paid": "y",
            "transfer": "y",
            "destination_account": str(destination_id),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        bill = db.session.get(Bill, bill_id)
        assert bill.linked_income_id == linked_income_id
        assert bill.linked_income.account_id == destination_id
        assert bill.linked_income.amount == Decimal("40.25")
        assert bill.linked_income.contributor == "Alice Updated"
        assert bill.linked_income.name == f"Transfer from {source_name}"


def test_duplicate_month_recreates_transfer_links_inside_the_copy(client, app, db):
    from app.models import Account, Bill, Income, Month

    finances = build_finances(db, "alice")
    original_income_id = finances.linked_income.id
    log_in(client, "alice")

    response = client.post(
        f"/months/{finances.month.id}/duplicate",
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        copied_month = Month.query.filter_by(
            user_id=finances.user.id,
            name=f"{finances.month.name} (Copy)",
        ).one()
        copied_source = Account.query.filter_by(
            month_id=copied_month.id,
            name=finances.source.name,
        ).one()
        copied_destination = Account.query.filter_by(
            month_id=copied_month.id,
            name=finances.destination.name,
        ).one()
        copied_bill = Bill.query.filter_by(
            account_id=copied_source.id,
            name=finances.bill.name,
        ).one()
        copied_income = Income.query.filter_by(
            account_id=copied_destination.id,
            name=finances.linked_income.name,
        ).one()

        assert copied_bill.linked_income_id == copied_income.id
        assert copied_bill.linked_income_id != original_income_id
        assert copied_bill.linked_income.account.month_id == copied_month.id
        assert copied_bill.transfer_account_id == copied_destination.id


def test_duplicate_month_name_stays_within_database_limit(client, app, db):
    from app.models import Month

    user = add_user(db, "alice")
    month = Month(name="M" * 50, user_id=user.id)
    db.session.add(month)
    db.session.commit()
    log_in(client, "alice")

    response = client.post(f"/months/{month.id}/duplicate", follow_redirects=False)
    assert response.status_code == 302

    with app.app_context():
        copy = Month.query.filter(Month.id != month.id).one()
        assert len(copy.name) <= 50
        assert copy.name.endswith(" (Copy)")


def test_generated_transfer_income_name_stays_within_database_limit(client, app, db):
    from app.models import Income

    finances = build_finances(db, "alice")
    finances.source.name = "S" * 100
    db.session.commit()
    log_in(client, "alice")

    response = client.post(
        f"/months/{finances.month.id}",
        data={
            "account_id": finances.source.id,
            "bill-name": "Boundary transfer",
            "bill-amount": "11.00",
            "bill-owner": "Alice",
            "bill-is_paid": "y",
            "bill-transfer": "y",
            "bill-destination_account": str(finances.destination.id),
            "bill-submit": "Save Bill",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        income = Income.query.filter_by(amount=Decimal("11.00")).one()
        assert len(income.name) == 100
        assert income.name.startswith("Transfer from ")


def test_renaming_source_account_updates_generated_transfer_income(client, app, db):
    from app.models import Income

    finances = build_finances(db, "alice")
    income_id = finances.linked_income.id
    log_in(client, "alice")

    response = client.post(
        f"/account/{finances.source.id}/edit",
        data={"name": "Renamed Current"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        assert db.session.get(Income, income_id).name == "Transfer from Renamed Current"


@pytest.mark.parametrize(
    "payload",
    [
        {"x": -1, "y": 0, "width": 400, "height": 350},
        {"x": 0, "y": -1, "width": 400, "height": 350},
        {"x": 0, "y": 0, "width": 399, "height": 350},
        {"x": 0, "y": 0, "width": 400, "height": 349},
        {"x": 0, "y": 0, "width": 1201, "height": 350},
        {"x": 0, "y": 0, "width": 400, "height": 1201},
        {"x": 801, "y": 0, "width": 400, "height": 350},
    ],
)
def test_account_position_rejects_out_of_bounds_geometry(client, app, db, payload):
    from app.models import Account

    finances = build_finances(db, "alice")
    account_id = finances.source.id
    original_geometry = (
        finances.source.pos_x,
        finances.source.pos_y,
        finances.source.width,
        finances.source.height,
    )
    log_in(client, "alice")

    response = client.post(
        f"/account/{account_id}/update_position",
        json=payload,
    )
    assert response.status_code == 400
    assert response.is_json

    with app.app_context():
        account = db.session.get(Account, account_id)
        assert (
            account.pos_x,
            account.pos_y,
            account.width,
            account.height,
        ) == original_geometry


def test_account_position_accepts_boundary_geometry(client, app, db):
    from app.models import Account

    finances = build_finances(db, "alice")
    account_id = finances.source.id
    log_in(client, "alice")

    response = client.post(
        f"/account/{account_id}/update_position",
        json={"x": 800, "y": 0, "width": 400, "height": 1200},
    )
    assert response.status_code == 200
    assert response.get_json() == {"success": True}

    with app.app_context():
        account = db.session.get(Account, account_id)
        assert (account.pos_x, account.pos_y) == (800, 0)
        assert (account.width, account.height) == (400, 1200)


def test_new_accounts_are_placed_on_a_non_overlapping_grid(client, app, db):
    from app.models import Account, Month

    user = add_user(db, "alice")
    month = Month(name="Layout Month", user_id=user.id)
    db.session.add(month)
    db.session.commit()
    log_in(client, "alice")

    for number in range(4):
        response = client.post(
            f"/months/{month.id}",
            data={
                "account-name": f"Account {number}",
                "account-submit": "Save Account",
            },
            follow_redirects=False,
        )
        assert response.status_code == 302

    with app.app_context():
        accounts = Account.query.filter_by(month_id=month.id).order_by(Account.id).all()
        assert len(accounts) == 4
        assert len({(account.pos_x, account.pos_y) for account in accounts}) == 4
        assert all(account.pos_x >= 0 and account.pos_y >= 0 for account in accounts)
        assert all(400 <= account.width <= 1200 for account in accounts)
        assert all(350 <= account.height <= 1200 for account in accounts)
        assert all(account.pos_x + account.width <= 1200 for account in accounts)

        for index, left in enumerate(accounts):
            for right in accounts[index + 1 :]:
                separated = (
                    left.pos_x + left.width <= right.pos_x
                    or right.pos_x + right.width <= left.pos_x
                    or left.pos_y + left.height <= right.pos_y
                    or right.pos_y + right.height <= left.pos_y
                )
                assert separated, f"{left.name} overlaps {right.name}"


def test_health_failure_is_generic_and_uses_service_unavailable(client, monkeypatch):
    from app.extensions import db

    def fail_health_query(*_args, **_kwargs):
        raise RuntimeError("sensitive database connection details")

    monkeypatch.setattr(db.session, "execute", fail_health_query)
    response = client.get("/health")

    assert response.status_code == 503
    assert response.get_json() == {"status": "unhealthy"}
    assert b"sensitive database connection details" not in response.data
