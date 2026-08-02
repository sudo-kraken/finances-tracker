from __future__ import annotations

from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from flask import redirect

ISSUER = "https://id.example.com"
REDIRECT_URI = "https://finances.example.com/auth/oidc/callback"
PASSWORD = "correct-horse-123"
EXTENSION_KEY = "finances_tracker_oidc"


def oidc_config(**overrides):
    config = {
        "TESTING": True,
        "SECRET_KEY": "oidc-test-secret",
        "SQLALCHEMY_DATABASE_URI": "sqlite://",
        "WTF_CSRF_ENABLED": False,
        "OIDC_ISSUER_URL": ISSUER,
        "OIDC_CLIENT_ID": "finances-client",
        "OIDC_CLIENT_SECRET": "client-secret",
        "OIDC_REDIRECT_URI": REDIRECT_URI,
        "OIDC_DISPLAY_NAME": "Test ID",
        "OIDC_AUTO_PROVISION": False,
        "OIDC_ONLY": False,
    }
    config.update(overrides)
    return config


def local_config(**overrides):
    config = oidc_config(
        OIDC_ISSUER_URL="",
        OIDC_CLIENT_ID="",
        OIDC_CLIENT_SECRET="",
        OIDC_REDIRECT_URI="",
    )
    config.update(overrides)
    return config


def close_app(application):
    from app.extensions import db

    with application.app_context():
        db.session.remove()
        db.drop_all()
        db.engine.dispose()


@pytest.fixture
def oidc_app(app_module):
    application = app_module.create_app(oidc_config())
    yield application
    close_app(application)


@pytest.fixture
def auto_provision_app(app_module):
    application = app_module.create_app(oidc_config(OIDC_AUTO_PROVISION=True))
    yield application
    close_app(application)


@pytest.fixture
def oidc_only_app(app_module):
    application = app_module.create_app(oidc_config(OIDC_ONLY=True))
    yield application
    close_app(application)


@pytest.fixture
def oidc_only_auto_provision_app(app_module):
    application = app_module.create_app(oidc_config(OIDC_ONLY=True, OIDC_AUTO_PROVISION=True))
    yield application
    close_app(application)


@pytest.fixture
def local_app(app_module):
    application = app_module.create_app(local_config())
    yield application
    close_app(application)


class FakeOidcClient:
    def __init__(self):
        self.authorize_error = None
        self.callback_error = None
        self.redirect_calls = []
        self.callback_calls = 0
        self.userinfo = self.claims(subject="subject-1")

    @staticmethod
    def claims(subject, **overrides):
        claims = {
            "iss": ISSUER,
            "sub": subject,
            "preferred_username": "alice",
            "name": "Alice Example",
            "email": "alice@example.com",
        }
        claims.update(overrides)
        return claims

    def authorize_redirect(self, redirect_uri, **kwargs):
        if self.authorize_error is not None:
            raise self.authorize_error
        call = {"redirect_uri": redirect_uri, **kwargs}
        self.redirect_calls.append(call)
        location = f"{ISSUER}/authorize?{urlencode(call)}"
        return redirect(location)

    def authorize_access_token(self):
        self.callback_calls += 1
        if self.callback_error is not None:
            raise self.callback_error
        return {"userinfo": self.userinfo}


class FakeOAuthRegistry:
    def __init__(self, client):
        self.client = client
        self.requested_clients = []

    def create_client(self, name):
        self.requested_clients.append(name)
        assert name == "oidc"
        return self.client


def install_fake_provider(application):
    provider = FakeOidcClient()
    application.extensions[EXTENSION_KEY] = FakeOAuthRegistry(provider)
    return provider


def create_user(application, username, *, month_name=None):
    from app.extensions import db
    from app.models import Month, User

    with application.app_context():
        user = User(username=username)
        user.set_password(PASSWORD)
        db.session.add(user)
        db.session.flush()
        month = None
        if month_name is not None:
            month = Month(name=month_name, user_id=user.id)
            db.session.add(month)
        db.session.commit()
        return {
            "user_id": user.id,
            "password_hash": user.password_hash,
            "month_id": month.id if month is not None else None,
        }


