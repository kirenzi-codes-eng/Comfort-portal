import unittest
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from src.utils.balances import (
    DuplicateFinancialTransactionError,
    _allocate_proportionally,
    get_member_loan_accounts,
    get_loan_records,
    record_loan_interest_accrual,
    record_loan_repayment,
)
from src.views.home import get_financial_metrics_cached, safe_execute_query
from src.views.loans import (
    approve_loan,
    create_historical_loan_record,
    get_loan_interest_schedule,
    months_between,
    should_apply_interest_for_loan,
    update_interest_accumulation,
)


class LoanBalanceTests(unittest.TestCase):
    def test_member_loan_accounts_include_unledgered_loans_without_claiming_zero_balance(self):
        loan = {
            "loan_id": 101,
            "member_id": "M101",
            "status": "Approved",
            "approved_date": date(2026, 1, 1),
            "applied_date": date(2025, 12, 20),
        }
        unledgered = {
            "principal": None,
            "interest": None,
            "outstanding": None,
            "ledger_backed": False,
        }
        with patch("src.utils.balances.ensure_accounting_schema"), patch(
            "src.utils.balances.execute_query", return_value=[loan]
        ), patch(
            "src.utils.balances._get_loan_balances_batch",
            return_value={101: unledgered},
        ):
            accounts = get_member_loan_accounts("m101")

        self.assertEqual(len(accounts), 1)
        self.assertEqual(accounts[0]["loan_id"], 101)
        self.assertFalse(accounts[0]["ledger_backed"])
        self.assertIsNone(accounts[0]["outstanding"])

    def test_member_loan_history_shows_unledgered_balance_as_unavailable(self):
        loan = {
            "loan_id": 101,
            "member_id": "M101",
            "amount_requested": Decimal("50000.00"),
            "status": "Active",
            "approved_date": date(2026, 1, 1),
            "applied_date": date(2025, 12, 20),
        }
        with patch("src.utils.balances.execute_query", return_value=[loan]), patch(
            "src.utils.balances.loans_table_has_purpose_column", return_value=True
        ), patch(
            "src.utils.balances._get_loan_balances_batch",
            return_value={
                101: {
                    "principal": None,
                    "interest": None,
                    "outstanding": None,
                    "ledger_backed": False,
                }
            },
        ):
            records = get_loan_records(member_id="M101")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["loan_id"], 101)
        self.assertFalse(records[0]["ledger_backed"])
        self.assertIsNone(records[0]["outstanding_balance"])
        self.assertIsNone(records[0]["interest_accumulated"])

    def test_allocation_rounding_conserves_pool_without_negative_shares(self):
        pool = Decimal("0.02")
        allocations = _allocate_proportionally(pool, {
            "M1": Decimal("1"),
            "M2": Decimal("1"),
            "M3": Decimal("1"),
            "M4": Decimal("1"),
        })

        self.assertEqual(sum(allocations.values()), pool)
        self.assertTrue(all(amount >= 0 for amount in allocations.values()))

    def test_repayment_applies_interest_before_principal_and_records_overpayment_credit(self):
        from unittest.mock import MagicMock

        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [("M101",), None]
        cursor.fetchall.return_value = [
            ("LOAN_PRINCIPAL_RECEIVABLE", Decimal("-80.00")),
            ("LOAN_INTEREST_RECEIVABLE", Decimal("-30.00")),
        ]
        connection_context = MagicMock()
        connection_context.__enter__.return_value = conn

        with patch("src.utils.balances.ensure_accounting_schema"), patch(
            "src.utils.balances.get_conn_from_pool", return_value=connection_context
        ), patch("src.utils.balances.record_transaction") as post:
            result = record_loan_repayment(
                loan_id=101,
                member_id="M101",
                amount=120.0,
                reference="repayment-101",
                approved_by="T101",
            )

        self.assertEqual(result["interest_paid"], 30.0)
        self.assertEqual(result["principal_paid"], 80.0)
        self.assertEqual(result["overpayment_credit"], 10.0)
        self.assertEqual(result["principal_remaining"], 0.0)
        self.assertEqual(result["interest_remaining"], 0.0)
        entries = post.call_args.kwargs["entries"]
        credit_line = next(line for line in entries if line["account_code"] == "MEMBER_CREDIT_LIABILITY")
        self.assertEqual(credit_line["credit"], Decimal("10.00"))
        self.assertIs(post.call_args.kwargs["connection"], conn)
        self.assertIn("FOR UPDATE", cursor.execute.call_args_list[0].args[0])

    def test_repayment_rejects_a_loan_owned_by_another_member(self):
        from unittest.mock import MagicMock

        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None
        connection_context = MagicMock()
        connection_context.__enter__.return_value = conn

        with patch("src.utils.balances.ensure_accounting_schema"), patch(
            "src.utils.balances.get_conn_from_pool", return_value=connection_context
        ), patch("src.utils.balances.record_transaction") as post:
            with self.assertRaisesRegex(ValueError, "not found for this member"):
                record_loan_repayment(
                    loan_id=101,
                    member_id="M101",
                    amount=50.0,
                    reference="repayment-wrong-owner",
                    approved_by="T101",
                )

        post.assert_not_called()

    def test_reversed_repayment_reference_cannot_be_reported_as_a_successful_retry(self):
        from unittest.mock import MagicMock

        conn = MagicMock()
        cursor = conn.cursor.return_value.__enter__.return_value
        cursor.fetchone.side_effect = [
            ("M101",),
            ("tx-101", "M101", 101, Decimal("50.00"), {
                "interest_paid": "10.00",
                "principal_paid": "40.00",
                "overpayment_credit": "0.00",
            }, True),
        ]
        connection_context = MagicMock()
        connection_context.__enter__.return_value = conn

        with patch("src.utils.balances.ensure_accounting_schema"), patch(
            "src.utils.balances.get_conn_from_pool", return_value=connection_context
        ):
            with self.assertRaisesRegex(DuplicateFinancialTransactionError, "already been reversed"):
                record_loan_repayment(
                    loan_id=101,
                    member_id="M101",
                    amount=50.0,
                    reference="repayment-reversed",
                    approved_by="T101",
                )

    def test_interest_accrual_rejects_a_loan_owned_by_another_member(self):
        with patch("src.utils.balances.ensure_accounting_schema"), patch(
            "src.utils.balances.execute_query",
            return_value=[{"member_id": "OTHER", "status": "Active"}],
        ), patch("src.utils.balances._account_balance") as account_balance:
            with self.assertRaisesRegex(ValueError, "does not match"):
                record_loan_interest_accrual(
                    loan_id=101,
                    member_id="M101",
                    accrual_date=date(2026, 7, 1),
                    approved_by="system",
                )

        account_balance.assert_not_called()

    def test_reversed_interest_accrual_reference_is_not_reported_as_posted(self):
        with patch("src.utils.balances.ensure_accounting_schema"), patch(
            "src.utils.balances.execute_query",
            side_effect=[
                [{"member_id": "M101", "status": "Active"}],
                [{"amount": 10.0, "is_reversed": True}],
            ],
        ):
            with self.assertRaisesRegex(DuplicateFinancialTransactionError, "was reversed"):
                record_loan_interest_accrual(
                    loan_id=101,
                    member_id="M101",
                    accrual_date=date(2026, 7, 1),
                    approved_by="system",
                )

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
                    "member_id": "M101",
                    "approved_by": "Treasurer",
                    "approved_date": None,
                    "applied_date": datetime(2023, 1, 1),
                    "last_interest_applied_at": None,
                    "last_payment_applied_at": None,
                }]
            if "UPDATE loans SET last_interest_applied_at" in query:
                updates.append(params)
            return []

        with patch("src.views.loans.execute_query", side_effect=fake_execute), patch(
            "src.views.loans.ensure_loan_interest_tracking_columns"
        ), patch("src.views.loans.record_loan_interest_accrual", return_value=100.0) as accrue:
            successful = update_interest_accumulation(datetime(2023, 2, 1))

        self.assertTrue(successful)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][0], date(2023, 2, 1))
        accrue.assert_called_once()

    def test_interest_update_reports_failure_if_any_loan_accrual_fails(self):
        def fake_execute(query, params=None, fetch=False):
            if fetch and "FROM loans" in query:
                return [{
                    "loan_id": 101,
                    "member_id": "M101",
                    "approved_by": "Treasurer",
                    "approved_date": datetime(2023, 1, 1),
                    "applied_date": datetime(2023, 1, 1),
                    "last_interest_applied_at": None,
                    "last_payment_applied_at": None,
                }]
            return []

        with patch("src.views.loans.execute_query", side_effect=fake_execute), patch(
            "src.views.loans.ensure_loan_interest_tracking_columns"
        ), patch(
            "src.views.loans.record_loan_interest_accrual",
            side_effect=RuntimeError("ledger unavailable"),
        ):
            successful = update_interest_accumulation(datetime(2023, 2, 1))

        self.assertFalse(successful)

    def test_approve_loan_triggers_first_interest_charge(self):
        with patch("src.views.loans.record_opening_loan") as post_disbursement, \
             patch("src.views.loans.record_audit_event"), \
             patch("src.views.loans.create_notification"), \
             patch("src.views.loans.update_interest_accumulation") as mock_update:
            result = approve_loan(101, "Treasurer")

        self.assertTrue(result)
        post_disbursement.assert_called_once()
        mock_update.assert_called_once()

    def test_months_between_counts_partial_months_for_daily_interest(self):
        self.assertAlmostEqual(months_between(datetime(2026, 5, 11), datetime(2026, 7, 14)), 2 + (3 / 31), places=4)

    def test_interest_applies_immediately_on_loan_issuance(self):
        start_date = datetime(2026, 5, 11, 9, 0)
        reference_date = datetime(2026, 5, 11, 9, 0)
        self.assertTrue(should_apply_interest_for_loan(start_date, reference_date, None, None))

    def test_first_due_date_grace_delays_second_interest_after_issuance(self):
        start_date = datetime(2026, 5, 11, 9, 0)
        last_interest_date = datetime(2026, 5, 11, 9, 0)
        reference_date_before_grace = datetime(2026, 6, 19, 9, 0)
        reference_date_after_grace = datetime(2026, 6, 21, 9, 0)
        self.assertFalse(should_apply_interest_for_loan(start_date, reference_date_before_grace, last_interest_date, None))
        self.assertTrue(should_apply_interest_for_loan(start_date, reference_date_after_grace, last_interest_date, None))

    def test_payment_after_due_before_grace_triggers_immediate_interest(self):
        start_date = datetime(2026, 5, 11, 9, 0)
        last_interest_date = datetime(2026, 5, 11, 9, 0)
        last_payment_date = datetime(2026, 6, 15, 9, 0)
        self.assertTrue(should_apply_interest_for_loan(start_date, last_payment_date, last_interest_date, last_payment_date))

    def test_payment_before_next_due_still_waits_until_grace_end(self):
        start_date = datetime(2026, 5, 11, 9, 0)
        last_interest_date = datetime(2026, 6, 20, 9, 0)
        last_payment_date = datetime(2026, 6, 25, 9, 0)
        self.assertFalse(should_apply_interest_for_loan(start_date, datetime(2026, 7, 19, 9, 0), last_interest_date, last_payment_date))
        self.assertFalse(should_apply_interest_for_loan(start_date, datetime(2026, 7, 20, 9, 0), last_interest_date, last_payment_date))
        self.assertFalse(should_apply_interest_for_loan(start_date, datetime(2026, 7, 21, 9, 0), last_interest_date, last_payment_date))

    def test_payment_during_grace_triggers_immediate_interest(self):
        start_date = datetime(2026, 5, 11, 9, 0)
        last_interest_date = datetime(2026, 6, 20, 9, 0)
        last_payment_date = datetime(2026, 7, 22, 9, 0)
        self.assertTrue(should_apply_interest_for_loan(start_date, datetime(2026, 7, 22, 9, 0), last_interest_date, last_payment_date))

    def test_get_loan_interest_schedule_reports_immediate_interest_and_grace_end_after_first_due_date(self):
        start_date = datetime(2026, 5, 11, 9, 0)
        next_due, grace_end = get_loan_interest_schedule(start_date, None, None, None)
        self.assertEqual(next_due, date(2026, 5, 11))
        self.assertEqual(grace_end, date(2026, 6, 20))

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
                accountant_reconciliation_reference="RECON-101",
            )

        self.assertTrue(created)
        self.assertEqual(insert_calls[0][1][0], "member-1")
        self.assertEqual(insert_calls[0][1][1], 5000.0)
        self.assertEqual(insert_calls[0][1][3], "Legacy repayment before launch")
        self.assertEqual(insert_calls[0][1][7], 250.0)
        mock_update.assert_not_called()

    @patch("src.views.home.get_subscription_totals", return_value={"total_paid": 0.0})
    def test_get_financial_metrics_cached_returns_zero_balance_when_no_active_loans(self, _):
        with patch("src.views.home.get_member_loan_outstanding_total", return_value=0.0), patch(
            "src.views.home.get_member_subscription_arrears", return_value=0.0
        ):
            get_financial_metrics_cached.clear()
            metrics = get_financial_metrics_cached("test_user")
            self.assertEqual(metrics["loan_balance"], 0.0)


if __name__ == "__main__":
    unittest.main()
