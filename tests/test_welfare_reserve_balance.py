from datetime import date

from src.utils import balances


def test_member_balances_use_approved_ledger_accounts(monkeypatch):
    monkeypatch.setattr(balances, "ensure_accounting_schema", lambda: None)
    account_values = {
        "MEMBER_SAVINGS_LIABILITY": 50000.0,
        "MEMBER_WELFARE_LIABILITY": 100000.0,
        "MEMBER_CREDIT_LIABILITY": 0.0,
        "WELFARE_DEBT_RECEIVABLE": 0.0,
    }

    def fake_execute_query(query, params=None, fetch=False):
        if "FROM subscriptions s" in query:
            return []
        assert "accounting_journal_entries" in query
        return [{"balance": account_values[params[0]]}] if fetch else None

    monkeypatch.setattr(balances, "execute_query", fake_execute_query)

    assert balances.get_member_welfare_reserve_balance("M1") == 100000.0
    assert balances.get_member_savings_balance("M1") == 50000.0
    assert balances.get_effective_member_balance("M1") == 150000.0


def test_member_balances_include_unposted_paid_legacy_subscriptions_without_double_counting(monkeypatch):
    monkeypatch.setattr(balances, "ensure_accounting_schema", lambda: None)
    account_values = {
        "MEMBER_SAVINGS_LIABILITY": 2000.0,
        "MEMBER_WELFARE_LIABILITY": 90000.0,
        "MEMBER_CREDIT_LIABILITY": 0.0,
        "WELFARE_DEBT_RECEIVABLE": 0.0,
    }

    def fake_account_balance(account_code, member_id=None, loan_id=None):
        return balances.Decimal(str(account_values[account_code]))

    def fake_execute_query(query, params=None, fetch=False):
        assert "UPPER(BTRIM(COALESCE(s.status::text, ''))) IN ('APPROVED', 'POSTED', 'SUCCESS', 'PAID')" in query
        assert "NOT EXISTS" in query
        assert "t.cycle_on::date = s.billing_month::date" in query
        return [{
            "member_id": "mem-001",
            "amount_paid": 25000.0,
            "status": "pAiD",
        }]

    monkeypatch.setattr(balances, "_account_balance", fake_account_balance)
    monkeypatch.setattr(balances, "execute_query", fake_execute_query)

    result = balances.get_member_balances("MEM-001")

    assert result == {
        "savings_balance": 17000.0,
        "welfare_balance": 100000.0,
        "member_credit": 0.0,
        "welfare_debt": 0.0,
        "total_balance": 117000.0,
    }


def test_batch_member_balances_match_member_ids_case_insensitively(monkeypatch):
    monkeypatch.setattr(balances, "ensure_accounting_schema", lambda: None)

    def fake_execute_query(query, params=None, fetch=False):
        if "FROM subscriptions s" in query:
            return [{
                "member_id": "MEM-001",
                "amount_paid": 25000.0,
                "status": "PAID",
            }]
        assert "UPPER(BTRIM(e.member_id::text)) = ANY(%s)" in query
        assert params[0] == ["MEM-001"]
        return [
            {"member_id": "mem-001", "account_code": "MEMBER_SAVINGS_LIABILITY", "balance": 20000.0},
            {"member_id": "mem-001", "account_code": "MEMBER_WELFARE_LIABILITY", "balance": 90000.0},
        ]

    monkeypatch.setattr(balances, "execute_query", fake_execute_query)

    result = balances.get_member_balances_batch(["mem-001"])

    assert result["mem-001"] == {
        "savings_balance": 35000.0,
        "welfare_balance": 100000.0,
        "member_credit": 0.0,
        "welfare_debt": 0.0,
        "total_balance": 135000.0,
    }


def test_pool_balance_aggregates_ledger_liabilities_and_welfare_fund(monkeypatch):
    values = {
        "MEMBER_SAVINGS_LIABILITY": balances.Decimal("200000.00"),
        "MEMBER_WELFARE_LIABILITY": balances.Decimal("50000.00"),
        "WELFARE_FUND": balances.Decimal("30000.00"),
    }
    monkeypatch.setattr(balances, "_account_balance", lambda account_code, **kwargs: values[account_code])
    monkeypatch.setattr(
        balances,
        "_get_legacy_subscription_fund_allocations",
        lambda: {"savings": balances.Decimal("0"), "welfare": balances.Decimal("0")},
    )

    assert balances.get_effective_pool_balance() == 280000.0


def test_pool_welfare_balance_includes_reserved_member_and_fund_balances(monkeypatch):
    values = {
        "MEMBER_WELFARE_LIABILITY": balances.Decimal("80000.00"),
        "WELFARE_FUND": balances.Decimal("100000.00"),
    }
    monkeypatch.setattr(balances, "_account_balance", lambda account_code, **kwargs: values[account_code])
    monkeypatch.setattr(
        balances,
        "_get_legacy_subscription_fund_allocations",
        lambda: {"savings": balances.Decimal("0"), "welfare": balances.Decimal("0")},
    )

    assert balances.get_effective_pool_welfare_balance() == 180000.0


