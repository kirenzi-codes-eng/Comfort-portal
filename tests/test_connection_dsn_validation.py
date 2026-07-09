import importlib

import pytest


@pytest.fixture
def connection_module():
    return importlib.import_module("src.database.connection")


def test_resolve_db_dsn_raises_clear_error_when_host_missing(monkeypatch, connection_module):
    monkeypatch.setenv("DB_HOST", "")
    monkeypatch.setenv("DB_NAME", "comfort")
    monkeypatch.setenv("DB_USER", "user")
    monkeypatch.setenv("DB_PASSWORD", "password")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_URL", raising=False)
    monkeypatch.setattr(connection_module.st, "secrets", {}, raising=False)

    with pytest.raises(connection_module.DatabaseUnavailableError, match="Missing required database settings"):
        connection_module._resolve_db_dsn()
