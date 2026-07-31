from __future__ import annotations

import hashlib
import re
import secrets
from collections.abc import Mapping
from time import time
from urllib.parse import urlsplit

from authlib.integrations.flask_client import OAuth
from flask import Blueprint, abort, current_app, flash, redirect, render_template, session, url_for
from flask_login import current_user, login_required, login_user
from sqlalchemy.exc import IntegrityError

from .extensions import db
from .models import Month, OidcIdentity, RegistrationGate, User, utc_now
from .schema_migrations import LEGACY_OWNER_PASSWORD_HASH, LEGACY_OWNER_USERNAME, is_legacy_owner

bp = Blueprint("oidc", __name__, url_prefix="/auth/oidc")

_EXTENSION_KEY = "finances_tracker_oidc"
_FLOW_KEY = "oidc_flow"
_CORE_SETTINGS = (
    "OIDC_ISSUER_URL",
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET",
    "OIDC_REDIRECT_URI",
)
_LINK_WINDOW_SECONDS = 15 * 60
_USERNAME_MAX_LENGTH = 64


def init_oidc(app) -> None:
    """Validate and register the optional OpenID Connect client."""

    values = {name: app.config.get(name) or "" for name in _CORE_SETTINGS}
    configured = {name for name, value in values.items() if str(value).strip()}
    if not configured:
        app.config["OIDC_ENABLED"] = False
        app.config["OIDC_DISPLAY_NAME"] = _display_name(app)
        return

    missing = [name for name in _CORE_SETTINGS if name not in configured]
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(f"OIDC configuration is incomplete; also set: {names}")

    issuer = str(values["OIDC_ISSUER_URL"]).strip()
    redirect_uri = str(values["OIDC_REDIRECT_URI"]).strip()
    _validate_url("OIDC_ISSUER_URL", issuer)
    _validate_url("OIDC_REDIRECT_URI", redirect_uri, callback=True)
    if len(issuer) > 255:
        raise RuntimeError("OIDC_ISSUER_URL must be no longer than 255 characters")

    auto_provision = app.config.get("OIDC_AUTO_PROVISION", False)
    if isinstance(auto_provision, str):
        auto_provision = auto_provision.lower() in {"1", "true", "yes", "on"}

    app.config.update(
        OIDC_ENABLED=True,
        OIDC_ISSUER_URL=issuer,
        OIDC_CLIENT_ID=str(values["OIDC_CLIENT_ID"]).strip(),
        OIDC_CLIENT_SECRET=str(values["OIDC_CLIENT_SECRET"]),
        OIDC_REDIRECT_URI=redirect_uri,
        OIDC_DISPLAY_NAME=_display_name(app),
        OIDC_AUTO_PROVISION=bool(auto_provision),
    )

    oauth = OAuth(app)
    oauth.register(
        name="oidc",
        client_id=app.config["OIDC_CLIENT_ID"],
        client_secret=app.config["OIDC_CLIENT_SECRET"],
        server_metadata_url=f"{issuer.rstrip('/')}/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid profile email",
            "code_challenge_method": "S256",
        },
    )
    app.extensions[_EXTENSION_KEY] = oauth


def _display_name(app) -> str:
    display_name = str(app.config.get("OIDC_DISPLAY_NAME") or "Pocket ID").strip()
    return (display_name or "Pocket ID")[:64]


def _validate_url(name: str, value: str, *, callback: bool = False) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.query or parsed.fragment:
        raise RuntimeError(f"{name} must be an absolute HTTP(S) URL without a query or fragment")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(f"{name} must use HTTPS except on localhost")
    if callback and parsed.path != "/auth/oidc/callback":
        raise RuntimeError("OIDC_REDIRECT_URI must end with /auth/oidc/callback")


def _require_enabled() -> None:
    if not current_app.config["OIDC_ENABLED"]:
        abort(404)


def _client():
    return current_app.extensions[_EXTENSION_KEY].create_client("oidc")


def _authorization_redirect(action: str, user_id: int | None = None):
    session[_FLOW_KEY] = {"action": action, "user_id": user_id}
    authorization_parameters = {"nonce": secrets.token_urlsafe(32)}
    if action == "link":
        authorization_parameters["prompt"] = "login"
    try:
        return _client().authorize_redirect(
            current_app.config["OIDC_REDIRECT_URI"],
            **authorization_parameters,
        )
    except Exception as error:  # Provider and discovery failures vary by HTTP client.
        session.pop(_FLOW_KEY, None)
        current_app.logger.warning("OIDC authorization could not start (%s)", type(error).__name__)
        flash("Could not contact the identity provider. Local password sign-in is still available.", "error")
        destination = "oidc.settings" if current_user.is_authenticated else "main.login"
        return redirect(url_for(destination))


@bp.post("/login")
def login():
    _require_enabled()
    if current_user.is_authenticated:
        return redirect(url_for("main.months"))
    return _authorization_redirect("login")


