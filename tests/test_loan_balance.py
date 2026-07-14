import unittest
from datetime import date, datetime
from unittest.mock import patch

from src.views.home import calculate_effective_loan_balance, get_financial_metrics_cached, safe_execute_query
from src.views.loans import (
    create_historical_loan_record,
    get_loan_interest_schedule,
    months_between,
    should_apply_interest_for_loan,
    update_interest_accumulation,
)


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

    def test_months_between_counts_partial_months_for_daily_interest(self):
        self.assertAlmostEqual(months_between(datetime(2026, 5, 11), datetime(2026, 7, 14)), 2 + (3 / 31), places=4)

    def test_grace_period_defers_interest_until_ten_days_after_start(self):
        start_date = datetime(2026, 5, 11, 9, 0)
        reference_date = datetime(2026, 5, 20, 8, 0)
        self.assertFalse(should_apply_interest_for_loan(start_date, reference_date, None, None))

    def test_payment_triggers_immediate_interest_after_grace_period(self):
        start_date = datetime(2026, 5, 11, 9, 0)
        reference_date = datetime(2026, 5, 21, 8, 0)
        last_interest_date = datetime(2026, 5, 20, 8, 0)
        last_payment_date = datetime(2026, 5, 21, 8, 0)
        self.assertTrue(should_apply_interest_for_loan(start_date, reference_date, last_interest_date, last_payment_date))

    def test_get_loan_interest_schedule_reports_grace_and_next_interest_dates(self):
        start_date = datetime(2026, 5, 11, 9, 0)
        next_due, grace_end = get_loan_interest_schedule(start_date, None, None, None)
        self.assertEqual(next_due, date(2026, 5, 21))
        self.assertEqual(grace_end, date(2026, 5, 21))

    def test_create_historical_loan_record_inserts_and_backfills_interest(self):
        insert_calls = []

        def fake_execute(query, params=None, fetch=False):
            insert_calls.append((query, params, fetch))
            return None

        with patch("src.views.loans.ensure_loans_purpose_column", return_value=True), \
             patch("src.views.loans.execute_query", side_effect=fake_execute), \
             patch("src.views.loans.update_interest_accumulation") as mock_update:
            created = create_historical_loan_record(
                member_id="member-1",
                principal_amount=5000.0,
                loan_date=date(2023, 1, 1),
                status="Cleared",
                accumulated_interest=250.0,
                notes="Legacy repayment before launch",
            )

        self.assertTrue(created)
        self.assertEqual(insert_calls[0][1][0], "member-1")
        self.assertEqual(insert_calls[0][1][1], 5000.0)
        self.assertEqual(insert_calls[0][1][3], "Legacy repayment before launch")
        self.assertEqual(insert_calls[0][1][7], 250.0)
        mock_update.assert_not_called()

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