def password_login(client, username):
    response = client.post(
        "/login",
        data={"username": username, "password": PASSWORD},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/months")
    return response


def start_oidc_login(client):
    response = client.post("/auth/oidc/login", follow_redirects=False)
    assert response.status_code == 302
    return response


def complete_callback(client, *, follow_redirects=False):
    return client.get(
        "/auth/oidc/callback?code=test-code&state=test-state",
        follow_redirects=follow_redirects,
    )


def test_oidc_is_disabled_when_all_core_settings_are_empty(local_app):
    assert local_app.config["OIDC_ENABLED"] is False
    assert EXTENSION_KEY not in local_app.extensions

    response = local_app.test_client().get("/login")
    assert response.status_code == 200
    assert b"Sign in with Test ID" not in response.data


def test_partial_oidc_configuration_fails_fast(app_module):
    config = local_config(OIDC_ISSUER_URL=ISSUER)

    with pytest.raises(RuntimeError, match=r"OIDC configuration is incomplete.*OIDC_CLIENT_ID"):
        app_module.create_app(config)


def test_oidc_only_requires_a_complete_provider_configuration(app_module):
    with pytest.raises(RuntimeError, match="OIDC_ONLY requires a complete OIDC configuration"):
        app_module.create_app(local_config(OIDC_ONLY=True))


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"OIDC_ISSUER_URL": "not-a-url"}, "absolute HTTP"),
        ({"OIDC_ISSUER_URL": "http://id.example.com"}, "must use HTTPS"),
        ({"OIDC_ISSUER_URL": f"{ISSUER}?tenant=one"}, "without a query or fragment"),
        (
            {"OIDC_REDIRECT_URI": "http://finances.example.com/auth/oidc/callback"},
            "must use HTTPS",
        ),
        ({"OIDC_REDIRECT_URI": "https://finances.example.com/callback"}, "must end with"),
        ({"OIDC_REDIRECT_URI": f"{REDIRECT_URI}?return=months"}, "without a query or fragment"),
    ],
)
def test_oidc_rejects_unsafe_or_incorrect_urls(app_module, overrides, message):
    with pytest.raises(RuntimeError, match=message):
        app_module.create_app(oidc_config(**overrides))


def test_oidc_allows_http_only_for_local_development(app_module):
    application = app_module.create_app(
        oidc_config(
            OIDC_ISSUER_URL="http://localhost:8000",
            OIDC_REDIRECT_URI="http://127.0.0.1:7070/auth/oidc/callback",
        )
    )
    try:
        assert application.config["OIDC_ENABLED"] is True
        assert application.config["OIDC_ISSUER_URL"] == "http://localhost:8000"
    finally:
        close_app(application)


def test_login_page_and_start_use_the_configured_callback_and_fresh_nonce(oidc_app):
    real_client = oidc_app.extensions[EXTENSION_KEY].create_client("oidc")
    assert real_client.client_kwargs["scope"] == "openid profile email"
    assert real_client.client_kwargs["code_challenge_method"] == "S256"

    provider = install_fake_provider(oidc_app)
    client = oidc_app.test_client()

    login_page = client.get("/login")
    assert b"Sign in with Test ID" in login_page.data
    assert b'action="/auth/oidc/login"' in login_page.data

    first = client.post(
        "/auth/oidc/login",
        headers={"Host": "untrusted.invalid"},
        follow_redirects=False,
    )
    second = start_oidc_login(client)

    assert first.status_code == 302
    assert len(provider.redirect_calls) == 2
    assert all(call["redirect_uri"] == REDIRECT_URI for call in provider.redirect_calls)
    nonces = [call["nonce"] for call in provider.redirect_calls]
    assert all(isinstance(nonce, str) and len(nonce) >= 32 for nonce in nonces)
    assert nonces[0] != nonces[1]

    query = parse_qs(urlsplit(second.headers["Location"]).query)
    assert query["redirect_uri"] == [REDIRECT_URI]
    assert query["nonce"] == [nonces[1]]
    with client.session_transaction() as session:
        assert session["oidc_flow"] == {"action": "login", "user_id": None}


