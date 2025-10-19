from decimal import Decimal


def test_amount_normalisation_success(app):
    from app.forms import BillForm, IncomeForm  # type: ignore

    # Bill amount cleaning with a plain decimal string
    with app.test_request_context(method="POST", data={"name": "X", "amount": "1234.56"}):
        f = BillForm(meta={"csrf": False})
        assert f.validate() is True
        assert isinstance(f.amount.data, Decimal)
        assert f.amount.data == Decimal("1234.56")

    # Income amount cleaning with a plain decimal string
    with app.test_request_context(method="POST", data={"name": "Y", "amount": "2503.50", "contributor": "A"}):
        f2 = IncomeForm(meta={"csrf": False})
        assert f2.validate() is True
        assert f2.amount.data == Decimal("2503.50")


def test_amount_validation_error_paths(app):
    from app.forms import BillForm, IncomeForm  # type: ignore

    # Bad amount should fail validation and hit the ValidationError path
    with app.test_request_context(method="POST", data={"name": "B", "amount": "not-a-number"}):
        f = BillForm(meta={"csrf": False})
        assert f.validate() is False
        assert "Amount" in f.errors or "amount" in f.errors

    with app.test_request_context(method="POST", data={"name": "C", "amount": "xx", "contributor": "A"}):
        f2 = IncomeForm(meta={"csrf": False})
        assert f2.validate() is False
        assert "Amount" in f2.errors or "amount" in f2.errors


def test_destination_coerce_and_choices(app):
    from app.forms import BillForm, destination_coerce  # type: ignore

    # destination_coerce helper
    assert destination_coerce("") == 0
    assert destination_coerce(None) == 0
    assert destination_coerce("7") == 7

    # When validating a SelectField we must provide choices
    with app.test_request_context(
        method="POST",
        data={"name": "Rent", "amount": "10.00", "transfer": "y", "destination_account": "7"},
    ):
        f = BillForm(meta={"csrf": False})
        f.destination_account.choices = [(0, "--"), (7, "Acc")]
        assert f.validate() is True
        assert f.destination_account.data == 7
