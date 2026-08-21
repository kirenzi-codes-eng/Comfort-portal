import types

from src.utils import balances


class _DummyState(dict):
    pass


def test_member_welfare_reserve_is_capped_and_total_balance_includes_it(monkeypatch):
    monkeypatch.setattr(balances, "ensure_member_balance_adjustments_table", lambda: None)

    def fake_execute_query(query, params=None, fetch=False):
        if "FROM subscriptions" in query and "member_id = %s" in query:
            return [{"total_contributions": 150000.0}] if fetch else None
        if "FROM member_balance_adjustments" in query and "adjustment_type = 'withdrawal'" in query:
            return [{"total_withdrawn": 0.0}] if fetch else None
        return [] if fetch else None

    monkeypatch.setattr(balances, "execute_query", fake_execute_query)

    assert balances.get_member_welfare_reserve_balance("M1") == 100000.0
    assert balances.get_member_savings_balance("M1") == 50000.0
    assert balances.get_effective_member_balance("M1") == 150000.0


def test_pool_balance_stays_at_net_contributions_after_withdrawals(monkeypatch):
    monkeypatch.setattr(balances, "ensure_member_balance_adjustments_table", lambda: None)

    def fake_execute_query(query, params=None, fetch=False):
        if "FROM subscriptions" in query and "member_id = %s" not in query:
            return [{"total_contributions": 300000.0}] if fetch else None
        if "FROM member_balance_adjustments" in query and "adjustment_type = 'withdrawal'" in query and "member_id = %s" in query:
            return [{"total_withdrawn": 20000.0}] if fetch else None
        if "FROM member_balance_adjustments" in query and "adjustment_type = 'withdrawal'" in query and "member_id = %s" not in query:
            return [{"total_withdrawn": 20000.0}] if fetch else None
        return [] if fetch else None

    monkeypatch.setattr(balances, "execute_query", fake_execute_query)

    assert balances.get_effective_pool_balance() == 280000.0


def test_pool_welfare_balance_uses_member_caps(monkeypatch):
    monkeypatch.setattr(balances, "ensure_member_balance_adjustments_table", lambda: None)

    def fake_execute_query(query, params=None, fetch=False):
        if "total_welfare" in query:
            assert params == (100000.0,)
            return [{"total_welfare": 180000.0}] if fetch else None
        return [] if fetch else None

    monkeypatch.setattr(balances, "execute_query", fake_execute_query)

    assert balances.get_effective_pool_welfare_balance() == 180000.0
