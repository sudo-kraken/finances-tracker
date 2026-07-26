import re
from pathlib import Path


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


def test_account_geometry_uses_the_full_rendered_canvas():
    template_path = Path(__file__).resolve().parents[1] / "app" / "templates" / "month_details.html"
    template = template_path.read_text(encoding="utf-8")

    assert "const getWorkspaceWidth = () => canvas.clientWidth;" in template
    assert "maxWorkspaceWidth" not in template
