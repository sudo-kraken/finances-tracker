import pytest


@pytest.mark.parametrize(
    "path",
    [
        "/months/1/edit",
        "/account/1/edit",
        "/bill/1/edit",
        "/income/1/edit",
    ],
)
def test_edit_routes_do_not_expose_missing_get_templates(client, path):
    response = client.get(path)

    assert response.status_code == 405
