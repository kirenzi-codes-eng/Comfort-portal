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


def test_init_db_pool_uses_connection_pool_for_postgres_urls(monkeypatch, connection_module):
    monkeypatch.setattr(connection_module.st, "secrets", {"DATABASE_URL": "postgresql://user:pass@db.example.com:5432/comfort"}, raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_URL", raising=False)
    monkeypatch.setattr(connection_module, "_resolve_db_dsn", lambda: "postgresql://user:pass@db.example.com:5432/comfort?sslmode=require&connect_timeout=10")
    connection_module.clear_cached_connection()

    class DummyPool:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def getconn(self):
            return object()

    created = {}

    def fake_pool_factory(*args, **kwargs):
        created["args"] = args
        created["kwargs"] = kwargs
        return DummyPool(*args, **kwargs)

    monkeypatch.setattr(connection_module.psycopg2.pool, "SimpleConnectionPool", fake_pool_factory)

    pool = connection_module.init_db_pool(minconn=1, maxconn=2)

    assert pool is not None
    assert created["kwargs"].get("dsn") == "postgresql://user:pass@db.example.com:5432/comfort?sslmode=require&connect_timeout=10"
