import importlib

import pytest

import app.config as config_module


def test_config_defaults_importable():
    c = config_module.Config()
    assert hasattr(c, "SECRET_KEY")
    assert hasattr(c, "SQLALCHEMY_DATABASE_URI")


def test_config_uses_database_uri_from_environment(monkeypatch):
    with monkeypatch.context() as scoped_monkeypatch:
        scoped_monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "sqlite:///custom.db")
        reloaded = importlib.reload(config_module)

    assert reloaded.Config.SQLALCHEMY_DATABASE_URI == "sqlite:///custom.db"
    importlib.reload(config_module)


def test_oidc_only_flag_uses_environment(monkeypatch):
    with monkeypatch.context() as scoped_monkeypatch:
        scoped_monkeypatch.setenv("OIDC_ONLY", "true")
        reloaded = importlib.reload(config_module)

    assert reloaded.Config.OIDC_ONLY is True
    importlib.reload(config_module)


def test_db_folder_creation_line_is_executed(monkeypatch):
    # Force the import-time branch that calls os.makedirs
    monkeypatch.setattr("os.path.exists", lambda path: False)
    calls = {"count": 0}

    def fake_makedirs(path, exist_ok=False):
        calls["count"] += 1
        assert exist_ok is True

    monkeypatch.setattr("os.makedirs", fake_makedirs)
    importlib.reload(config_module)

    # At least one makedirs call should have been attempted
    assert calls["count"] >= 1


def test_app_requires_an_explicit_secret_key():
    from app import create_app

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app({"TESTING": False, "SECRET_KEY": None})
