import contextlib
import importlib
import types


def test_reload_module_executes_create_app_under_coverage():
    mod = importlib.import_module("app.app")
    assert isinstance(mod, types.ModuleType)

    reloaded = importlib.reload(mod)
    assert hasattr(reloaded, "app")

    # Blueprint should be registered on the reloaded app
    names = [bp.name for bp in reloaded.app.blueprints.values()]
    assert "main" in names

    from app.extensions import db as _db  # type: ignore

    with reloaded.app.app_context(), contextlib.suppress(Exception):
        _db.engine.dispose()
