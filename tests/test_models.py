from decimal import Decimal


def test_models_crud_and_relationships(db):
    from app.extensions import db as _db  # type: ignore
    from app.models import User, Month, Account, Income, Bill  # type: ignore

    u = User(username="alice")
    u.set_password("secret123")
    _db.session.add(u)

    m = Month(name="October")
    _db.session.add(m)
    _db.session.commit()

    a = Account(month_id=m.id, name="Primary")
    _db.session.add(a)
    _db.session.commit()

    inc = Income(account_id=a.id, name="Salary", amount=Decimal("1000.00"), contributor="Alice")
    bill = Bill(account_id=a.id, name="Rent", amount=Decimal("600.00"))
    bill.linked_income = inc

    _db.session.add_all([inc, bill])
    _db.session.commit()

    assert u.check_password("secret123") is True
    assert u.check_password("nope") is False
    assert a.bills[0].name == "Rent"
    assert a.incomes[0].name == "Salary"
    assert bill.linked_income_id == inc.id
