import os

basedir = os.path.abspath(os.path.dirname(__file__))


def _env_flag(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # Build a path to 'db/finances.db' inside the app folder
    DB_FOLDER = os.environ.get("DATABASE_FOLDER", os.path.join(basedir, "db"))
    DEFAULT_DATABASE_URI = "sqlite:///" + os.path.join(DB_FOLDER, "finances.db")
    SQLALCHEMY_DATABASE_URI = os.environ.get("SQLALCHEMY_DATABASE_URI", DEFAULT_DATABASE_URI)

    # Only the bundled SQLite database needs a local directory.  External
    # database URIs (for example PostgreSQL) must not create an unused folder.
    if SQLALCHEMY_DATABASE_URI == DEFAULT_DATABASE_URI:
        os.makedirs(DB_FOLDER, exist_ok=True)
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    ALLOW_REGISTRATION = _env_flag("ALLOW_REGISTRATION")
    OIDC_ISSUER_URL = os.environ.get("OIDC_ISSUER_URL", "")
    OIDC_CLIENT_ID = os.environ.get("OIDC_CLIENT_ID", "")
    OIDC_CLIENT_SECRET = os.environ.get("OIDC_CLIENT_SECRET", "")
    OIDC_REDIRECT_URI = os.environ.get("OIDC_REDIRECT_URI", "")
    OIDC_DISPLAY_NAME = os.environ.get("OIDC_DISPLAY_NAME", "Pocket ID")
    OIDC_AUTO_PROVISION = _env_flag("OIDC_AUTO_PROVISION")
    OIDC_ONLY = _env_flag("OIDC_ONLY")
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _env_flag("SESSION_COOKIE_SECURE")
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_SECURE = SESSION_COOKIE_SECURE