@bp.get("/settings")
@login_required
def settings():
    _require_enabled()
    identity = db.session.scalar(
        db.select(OidcIdentity).where(
            OidcIdentity.user_id == current_user.id,
            OidcIdentity.issuer == current_app.config["OIDC_ISSUER_URL"],
        )
    )
    return render_template(
        "auth_settings.html",
        identity=identity,
        can_disconnect=_recent_local_authentication(),
        oidc_display_name=current_app.config["OIDC_DISPLAY_NAME"],
    )


@bp.post("/link")
@login_required
def link():
    _require_enabled()
    if not _recent_local_authentication():
        flash("Sign out and sign in with your password again before connecting an identity provider.", "warning")
        return redirect(url_for("oidc.settings"))

    existing = db.session.scalar(
        db.select(OidcIdentity.id).where(
            OidcIdentity.user_id == current_user.id,
            OidcIdentity.issuer == current_app.config["OIDC_ISSUER_URL"],
        )
    )
    if existing is not None:
        flash(f"{current_app.config['OIDC_DISPLAY_NAME']} is already connected.")
        return redirect(url_for("oidc.settings"))
    return _authorization_redirect("link", current_user.id)


@bp.post("/disconnect")
@login_required
def disconnect():
    _require_enabled()
    if not _recent_local_authentication():
        flash(
            f"Sign in with your local password again before disconnecting {current_app.config['OIDC_DISPLAY_NAME']}.",
            "warning",
        )
        return redirect(url_for("oidc.settings"))

    identity = db.session.scalar(
        db.select(OidcIdentity).where(
            OidcIdentity.user_id == current_user.id,
            OidcIdentity.issuer == current_app.config["OIDC_ISSUER_URL"],
        )
    )
    if identity is None:
        flash("No identity provider is connected to this account.")
        return redirect(url_for("oidc.settings"))

    db.session.delete(identity)
    db.session.commit()
    flash(f"{current_app.config['OIDC_DISPLAY_NAME']} disconnected.", "success")
    return redirect(url_for("oidc.settings"))


@bp.get("/callback")
def callback():
    _require_enabled()
    flow = session.pop(_FLOW_KEY, None)
    if not isinstance(flow, dict) or flow.get("action") not in {"login", "link"}:
        return _authentication_failed("The sign-in request expired. Please try again.")

    try:
        token = _client().authorize_access_token()
        claims = token.get("userinfo") if isinstance(token, Mapping) else None
    except Exception as error:  # Authlib and provider transport errors share no single base class.
        current_app.logger.warning("OIDC callback failed (%s)", type(error).__name__)
        return _authentication_failed("Identity provider sign-in failed. Please try again.", flow)

    identity = _validated_identity(claims)
    if identity is None:
        return _authentication_failed("Identity provider sign-in failed. Please try again.", flow)
    issuer, subject, email = identity

    if flow["action"] == "link":
        return _complete_link(flow, issuer, subject, email)
    return _complete_login(issuer, subject, email, claims)


def _validated_identity(claims) -> tuple[str, str, str | None] | None:
    if not isinstance(claims, Mapping):
        return None
    issuer = claims.get("iss")
    subject = claims.get("sub")
    if (
        not isinstance(issuer, str)
        or issuer != current_app.config["OIDC_ISSUER_URL"]
        or len(issuer) > 255
        or not isinstance(subject, str)
        or not subject
        or len(subject) > 255
    ):
        return None
    email = claims.get("email")
    if not isinstance(email, str) or len(email) > 320:
        email = None
    return issuer, subject, email


def _complete_link(flow: dict, issuer: str, subject: str, email: str | None):
    expected_user_id = flow.get("user_id")
    if (
        not current_user.is_authenticated
        or not isinstance(expected_user_id, int)
        or current_user.id != expected_user_id
        or not _recent_local_authentication()
    ):
        return _authentication_failed("The account-linking request expired. Please sign in again.", flow)

    claimed = db.session.scalar(
        db.select(OidcIdentity).where(OidcIdentity.issuer == issuer, OidcIdentity.subject == subject)
    )
    if claimed is not None:
        if claimed.user_id != current_user.id:
            return _authentication_failed("That identity cannot be connected to this account.", flow)
        if email is not None:
            claimed.email = email
        db.session.commit()
        flash(f"{current_app.config['OIDC_DISPLAY_NAME']} is already connected.", "success")
        return redirect(url_for("oidc.settings"))

    current_provider = db.session.scalar(
        db.select(OidcIdentity.id).where(
            OidcIdentity.user_id == current_user.id,
            OidcIdentity.issuer == issuer,
        )
    )
    if current_provider is not None:
        return _authentication_failed("This account already has an identity provider connection.", flow)

    db.session.add(OidcIdentity(user_id=current_user.id, issuer=issuer, subject=subject, email=email))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return _authentication_failed("That identity cannot be connected to this account.", flow)

    flash(f"{current_app.config['OIDC_DISPLAY_NAME']} connected successfully.", "success")
    return redirect(url_for("oidc.settings"))


