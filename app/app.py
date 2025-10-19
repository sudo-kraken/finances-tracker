from __future__ import annotations

import os

from flask import Flask

from .config import Config
from .extensions import db, login_manager


def _build_app(config_overrides: dict | None = None) -> Flask:
    """Build the Flask application and return the singleton app."""
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

    # Initialise extensions
    db.init_app(app)
    login_manager.init_app(app)

    with app.app_context():
        # Keep all intra package imports relative so `app:app` works
        from . import models  # noqa: F401

        db.create_all()

    from .routes import bp as main_bp

    app.register_blueprint(main_bp)

    return app


app = _build_app()

if __name__ == "__main__":
    port = int(os.getenv("PORT", "7070"))
    app.run(host="0.0.0.0", port=port)
