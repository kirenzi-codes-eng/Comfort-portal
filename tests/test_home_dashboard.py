import unittest
from unittest.mock import patch

from src.database.connection import DatabaseUnavailableError
from src.views.home import (
    _should_use_mock_data,
    get_financial_metrics_cached,
    get_member_activity_timeline,
    get_member_summary_stats,
    safe_execute_query,
)


class HomeDashboardTests(unittest.TestCase):
    def test_safe_execute_query_uses_fallback_for_wrapped_database_errors(self):
        fallback = [{"total_interest_collected": 0.0}]

        with patch(
            "src.views.home.execute_query",
            side_effect=DatabaseUnavailableError("Database query unavailable"),
        ):
            rows = safe_execute_query(
                "SELECT total_interest_collected FROM loans;",
                fetch=True,
                fallback=fallback,
            )

        self.assertEqual(rows, fallback)

    def test_should_use_mock_data_is_false_for_logged_in_user(self):
        self.assertFalse(_should_use_mock_data("MEM-001"))

    def test_get_member_activity_timeline_uses_approved_ledger_events(self):
        with patch(
            "src.views.home.get_subscription_history",
            return_value=[
                {
                    "billing_month": "2026-05-01",
                    "approved_at": "2026-05-03",
                    "amount_paid": 20000.0,
                    "status": "APPROVED",
                    "full_name": "Test User",
                    "reference": "subscription-proof:1",
                },
            ],
        ), patch(
            "src.views.home.get_loan_records",
            return_value=[
                {
                    "loan_id": 101,
                    "applied_date": "2026-06-01",
                    "amount_requested": 120000.0,
                    "outstanding_balance": 80000.0,
                    "ledger_backed": True,
                    "status": "Approved",
                    "approved_by": "Chairperson",
                    "applicant_name": "Test User",
                },
            ],
        ):
            timeline = get_member_activity_timeline("MEM-001", limit=5)

        self.assertEqual(len(timeline), 2)
        self.assertEqual(timeline[0]["kind"], "loan")
        self.assertEqual(timeline[1]["kind"], "subscription")
        self.assertIn("Outstanding: UGX 80,000", timeline[0]["description"])
        self.assertEqual(timeline[0]["follow_up"], "Follow up on repayment balance: UGX 80,000 outstanding.")
        self.assertIn("Reference: 101", timeline[0]["description"])
        self.assertIn("Approved by: Chairperson", timeline[0]["description"])
        self.assertIn("Applied by: Test User", timeline[0]["description"])
        self.assertIn("Paid by: Test User", timeline[1]["description"])
        self.assertEqual(timeline[1]["follow_up"], "No action required.")

    def test_get_financial_metrics_cached_uses_total_subscription_contributions(self):
        with patch("src.views.home.get_subscription_totals", return_value={"total_paid": 250000.0}), patch(
            "src.views.home.get_member_loan_outstanding_total", return_value=0.0
        ), patch("src.views.home.get_member_subscription_arrears", return_value=0.0):
            metrics = get_financial_metrics_cached("MEM-001")

        self.assertEqual(metrics["total_paid"], 250000.0)

    def test_get_admin_dashboard_metrics_separates_principal_and_unpaid_interest(self):
        with patch(
            "src.views.home.get_admin_dashboard_balances",
            return_value={
                "savings_pool": 0.0,
                "welfare_pool": 0.0,
                "total_disbursed": 100000.0,
                "interest_collected": 2500.0,
                "outstanding_interest": 10000.0,
            },
        ), patch(
            "src.views.home.get_loan_portfolio",
            return_value={
                "loans": [],
                "outstanding_principal": 100000.0,
                "outstanding_interest": 10000.0,
                "outstanding_total": 110000.0,
            },
        ), patch(
            "src.views.home.get_subscription_arrears", return_value={"total_arrears": 0.0}
        ):
            from src.views.home import get_admin_dashboard_metrics

            metrics = get_admin_dashboard_metrics()

        self.assertEqual(metrics["total_cash_loaned"], 100000.0)
        self.assertEqual(metrics["total_unrepaid_principal"], 100000.0)
        self.assertEqual(metrics["total_unpaid_interest"], 10000.0)
        self.assertEqual(metrics["total_unrepaid_interest"], 10000.0)
        self.assertEqual(metrics["total_interest_collected"], 2500.0)

    def test_admin_dashboard_includes_unreconciled_active_loan_accounts(self):
        with patch(
            "src.views.home.get_admin_dashboard_balances",
            return_value={
                "savings_pool": 0.0,
                "welfare_pool": 0.0,
                "total_disbursed": 0.0,
                "interest_collected": 0.0,
                "outstanding_interest": 0.0,
            },
        ), patch(
            "src.views.home.get_loan_portfolio",
            return_value={
                "loans": [{
                    "member_name": "Legacy Borrower",
                    "status": "Approved",
                    "outstanding": None,
                    "ledger_backed": False,
                }],
                "outstanding_principal": 0.0,
                "outstanding_interest": 0.0,
                "outstanding_total": 0.0,
                "loans_requiring_reconciliation": 1,
            },
        ), patch(
            "src.views.home.get_subscription_arrears", return_value={"total_arrears": 0.0}
        ):
            from src.views.home import get_admin_dashboard_metrics

            metrics = get_admin_dashboard_metrics()

        self.assertEqual(metrics["loans_requiring_reconciliation"], 1)
        self.assertEqual(metrics["borrowers"][0]["loan_status"], "Needs ledger reconciliation")
        self.assertIsNone(metrics["borrowers"][0]["loan_balance"])

    def test_member_summary_counts_activity_arrears_and_status_variants(self):
        with patch(
            "src.views.home.get_member_activity_summary",
            return_value={
                "total_members": 5,
                "active_members": 2,
                "inactive_members": 2,
                "pending_members": 1,
                "active_member_names": ["Active One", "Active Two"],
                "inactive_member_names": ["Inactive One", "Inactive Two"],
            },
        ):
            stats = get_member_summary_stats()

        self.assertEqual(stats["active_members"], 2)
        self.assertEqual(stats["inactive_members"], 2)
        self.assertEqual(stats["active_member_names"], ["Active One", "Active Two"])
        self.assertEqual(stats["inactive_member_names"], ["Inactive One", "Inactive Two"])
        self.assertEqual(stats["required_action"], "Review 2 inactive members.")


if __name__ == "__main__":
    unittest.main()
