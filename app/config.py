import os

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "you-will-never-guess"

    # Build a path to 'db/finances.db' inside the app folder
    DB_FOLDER = os.path.join(basedir, "db")
    DEFAULT_DATABASE_URI = "sqlite:///" + os.path.join(DB_FOLDER, "finances.db")
    SQLALCHEMY_DATABASE_URI = os.environ.get("SQLALCHEMY_DATABASE_URI", DEFAULT_DATABASE_URI)

    # Only the bundled SQLite database needs a local directory.  External
    # database URIs (for example PostgreSQL) must not create an unused folder.
    if SQLALCHEMY_DATABASE_URI == DEFAULT_DATABASE_URI and not os.path.exists(DB_FOLDER):
        os.makedirs(DB_FOLDER)
    SQLALCHEMY_TRACK_MODIFICATIONS = False
