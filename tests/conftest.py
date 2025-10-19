import contextlib
import importlib
import os
import sys

import pytest


@pytest.fixture(scope="session")
def app_module():
    # Safe test config
    os.environ["FINANCES_TESTING"] = "1"
    # If already imported, drop and re-import so the env takes effect
    if "app" in sys.modules:
        sys.modules.pop("app")
    return importlib.import_module("app")


@pytest.fixture
def app(app_module):
    return app_module.app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    from app.extensions import db as _db  # type: ignore

    with app.app_context():
        _db.create_all()
        try:
            yield _db
        finally:
            # Clean rows
            _db.session.remove()
            for tbl in reversed(_db.metadata.sorted_tables):
                _db.session.execute(tbl.delete())
            _db.session.commit()
            # Dispose engine to avoid unclosed DB warnings on Windows
            with contextlib.suppress(Exception):
                _db.engine.dispose()
