from __future__ import annotations

import importlib
import os
import sys
from urllib.parse import urlsplit

import atheris

os.environ.setdefault("FINANCES_TESTING", "1")
os.environ.setdefault("SQLALCHEMY_DATABASE_URI", "sqlite://")

with atheris.instrument_imports():
    oidc = importlib.import_module("app.oidc")


def test_one_input(data: bytes) -> None:
    provider = atheris.FuzzedDataProvider(data)
    component = provider.ConsumeUnicodeNoSurrogates(1024)
    candidates = (
        component,
        f"https://{component}",
        f"https://example.com/{component}",
        f"https://example.com/auth/oidc/callback{component}",
        f"http://localhost:7070/{component}",
    )

    for callback in (False, True):
        for candidate in candidates:
            try:
                oidc._validate_url("OIDC_FUZZ_URL", candidate, callback=callback)
            except RuntimeError:
                continue

            parsed = urlsplit(candidate)
            assert parsed.scheme in {"http", "https"}
            assert parsed.netloc and parsed.hostname
            assert parsed.username is None and parsed.password is None
            assert not parsed.query and not parsed.fragment
            assert not any(character.isspace() or ord(character) < 32 for character in candidate)
            _ = parsed.port
            if parsed.scheme == "http":
                assert parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            if callback:
                assert parsed.path == "/auth/oidc/callback"


def main() -> None:
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
