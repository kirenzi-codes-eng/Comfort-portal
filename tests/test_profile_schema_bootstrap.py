from src.views import admin_docs


def test_ensure_member_profile_columns_creates_members_table(monkeypatch):
    calls = []

    def fake_execute_query(query, params=None, fetch=False):
        calls.append((query, params, fetch))
        return None

    monkeypatch.setattr(admin_docs, "execute_query", fake_execute_query)

    admin_docs.ensure_member_profile_columns()

    assert any("CREATE TABLE IF NOT EXISTS members" in query for query, _, _ in calls)