def test_oidc_only_hides_and_rejects_local_login_and_registration(oidc_only_app):
    alice = create_user(oidc_only_app, "alice", month_name="Private Month")
    oidc_only_app.config["ALLOW_REGISTRATION"] = True
    client = oidc_only_app.test_client()

    login_page = client.get("/login")
    assert login_page.status_code == 200
    assert b"Sign in with Test ID" in login_page.data
    assert b"login-username" not in login_page.data
    assert b"login-password" not in login_page.data
    assert b">Register<" not in login_page.data

    local_login = client.post(
        "/login",
        data={"username": "alice", "password": PASSWORD},
        follow_redirects=True,
    )
    assert local_login.status_code == 200
    assert b"Username and password sign-in is disabled" in local_login.data
    assert urlsplit(client.get("/months", follow_redirects=False).headers["Location"]).path == "/login"

    assert client.get("/register", follow_redirects=False).headers["Location"].endswith("/login")
    registration = client.post(
        "/register",
        data={
            "username": "bob",
            "password": "another-correct-horse-123",
            "confirm_password": "another-correct-horse-123",
        },
        follow_redirects=True,
    )
    assert registration.status_code == 200
    assert b"Username and password registration is disabled" in registration.data

    from app.extensions import db
    from app.models import User

    with oidc_only_app.app_context():
        users = db.session.scalars(db.select(User)).all()
        assert [(user.id, user.username, user.password_hash) for user in users] == [
            (alice["user_id"], "alice", alice["password_hash"])
        ]


def test_oidc_only_allows_linked_login_but_blocks_identity_changes(oidc_only_app):
    alice = create_user(oidc_only_app, "alice", month_name="OIDC Month")
    provider = install_fake_provider(oidc_only_app)
    provider.userinfo = provider.claims("linked-subject", email="alice@example.com")

    from app.extensions import db
    from app.models import OidcIdentity, User

    with oidc_only_app.app_context():
        db.session.add(
            OidcIdentity(
                user_id=alice["user_id"],
                issuer=ISSUER,
                subject="linked-subject",
                email="alice@example.com",
            )
        )
        db.session.commit()

    client = oidc_only_app.test_client()
    start_oidc_login(client)
    login = complete_callback(client)
    assert login.status_code == 302
    assert login.headers["Location"].endswith("/months")
    assert b"OIDC Month" in client.get("/months").data

    with client.session_transaction() as session:
        assert session["_user_id"] == str(alice["user_id"])
        assert session["auth_method"] == "oidc"

    settings = client.get("/auth/oidc/settings")
    assert b"Username and password sign-in is disabled" in settings.data
    assert b"Disconnect Test ID" not in settings.data
    assert b"Connect Test ID" not in settings.data

    disconnect = client.post("/auth/oidc/disconnect", follow_redirects=True)
    assert b"cannot be disconnected while OIDC-only login is enabled" in disconnect.data
    link = client.post("/auth/oidc/link", follow_redirects=True)
    assert b"Account linking is disabled while OIDC-only login is enabled" in link.data

    with oidc_only_app.app_context():
        user = db.session.get(User, alice["user_id"])
        identity = db.session.scalar(db.select(OidcIdentity).where(OidcIdentity.subject == "linked-subject"))
        assert user.password_hash == alice["password_hash"]
        assert identity is not None
        assert identity.user_id == alice["user_id"]