def _complete_login(issuer: str, subject: str, email: str | None, claims: Mapping):
    identity = db.session.scalar(
        db.select(OidcIdentity).where(OidcIdentity.issuer == issuer, OidcIdentity.subject == subject)
    )
    if identity is not None:
        if email is not None:
            identity.email = email
        identity.last_login_at = utc_now()
        db.session.commit()
        return _log_in(identity.user)

    if not current_app.config["OIDC_AUTO_PROVISION"]:
        flash(
            "No linked account was found. Sign in with your password, then connect the identity provider from Account.",
            "warning",
        )
        return redirect(url_for("main.login"))

    return _provision_user(issuer, subject, email, claims)


def _provision_user(issuer: str, subject: str, email: str | None, claims: Mapping):
    preferred_username = claims.get("preferred_username")
    if isinstance(preferred_username, str) and preferred_username.strip():
        matching_user = db.session.scalar(
            db.select(User).where(db.func.lower(User.username) == preferred_username.strip().lower())
        )
        if matching_user is not None and not is_legacy_owner(matching_user.username, matching_user.password_hash):
            flash(
                "A local account with that username already exists. Sign in with its password and connect the identity provider.",
                "warning",
            )
            return redirect(url_for("main.login"))

    try:
        username = _provisioned_username(issuer, subject, claims)
    except RuntimeError:
        return _authentication_failed("The account could not be created. Please try again.")

    if not _ensure_registration_gate():
        return _authentication_failed("The account could not be created. Please try again.")

    user = User(username=username)
    user.set_password(secrets.token_urlsafe(64))
    identity = OidcIdentity(
        user=user,
        issuer=issuer,
        subject=subject,
        email=email,
        last_login_at=utc_now(),
    )
    db.session.add(user)

    legacy_owner = db.session.scalar(
        db.select(User).where(
            User.username == LEGACY_OWNER_USERNAME,
            User.password_hash == LEGACY_OWNER_PASSWORD_HASH,
        )
    )
    if legacy_owner is not None and is_legacy_owner(legacy_owner.username, legacy_owner.password_hash):
        db.session.flush()
        db.session.execute(db.update(Month).where(Month.user_id == legacy_owner.id).values(user_id=user.id))
        db.session.delete(legacy_owner)

    db.session.add(identity)

    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        winner = db.session.scalar(
            db.select(OidcIdentity).where(OidcIdentity.issuer == issuer, OidcIdentity.subject == subject)
        )
        if winner is not None:
            return _log_in(winner.user)
        return _authentication_failed("The account could not be created. Please try again.")

    flash("Account created from the identity provider.", "success")
    return _log_in(user)


def _provisioned_username(issuer: str, subject: str, claims: Mapping) -> str:
    raw_name = claims.get("preferred_username")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raw_name = claims.get("name")
    if not isinstance(raw_name, str) or not raw_name.strip():
        raw_name = "oidc-user"

    base = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw_name.strip()).strip("._-")
    if not base or not base[0].isalnum():
        base = "oidc-user"
    digest = hashlib.sha256(f"{issuer}\0{subject}".encode()).hexdigest()[:12]
    base = base[: _USERNAME_MAX_LENGTH - len(digest) - 1]
    candidate = f"{base}-{digest}"
    if db.session.scalar(db.select(User.id).where(db.func.lower(User.username) == candidate.lower())) is None:
        return candidate

    for suffix in range(2, 100):
        suffix_text = f"-{suffix}"
        alternate = f"{candidate[: _USERNAME_MAX_LENGTH - len(suffix_text)]}{suffix_text}"
        if db.session.scalar(db.select(User.id).where(db.func.lower(User.username) == alternate.lower())) is None:
            return alternate
    raise RuntimeError("Could not allocate an OIDC username")


def _ensure_registration_gate() -> bool:
    if db.session.get(RegistrationGate, 1) is not None:
        return True
    try:
        with db.session.begin_nested():
            db.session.add(RegistrationGate(id=1))
    except IntegrityError:
        # Another request claimed the gate; OIDC provisioning remains allowed.
        return db.session.get(RegistrationGate, 1) is not None
    return True


def _recent_local_authentication() -> bool:
    authenticated_at = session.get("local_authenticated_at")
    return (
        session.get("auth_method") == "password"
        and isinstance(authenticated_at, int)
        and 0 <= int(time()) - authenticated_at <= _LINK_WINDOW_SECONDS
    )


def _log_in(user: User):
    session.clear()
    login_user(user, remember=False, fresh=True)
    session["auth_method"] = "oidc"
    flash(f"Signed in with {current_app.config['OIDC_DISPLAY_NAME']}.", "success")
    return redirect(url_for("main.months"))


def _authentication_failed(message: str, flow: dict | None = None):
    flash(message, "error")
    if (flow or {}).get("action") == "link" and current_user.is_authenticated:
        return redirect(url_for("oidc.settings"))
    return redirect(url_for("main.login"))
