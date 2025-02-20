import os

basedir = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY") or "you-will-never-guess"
    
    # Build a path to 'db/finances.db' inside the app folder
    DB_FOLDER = os.path.join(basedir, "db")
    if not os.path.exists(DB_FOLDER):
        os.makedirs(DB_FOLDER)

    SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(DB_FOLDER, "finances.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