def test_enabling_oidc_only_ends_an_existing_password_session(oidc_app):
    alice = create_user(oidc_app, "alice", month_name="Local Month")
    password_client = oidc_app.test_client()
    legacy_client = oidc_app.test_client()
    password_login(password_client, "alice")
    password_login(legacy_client, "alice")
    with legacy_client.session_transaction() as session:
        session.pop("auth_method")

    oidc_app.config["OIDC_ONLY"] = True
    for client in (password_client, legacy_client):
        response = client.get("/months", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["Location"].endswith("/login")
        with client.session_transaction() as session:
            assert "_user_id" not in session
            assert "auth_method" not in session
    with oidc_app.app_context():
        from app.extensions import db
        from app.models import User

        assert db.session.get(User, alice["user_id"]).password_hash == alice["password_hash"]


def test_enabling_oidc_only_keeps_an_existing_oidc_session(oidc_app):
    alice = create_user(oidc_app, "alice", month_name="OIDC Month")
    client = oidc_app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(alice["user_id"])
        session["_fresh"] = True
        session["auth_method"] = "oidc"

    oidc_app.config["OIDC_ONLY"] = True
    response = client.get("/months")

    assert response.status_code == 200
    assert b"OIDC Month" in response.data
    with client.session_transaction() as session:
        assert session["_user_id"] == str(alice["user_id"])
        assert session["auth_method"] == "oidc"


def test_oidc_only_blocks_a_link_callback_started_before_the_mode_changed(oidc_app):
    provider = install_fake_provider(oidc_app)
    client = oidc_app.test_client()
    with client.session_transaction() as session:
        session["oidc_flow"] = {"action": "link", "user_id": 1}
    oidc_app.config["OIDC_ONLY"] = True

    response = complete_callback(client, follow_redirects=True)
    assert response.status_code == 200
    assert b"Account linking is disabled while OIDC-only login is enabled" in response.data
    assert provider.callback_calls == 0


def test_oidc_only_provider_failures_do_not_offer_password_fallback(oidc_only_app):
    provider = install_fake_provider(oidc_only_app)
    provider.authorize_error = RuntimeError("provider unavailable")
    client = oidc_only_app.test_client()

    response = client.post("/auth/oidc/login", follow_redirects=True)
    assert response.status_code == 200
    assert b"Could not contact the identity provider. Please try again later." in response.data
    assert b"Local password sign-in is still available" not in response.data


def test_provider_outage_does_not_break_local_password_login(oidc_app):
    user = create_user(oidc_app, "alice", month_name="August 2026")
    provider = install_fake_provider(oidc_app)
    provider.authorize_error = RuntimeError("provider unavailable")
    client = oidc_app.test_client()

    failed = client.post("/auth/oidc/login", follow_redirects=True)
    assert failed.status_code == 200
    assert b"Local password sign-in is still available" in failed.data
    with client.session_transaction() as session:
        assert "oidc_flow" not in session

    password_login(client, "alice")
    months = client.get("/months")
    assert months.status_code == 200
    assert b"August 2026" in months.data

    from app.extensions import db
    from app.models import User

    with oidc_app.app_context():
        assert db.session.get(User, user["user_id"]).password_hash == user["password_hash"]


def test_local_user_can_link_oidc_without_changing_password_or_ownership(oidc_app):
    original = create_user(oidc_app, "alice", month_name="Preserved Month")
    provider = install_fake_provider(oidc_app)
    provider.userinfo = provider.claims("alice-subject", preferred_username="renamed-at-provider")
    client = oidc_app.test_client()

    password_login(client, "alice")
    started = client.post("/auth/oidc/link", follow_redirects=False)
    assert started.status_code == 302
    assert provider.redirect_calls[-1]["redirect_uri"] == REDIRECT_URI
    assert provider.redirect_calls[-1]["prompt"] == "login"
    with client.session_transaction() as session:
        assert session["oidc_flow"] == {"action": "link", "user_id": original["user_id"]}

    completed = complete_callback(client)
    assert completed.status_code == 302
    assert completed.headers["Location"].endswith("/auth/oidc/settings")

    from app.extensions import db
    from app.models import Month, OidcIdentity, User

    with oidc_app.app_context():
        user = db.session.get(User, original["user_id"])
        month = db.session.get(Month, original["month_id"])
        identity = db.session.scalar(
            db.select(OidcIdentity).where(
                OidcIdentity.issuer == ISSUER,
                OidcIdentity.subject == "alice-subject",
            )
        )
        assert user.username == "alice"
        assert user.password_hash == original["password_hash"]
        assert user.check_password(PASSWORD)
        assert month.user_id == original["user_id"]
        assert identity.user_id == original["user_id"]

    assert client.get("/months").status_code == 200
    client.post("/logout")
    password_login(client, "alice")


def test_local_user_can_disconnect_and_replace_an_oidc_identity(oidc_app):
    alice = create_user(oidc_app, "alice", month_name="Preserved Month")
    provider = install_fake_provider(oidc_app)

    from app.extensions import db
    from app.models import OidcIdentity

    with oidc_app.app_context():
        db.session.add(
            OidcIdentity(
                user_id=alice["user_id"],
                issuer=ISSUER,
                subject="wrong-subject",
            )
        )
        db.session.commit()

    client = oidc_app.test_client()
    password_login(client, "alice")
    settings = client.get("/auth/oidc/settings")
    assert b"Disconnect Test ID" in settings.data

    disconnected = client.post("/auth/oidc/disconnect", follow_redirects=True)
    assert b"Test ID disconnected" in disconnected.data
    with oidc_app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(OidcIdentity)) == 0

    provider.userinfo = provider.claims("correct-subject")
    assert client.post("/auth/oidc/link").status_code == 302
    assert provider.redirect_calls[-1]["prompt"] == "login"
    assert complete_callback(client).status_code == 302
    with oidc_app.app_context():
        replacement = db.session.scalar(db.select(OidcIdentity))
        assert replacement.subject == "correct-subject"
        assert replacement.user_id == alice["user_id"]


