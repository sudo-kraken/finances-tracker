import importlib


def test_config_defaults_importable():
    from app.config import Config  # type: ignore

    c = Config()
    assert hasattr(c, "SECRET_KEY")
    assert hasattr(c, "SQLALCHEMY_DATABASE_URI")


def test_db_folder_creation_line_is_executed(monkeypatch):
    import app.config as cfg  # type: ignore

    # Force the import-time branch that calls os.makedirs
    monkeypatch.setattr("os.path.exists", lambda path: False)
    calls = {"count": 0}

    def fake_makedirs(path):
        calls["count"] += 1

    monkeypatch.setattr("os.makedirs", fake_makedirs)
    importlib.reload(cfg)

    # At least one makedirs call should have been attempted
    assert calls["count"] >= 1