def test_legacy_subscription_pool_allocation_respects_member_welfare_reserve_cap(monkeypatch):
    monkeypatch.setattr(balances, "ensure_accounting_schema", lambda: None)
    monkeypatch.setattr(
        balances,
        "_get_unposted_legacy_subscription_rows",
        lambda: [
            {"member_id": "MEM-1", "amount_paid": 30000.0},
            {"member_id": "mem-2", "amount_paid": 50000.0},
        ],
    )

    def fake_execute_query(query, params=None, fetch=False):
        assert "MEMBER_WELFARE_LIABILITY" in query
        assert params == (["MEM-1", "MEM-2"],)
        return [
            {"member_key": "MEM-1", "welfare_balance": 90000.0},
            {"member_key": "MEM-2", "welfare_balance": 100000.0},
        ]

    monkeypatch.setattr(balances, "execute_query", fake_execute_query)

    assert balances._get_legacy_subscription_fund_allocations() == {
        "savings": balances.Decimal("70000.00"),
        "welfare": balances.Decimal("10000.00"),
    }


def test_global_subscription_arrears_include_legacy_paid_records_case_insensitively(monkeypatch):
    monkeypatch.setattr(balances, "ensure_accounting_schema", lambda: None)
    monkeypatch.setattr(
        balances,
        "_all_members",
        lambda: [{"member_id": "MEM-1"}, {"member_id": "MEM-2"}],
    )

    def fake_execute_query(query, params=None, fetch=False):
        if "FROM subscriptions s" in query:
            return [{"member_id": "mem-1", "amount_paid": 20000.0}]
        return [{"member_id": "mem-2", "paid": 20000.0}]

    monkeypatch.setattr(balances, "execute_query", fake_execute_query)

    result = balances.get_subscription_arrears(date(2026, 2, 28))

    assert result["total_arrears"] == 40000.0


def test_admin_dashboard_uses_savings_only_and_nets_loan_disbursement_reversals(monkeypatch):
    monkeypatch.setattr(balances, "ensure_accounting_schema", lambda: None)
    monkeypatch.setattr(balances, "get_effective_pool_savings_balance", lambda: 45000.0)
    monkeypatch.setattr(balances, "get_effective_pool_welfare_balance", lambda: 125000.0)
    monkeypatch.setattr(balances, "get_verified_cash_interest", lambda: 2500.0)
    monkeypatch.setattr(
        balances,
        "_account_balance",
        lambda account_code, **kwargs: balances.Decimal("1000.00"),
    )

    def fake_execute_query(query, params=None, fetch=False):
        assert "LEFT JOIN accounting_transactions original ON original.transaction_id = t.reversal_of" in query
        assert "t.category = 'REVERSAL' AND original.category = 'LOAN_DISBURSEMENT'" in query
        assert "SUM(e.debit - e.credit)" in query
        return [{"total_disbursed": 80000.0}]

    monkeypatch.setattr(balances, "execute_query", fake_execute_query)

    result = balances.get_admin_dashboard_balances()

    assert result["savings_pool"] == 45000.0
    assert result["welfare_pool"] == 125000.0
    assert result["total_disbursed"] == 80000.0


def test_loan_portfolio_displays_active_legacy_rows_without_fabricating_balances(monkeypatch):
    monkeypatch.setattr(balances, "ensure_accounting_schema", lambda: None)

    def fake_execute_query(query, params=None, fetch=False):
        assert "FROM loans l" in query
        assert "LEFT JOIN accounting_journal_entries e" in query
        assert "UPPER(BTRIM(l.status::text)) IN ('APPROVED', 'ACTIVE')" in query
        return [
            {
                "loan_id": 201,
                "member_id": "M-201",
                "full_name": "Ledger Borrower",
                "status": "Active",
                "ledger_entry_count": 3,
                "principal": 60000.0,
                "interest": 5000.0,
            },
            {
                "loan_id": 202,
                "member_id": "M-202",
                "full_name": "Legacy Borrower",
                "status": "Approved",
                "ledger_entry_count": 0,
                "principal": 0.0,
                "interest": 0.0,
            },
        ]

    monkeypatch.setattr(balances, "execute_query", fake_execute_query)

    result = balances.get_loan_portfolio()

    assert len(result["loans"]) == 2
    assert result["loans"][0]["outstanding"] == 65000.0
    assert result["loans"][0]["ledger_backed"] is True
    assert result["loans"][1]["outstanding"] is None
    assert result["loans"][1]["ledger_backed"] is False
    assert result["outstanding_principal"] == 60000.0
    assert result["outstanding_interest"] == 5000.0
    assert result["loans_requiring_reconciliation"] == 1