def test_link_requires_recent_password_authentication_at_start_and_callback(oidc_app):
    create_user(oidc_app, "alice")
    provider = install_fake_provider(oidc_app)
    provider.userinfo = provider.claims("alice-subject")
    client = oidc_app.test_client()

    password_login(client, "alice")
    with client.session_transaction() as session:
        session["local_authenticated_at"] = 1
    expired_start = client.post("/auth/oidc/link", follow_redirects=True)
    assert b"Sign out and sign in with your password again" in expired_start.data
    assert provider.redirect_calls == []

    client.post("/logout")
    password_login(client, "alice")
    assert client.post("/auth/oidc/link").status_code == 302
    with client.session_transaction() as session:
        session["local_authenticated_at"] = 1
    expired_callback = complete_callback(client, follow_redirects=True)
    assert b"account-linking request expired" in expired_callback.data

    from app.extensions import db
    from app.models import OidcIdentity

    with oidc_app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(OidcIdentity)) == 0


def test_identity_linked_to_another_user_cannot_be_reassigned(oidc_app):
    alice = create_user(oidc_app, "alice", month_name="Alice Month")
    bob = create_user(oidc_app, "bob", month_name="Bob Month")
    provider = install_fake_provider(oidc_app)
    provider.userinfo = provider.claims("bob-subject", preferred_username="bob")

    from app.extensions import db
    from app.models import OidcIdentity

    with oidc_app.app_context():
        db.session.add(OidcIdentity(user_id=bob["user_id"], issuer=ISSUER, subject="bob-subject"))
        db.session.commit()

    client = oidc_app.test_client()
    password_login(client, "alice")
    assert client.post("/auth/oidc/link").status_code == 302
    response = complete_callback(client, follow_redirects=True)

    assert response.status_code == 200
    assert b"cannot be connected to this account" in response.data
    assert b"Alice Month" in client.get("/months").data
    assert b"Bob Month" not in client.get("/months").data

    with oidc_app.app_context():
        identities = db.session.scalars(db.select(OidcIdentity)).all()
        assert len(identities) == 1
        assert identities[0].user_id == bob["user_id"]
        assert identities[0].user_id != alice["user_id"]


def test_unlinked_identity_is_refused_and_never_matched_by_username(oidc_app):
    alice = create_user(oidc_app, "alice", month_name="Private Month")
    provider = install_fake_provider(oidc_app)
    provider.userinfo = provider.claims(
        "unlinked-subject",
        preferred_username="ALICE",
        email="alice@example.com",
    )
    client = oidc_app.test_client()

    start_oidc_login(client)
    response = complete_callback(client, follow_redirects=True)

    assert response.status_code == 200
    assert b"No linked account was found" in response.data
    assert client.get("/months").status_code == 302

    from app.extensions import db
    from app.models import OidcIdentity, User

    with oidc_app.app_context():
        users = db.session.scalars(db.select(User)).all()
        assert len(users) == 1
        assert users[0].id == alice["user_id"]
        assert users[0].password_hash == alice["password_hash"]
        assert db.session.scalar(db.select(db.func.count()).select_from(OidcIdentity)) == 0


def test_linked_oidc_login_clears_the_old_session(oidc_app):
    alice = create_user(oidc_app, "alice", month_name="Linked Month")
    provider = install_fake_provider(oidc_app)
    provider.userinfo = provider.claims("linked-subject", email="updated@example.com")

    from app.extensions import db
    from app.models import OidcIdentity

    with oidc_app.app_context():
        db.session.add(
            OidcIdentity(
                user_id=alice["user_id"],
                issuer=ISSUER,
                subject="linked-subject",
                email="old@example.com",
            )
        )
        db.session.commit()

    client = oidc_app.test_client()
    with client.session_transaction() as session:
        session["stale"] = "must disappear"
        session["auth_method"] = "password"
        session["local_authenticated_at"] = 1

    start_oidc_login(client)
    response = complete_callback(client)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/months")

    with client.session_transaction() as session:
        assert session["_user_id"] == str(alice["user_id"])
        assert session["auth_method"] == "oidc"
        assert "stale" not in session
        assert "local_authenticated_at" not in session
        assert "oidc_flow" not in session

    assert b"Linked Month" in client.get("/months").data
    settings = client.get("/auth/oidc/settings")
    assert b"Disconnect Test ID" not in settings.data
    refused_disconnect = client.post("/auth/oidc/disconnect", follow_redirects=True)
    assert b"Sign in with your local password again" in refused_disconnect.data
    with oidc_app.app_context():
        identity = db.session.scalar(db.select(OidcIdentity).where(OidcIdentity.subject == "linked-subject"))
        assert identity.email == "updated@example.com"
        assert identity.last_login_at is not None


