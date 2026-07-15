import unittest
from unittest.mock import patch

from src.views.home import _should_use_mock_data, get_financial_metrics_cached, get_member_activity_timeline


class HomeDashboardTests(unittest.TestCase):
    def test_should_use_mock_data_is_false_for_logged_in_user(self):
        self.assertFalse(_should_use_mock_data("MEM-001"))

    def test_get_member_activity_timeline_merges_subscription_and_loan_events(self):
        def fake_execute(query, params=None, fetch=False, fallback=None):
            if "FROM subscriptions" in query:
                return [
                    {"billing_month": "2026-05-01", "amount_paid": 20000.0, "status": "Paid"},
                    {"billing_month": "2026-04-01", "amount_paid": 15000.0, "status": "Paid"},
                ]
            if "FROM loans" in query:
                return [
                    {"applied_date": "2026-06-01", "amount_requested": 120000.0, "status": "Approved"},
                ]
            return []

        with patch("src.views.home.safe_execute_query", side_effect=fake_execute):
            timeline = get_member_activity_timeline("MEM-001", limit=5)

        self.assertEqual(len(timeline), 3)
        self.assertEqual(timeline[0]["kind"], "loan")
        self.assertEqual(timeline[1]["kind"], "subscription")
        self.assertEqual(timeline[2]["kind"], "subscription")

    def test_get_financial_metrics_cached_uses_total_subscription_contributions(self):
        def fake_execute(query, params=None, fetch=False, fallback=None):
            if "FROM subscriptions" in query and "SUM(amount_paid)" in query and "member_id = %s" in query:
                return [{"total_contributed": 250000.0}]
            if "FROM loans" in query:
                return [{"outstanding_balance": 0.0, "interest_accumulated": 0.0, "amount_requested": 0.0}]
            return []

        with patch("src.views.home.safe_execute_query", side_effect=fake_execute):
            metrics = get_financial_metrics_cached("MEM-001")

        self.assertEqual(metrics["total_paid"], 250000.0)


if __name__ == "__main__":
    unittest.main()
