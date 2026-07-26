import re


def test_index_redirects_for_anon(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (301, 302, 303)
    assert "/login" in r.headers.get("Location", "")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "same-origin"


def test_workspace_overrides_bootstrap_container_width(client):
    response = client.get("/static/css/style.css")

    assert response.status_code == 200
    app_main_rule = re.search(r"\.app-main\s*\{(?P<body>[^}]+)\}", response.get_data(as_text=True))
    assert app_main_rule is not None
    assert "max-width: 1440px;" in app_main_rule.group("body")
