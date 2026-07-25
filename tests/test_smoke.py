def test_index_redirects_for_anon(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (301, 302, 303)
    assert "/login" in r.headers.get("Location", "")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "same-origin"
