import unittest
from unittest.mock import patch

from src.views.home import (
    _should_use_mock_data,
    get_financial_metrics_cached,
    get_member_activity_timeline,
    get_member_summary_stats,
)


class HomeDashboardTests(unittest.TestCase):
    def test_should_use_mock_data_is_false_for_logged_in_user(self):
        self.assertFalse(_should_use_mock_data("MEM-001"))

    def test_get_member_activity_timeline_merges_subscription_and_loan_events(self):
        def fake_execute(query, params=None, fetch=False, fallback=None):
            if "FROM subscriptions" in query:
                return [
                    {"billing_month": "2026-05-01", "amount_paid": 20000.0, "status": "Paid", "payer_name": "Test User"},
                    {"billing_month": "2026-04-01", "amount_paid": 15000.0, "status": "Paid", "payer_name": "Test User"},
                ]
            if "FROM loans" in query:
                return [
                    {
                        "loan_id": "LN-001",
                        "applied_date": "2026-06-01",
                        "amount_requested": 120000.0,
                        "outstanding_balance": 80000.0,
                        "status": "Approved",
                        "approved_by": "Chairperson",
                        "applicant_name": "Test User",
                    },
                ]
            return []

        with patch("src.views.home.safe_execute_query", side_effect=fake_execute):
            timeline = get_member_activity_timeline("MEM-001", limit=5)

        self.assertEqual(len(timeline), 3)
        self.assertEqual(timeline[0]["kind"], "loan")
        self.assertEqual(timeline[1]["kind"], "subscription")
        self.assertEqual(timeline[2]["kind"], "subscription")
        self.assertIn("Outstanding: UGX 80,000", timeline[0]["description"])
        self.assertEqual(timeline[0]["follow_up"], "Follow up on repayment balance: UGX 80,000 outstanding.")
        self.assertIn("Reference: LN-001", timeline[0]["description"])
        self.assertIn("Approved by: Chairperson", timeline[0]["description"])
        self.assertIn("Applied by: Test User", timeline[0]["description"])
        self.assertIn("Paid by: Test User", timeline[1]["description"])
        self.assertEqual(timeline[1]["follow_up"], "No action required.")

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

    def test_get_admin_dashboard_metrics_separates_principal_and_unpaid_interest(self):
        def fake_execute(query, params=None, fetch=False, fallback=None):
            if "FROM loans" in query and "interest_accumulated" in query:
                return [
                    {
                        "amount_requested": 100000.0,
                        "outstanding_balance": 110000.0,
                        "interest_accumulated": 10000.0,
                    }
                ]
            if "FROM loans" in query:
                return []
            if "FROM members" in query:
                return [{"total_arrears": 0.0}]
            return []

        with patch("src.views.home.safe_execute_query", side_effect=fake_execute), patch(
            "src.views.home.get_effective_pool_balance", return_value=0.0
        ), patch("src.views.home.get_effective_pool_welfare_balance", return_value=0.0):
            from src.views.home import get_admin_dashboard_metrics

            metrics = get_admin_dashboard_metrics()

        self.assertEqual(metrics["total_cash_loaned"], 100000.0)
        self.assertEqual(metrics["total_unrepaid_principal"], 100000.0)
        self.assertEqual(metrics["total_unpaid_interest"], 10000.0)
        self.assertEqual(metrics["total_unrepaid_interest"], 10000.0)

    def test_member_summary_counts_activity_arrears_and_status_variants(self):
        captured = {}

        def fake_execute(query, params=None, fetch=False, fallback=None):
            captured["query"] = query
            captured["params"] = params
            return [{"total_members": 5, "active_members": 2, "inactive_members": 2, "pending_members": 1}]

        with patch("src.views.home.safe_execute_query", side_effect=fake_execute):
            stats = get_member_summary_stats()

        self.assertEqual(stats["active_members"], 2)
        self.assertEqual(stats["inactive_members"], 2)
        self.assertEqual(stats["required_action"], "Review 2 inactive members.")
        self.assertEqual(len(captured["params"]), 3)
        self.assertIn("greatest(0", captured["query"])


if __name__ == "__main__":
    unittest.main()
