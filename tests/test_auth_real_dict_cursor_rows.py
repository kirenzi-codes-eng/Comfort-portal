from contextlib import contextmanager

import src.components.auth as auth


class FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, *args, **kwargs):
        return None

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return self._rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class FakeConnection:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return FakeCursor(self._rows)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_find_avatar_column_uses_dict_access(monkeypatch):
    monkeypatch.setattr(auth, "_ensure_member_profile_columns", lambda: None)

    @contextmanager
    def fake_get_conn_from_pool():
        yield FakeConnection([{"column_name": "avatar_url"}])

    monkeypatch.setattr(auth, "get_conn_from_pool", fake_get_conn_from_pool)

    assert auth._find_avatar_column() == "avatar_url"


def test_get_member_columns_uses_dict_access(monkeypatch):
    monkeypatch.setattr(auth, "_ensure_member_profile_columns", lambda: None)

    @contextmanager
    def fake_get_conn_from_pool():
        yield FakeConnection([
            {"column_name": "member_id"},
            {"column_name": "avatar_url"},
        ])

    monkeypatch.setattr(auth, "get_conn_from_pool", fake_get_conn_from_pool)

    columns = auth._get_member_columns()

    assert "member_id" in columns
    assert "avatar_url" in columns
