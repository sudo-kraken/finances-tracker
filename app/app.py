from __future__ import annotations

import os

from flask import Flask, flash, redirect, session, url_for
from flask_login import current_user, logout_user
from sqlalchemy import event

from .config import Config
from .extensions import csrf, db, login_manager


def create_app(config_overrides: dict | None = None) -> Flask:
    """Build and configure a Flask application."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config.from_object(Config)

    # Test friendly overrides; the test suite sets FINANCES_TESTING=1
    if os.getenv("FINANCES_TESTING") == "1":
        app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            SQLALCHEMY_DATABASE_URI="sqlite://",
            SECRET_KEY="test-secret",
        )

    if config_overrides:
        app.config.update(config_overrides)

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError("SECRET_KEY must be set to a long, random value.")

    # Initialise extensions
    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    with app.app_context():
        from . import models  # noqa: F401
        from .schema_migrations import upgrade_schema

        if db.engine.dialect.name == "sqlite":

            @event.listens_for(db.engine, "connect")
            def _configure_sqlite(dbapi_connection, _connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys = ON")
                cursor.execute("PRAGMA busy_timeout = 30000")
                cursor.close()

        upgrade_schema(db.engine, db.metadata)

    from .oidc import bp as oidc_bp
    from .oidc import init_oidc
    from .routes import bp as main_bp

    init_oidc(app)
    app.register_blueprint(main_bp)
    app.register_blueprint(oidc_bp)

    @app.before_request
    def enforce_oidc_only_sessions():
        if app.config["OIDC_ONLY"] and current_user.is_authenticated and session.get("auth_method") != "oidc":
            session.clear()
            logout_user()
            flash(f"Sign in with {app.config['OIDC_DISPLAY_NAME']} to continue.", "warning")
            return redirect(url_for("main.login"))
        return None

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response

    return app


_build_app = create_app
app = create_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "7070"))
    app.run(host="0.0.0.0", port=port)