def test_auto_provision_creates_a_distinct_user_and_identity(auto_provision_app):
    provider = install_fake_provider(auto_provision_app)
    provider.userinfo = provider.claims(
        "new-subject",
        preferred_username="new.user",
        email="new@example.com",
    )
    client = auto_provision_app.test_client()

    start_oidc_login(client)
    response = complete_callback(client)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/months")

    from app.extensions import db
    from app.models import OidcIdentity, RegistrationGate, User

    with auto_provision_app.app_context():
        user = db.session.scalar(db.select(User))
        identity = db.session.scalar(db.select(OidcIdentity))
        assert user.username.startswith("new.user-")
        assert user.username != "new.user"
        assert len(user.username) <= 64
        assert not user.check_password(PASSWORD)
        assert identity.user_id == user.id
        assert (identity.issuer, identity.subject, identity.email) == (
            ISSUER,
            "new-subject",
            "new@example.com",
        )
        assert db.session.get(RegistrationGate, 1) is not None

    with client.session_transaction() as session:
        assert session["auth_method"] == "oidc"


def test_first_oidc_user_claims_preserved_legacy_data(auto_provision_app):
    from app.extensions import db
    from app.models import Month, User
    from app.schema_migrations import LEGACY_OWNER_PASSWORD_HASH, LEGACY_OWNER_USERNAME

    with auto_provision_app.app_context():
        legacy_owner = User(username=LEGACY_OWNER_USERNAME, password_hash=LEGACY_OWNER_PASSWORD_HASH)
        db.session.add(legacy_owner)
        db.session.flush()
        month = Month(name="Preserved legacy month", user_id=legacy_owner.id)
        db.session.add(month)
        db.session.commit()
        month_id = month.id

    provider = install_fake_provider(auto_provision_app)
    provider.userinfo = provider.claims("first-oidc-subject", preferred_username="new-owner")
    client = auto_provision_app.test_client()
    start_oidc_login(client)
    assert complete_callback(client).status_code == 302

    with auto_provision_app.app_context():
        new_owner = db.session.scalar(db.select(User).where(User.username.like("new-owner-%")))
        assert new_owner is not None
        assert db.session.get(Month, month_id).user_id == new_owner.id
        assert db.session.scalar(db.select(User).where(User.username == LEGACY_OWNER_USERNAME)) is None


def test_auto_provision_refuses_a_case_insensitive_local_username_collision(auto_provision_app):
    alice = create_user(auto_provision_app, "Alice", month_name="Existing Data")
    provider = install_fake_provider(auto_provision_app)
    provider.userinfo = provider.claims("attacker-subject", preferred_username="alice")
    client = auto_provision_app.test_client()

    start_oidc_login(client)
    response = complete_callback(client, follow_redirects=True)

    assert response.status_code == 200
    assert b"local account with that username already exists" in response.data
    assert client.get("/months").status_code == 302

    from app.extensions import db
    from app.models import OidcIdentity, User

    with auto_provision_app.app_context():
        users = db.session.scalars(db.select(User)).all()
        assert [(user.id, user.username, user.password_hash) for user in users] == [
            (alice["user_id"], "Alice", alice["password_hash"])
        ]
        assert db.session.scalar(db.select(db.func.count()).select_from(OidcIdentity)) == 0


def test_oidc_only_unlinked_identity_guidance_does_not_offer_password_login(oidc_only_app):
    provider = install_fake_provider(oidc_only_app)
    provider.userinfo = provider.claims("unlinked-subject")
    client = oidc_only_app.test_client()

    start_oidc_login(client)
    response = complete_callback(client, follow_redirects=True)

    assert response.status_code == 200
    assert (
        b"Ask the administrator to temporarily disable OIDC-only mode to link the existing account, "
        b"or enable OIDC auto-provisioning" in response.data
    )
    assert b"Sign in with your password" not in response.data


