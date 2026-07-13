import unittest
from datetime import datetime
from unittest.mock import patch

from src.views.home import calculate_effective_loan_balance, get_financial_metrics_cached, safe_execute_query
from src.views.loans import update_interest_accumulation


class LoanBalanceTests(unittest.TestCase):
    def test_includes_interest_when_outstanding_balance_is_still_principal_only(self):
        rows = [
            {"outstanding_balance": 1000.0, "interest_accumulated": 100.0, "amount_requested": 1000.0},
        ]
        self.assertEqual(calculate_effective_loan_balance(rows), 1100.0)

    def test_uses_outstanding_balance_when_it_already_includes_interest(self):
        rows = [
            {"outstanding_balance": 1100.0, "interest_accumulated": 100.0, "amount_requested": 1000.0},
        ]
        self.assertEqual(calculate_effective_loan_balance(rows), 1100.0)

    def test_does_not_double_count_interest_after_partial_repayment(self):
        rows = [
            {"outstanding_balance": 50000.0, "interest_accumulated": 10000.0, "amount_requested": 100000.0},
        ]
        self.assertEqual(calculate_effective_loan_balance(rows), 50000.0)

    def test_safe_execute_query_preserves_empty_results_over_fallback(self):
        with patch("src.views.home.execute_query", return_value=[]):
            result = safe_execute_query("SELECT 1;", fetch=True, fallback=[{"outstanding_balance": 260000.0}])
            self.assertEqual(result, [])

    def test_update_interest_accumulation_uses_applied_date_for_older_active_loans(self):
        updates = []

        def fake_execute(query, params=None, fetch=False):
            if fetch and "FROM loans" in query:
                return [{
                    "loan_id": 101,
                    "outstanding_balance": 1000.0,
                    "interest_accumulated": 0.0,
                    "approved_date": None,
                    "applied_date": datetime(2023, 1, 1),
                    "status": "Active",
                }]
            if "UPDATE loans SET interest_accumulated" in query:
                updates.append(params)
                return None
            return []

        with patch("src.views.loans.execute_query", side_effect=fake_execute):
            update_interest_accumulation(datetime(2023, 2, 1))

        self.assertEqual(len(updates), 1)
        self.assertAlmostEqual(updates[0][0], 100.0)
        self.assertAlmostEqual(updates[0][1], 1100.0)

    @patch("src.views.home.get_effective_member_balance", return_value=0.0)
    def test_get_financial_metrics_cached_returns_zero_balance_when_no_active_loans(self, _):
        def fake_execute(query, params=None, fetch=False):
            if "FROM loans WHERE member_id = %s AND status IN ('Active','Approved')" in query:
                return []
            if "COALESCE(SUM(amount_paid),0) AS total_paid_year" in query:
                return [{"total_paid_year": 0}]
            return [{"outstanding_balance": 0.0, "interest_accumulated": 0.0, "amount_requested": 0.0}]

        with patch("src.views.home.execute_query", side_effect=fake_execute):
            get_financial_metrics_cached.clear()
            metrics = get_financial_metrics_cached("test_user")
            self.assertEqual(metrics["loan_balance"], 0.0)


if __name__ == "__main__":
    unittest.main()
