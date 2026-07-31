from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError


def test_models_crud_and_relationships(db):
    from app.extensions import db as _db  # type: ignore
    from app.models import Account, Bill, Income, Month, User  # type: ignore

    u = User(username="alice")
    u.set_password("secret123")
    _db.session.add(u)

    m = Month(name="October", user=u)
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
    assert len(u.password_hash) > 128
    assert User.password_hash.type.length == 512


def test_oidc_identity_relationship_and_constraints(db):
    from app.models import OidcIdentity, User

    alice = User(username="alice")
    alice.set_password("secret123")
    bob = User(username="bob")
    bob.set_password("secret123")
    identity = OidcIdentity(
        user=alice,
        issuer="https://id.example.test",
        subject="alice-subject",
        email="alice@example.test",
    )
    db.session.add_all([alice, bob, identity])
    db.session.commit()

    assert alice.oidc_identities == [identity]
    assert identity.user is alice
    assert identity.created_at is not None
    assert identity.last_login_at is None

    db.session.add(
        OidcIdentity(
            user=bob,
            issuer=identity.issuer,
            subject=identity.subject,
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    db.session.add(
        OidcIdentity(
            user=alice,
            issuer=identity.issuer,
            subject="another-subject",
        )
    )
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_deleting_user_deletes_oidc_identity(db):
    from app.models import OidcIdentity, User

    user = User(username="alice")
    user.set_password("secret123")
    identity = OidcIdentity(
        user=user,
        issuer="https://id.example.test",
        subject="alice-subject",
    )
    db.session.add(user)
    db.session.commit()
    identity_id = identity.id

    db.session.delete(user)
    db.session.commit()

    assert db.session.get(OidcIdentity, identity_id) is None