def test_oidc_only_auto_provisioning_remains_available(oidc_only_auto_provision_app):
    provider = install_fake_provider(oidc_only_auto_provision_app)
    provider.userinfo = provider.claims("new-oidc-subject", preferred_username="new.user")
    client = oidc_only_auto_provision_app.test_client()

    start_oidc_login(client)
    response = complete_callback(client)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/months")
    with client.session_transaction() as session:
        assert session["auth_method"] == "oidc"


def test_oidc_only_username_collision_guidance_does_not_offer_password_login(oidc_only_auto_provision_app):
    alice = create_user(oidc_only_auto_provision_app, "Alice")
    provider = install_fake_provider(oidc_only_auto_provision_app)
    provider.userinfo = provider.claims("attacker-subject", preferred_username="alice")
    client = oidc_only_auto_provision_app.test_client()

    start_oidc_login(client)
    response = complete_callback(client, follow_redirects=True)

    assert response.status_code == 200
    assert b"Ask the administrator to resolve the account link" in response.data
    assert b"Sign in with its password" not in response.data

    from app.extensions import db
    from app.models import User

    with oidc_only_auto_provision_app.app_context():
        users = db.session.scalars(db.select(User)).all()
        assert [(user.id, user.username, user.password_hash) for user in users] == [
            (alice["user_id"], "Alice", alice["password_hash"])
        ]


@pytest.mark.parametrize(
    "userinfo",
    [
        None,
        {},
        {"iss": ISSUER},
        {"iss": ISSUER, "sub": ""},
        {"iss": ISSUER, "sub": 123},
        {"iss": "https://attacker.example.com", "sub": "subject"},
        {"iss": ISSUER, "sub": "s" * 256},
    ],
)
def test_invalid_oidc_claims_are_rejected(oidc_app, userinfo):
    provider = install_fake_provider(oidc_app)
    provider.userinfo = userinfo
    client = oidc_app.test_client()

    start_oidc_login(client)
    response = complete_callback(client, follow_redirects=True)

    assert response.status_code == 200
    assert b"Identity provider sign-in failed" in response.data
    assert client.get("/months").status_code == 302

    from app.extensions import db
    from app.models import OidcIdentity, User

    with oidc_app.app_context():
        assert db.session.scalar(db.select(db.func.count()).select_from(User)) == 0
        assert db.session.scalar(db.select(db.func.count()).select_from(OidcIdentity)) == 0


def test_callback_provider_error_is_generic_and_consumes_the_flow(oidc_app, caplog):
    provider = install_fake_provider(oidc_app)
    provider.callback_error = RuntimeError("token=provider-secret")
    client = oidc_app.test_client()

    start_oidc_login(client)
    response = complete_callback(client, follow_redirects=True)

    assert response.status_code == 200
    assert b"Identity provider sign-in failed" in response.data
    assert b"provider-secret" not in response.data
    assert "provider-secret" not in caplog.text
    with client.session_transaction() as session:
        assert "oidc_flow" not in session

    replay = complete_callback(client, follow_redirects=True)
    assert b"sign-in request expired" in replay.data
    assert provider.callback_calls == 1


def test_link_provider_error_preserves_the_local_login(oidc_app):
    alice = create_user(oidc_app, "alice", month_name="Still Available")
    provider = install_fake_provider(oidc_app)
    client = oidc_app.test_client()

    password_login(client, "alice")
    assert client.post("/auth/oidc/link").status_code == 302
    provider.callback_error = RuntimeError("provider rejected request")
    response = complete_callback(client, follow_redirects=True)

    assert response.status_code == 200
    assert b"Identity provider sign-in failed" in response.data
    assert b"Still Available" in client.get("/months").data
    with client.session_transaction() as session:
        assert session["_user_id"] == str(alice["user_id"])
        assert session["auth_method"] == "password"


def test_disabled_oidc_routes_return_not_found_and_logout_clears_session(local_app):
    create_user(local_app, "alice", month_name="Local Month")
    client = local_app.test_client()

    assert client.post("/auth/oidc/login").status_code == 404
    assert client.get("/auth/oidc/callback").status_code == 404

    password_login(client, "alice")
    assert client.get("/auth/oidc/settings").status_code == 404
    assert client.post("/auth/oidc/link").status_code == 404

    with client.session_transaction() as session:
        session["stale"] = "remove-me"
    logout = client.post("/logout", follow_redirects=False)
    assert logout.status_code == 302
    assert logout.headers["Location"].endswith("/login")
    with client.session_transaction() as session:
        assert dict(session) == {}
    assert client.get("/months").status_code == 302
