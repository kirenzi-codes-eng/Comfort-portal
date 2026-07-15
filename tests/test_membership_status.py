import unittest
from datetime import date

from unittest.mock import patch

from src.utils.membership import get_membership_status_for_db, normalize_membership_status, sanitize_member_status_records


class MembershipStatusTests(unittest.TestCase):
    def test_full_status_for_mature_member_with_savings(self):
        status = get_membership_status_for_db(date(2023, 1, 1), saving_balance=150000, arrears_balance=0)
        self.assertEqual(status, "Full Member")

    def test_probationary_status_for_approved_member_within_60_days(self):
        status = get_membership_status_for_db(date.today(), saving_balance=50000, arrears_balance=0)
        self.assertEqual(status, "Probationary")

    def test_high_arrears_does_not_change_full_member_status(self):
        status = get_membership_status_for_db(date(2023, 1, 1), saving_balance=150000, arrears_balance=40000)
        self.assertEqual(status, "Full Member")

    def test_partial_member_status_for_low_savings(self):
        status = get_membership_status_for_db(date(2023, 1, 1), saving_balance=50000, arrears_balance=0)
        self.assertEqual(status, "Partial Member")

    def test_normalizes_full_aliases_to_full_member(self):
        self.assertEqual(normalize_membership_status("Full"), "Full Member")
        self.assertEqual(normalize_membership_status("full member"), "Full Member")
        self.assertEqual(normalize_membership_status("full-member"), "Full Member")

    def test_normalizes_inactive_to_pending(self):
        self.assertEqual(normalize_membership_status("Inactive"), "Pending")

    @patch("src.utils.membership.execute_query")
    def test_sanitize_member_status_records_updates_inactive_members(self, mock_execute):
        mock_execute.side_effect = [
            [{"member_id": "MEM-001", "join_date": date(2023, 1, 1)}],
            [{"total_paid": 150000.0, "pending_paid": 40000.0}],
            None,
        ]

        updated_count = sanitize_member_status_records()

        self.assertEqual(updated_count, 1)
        self.assertEqual(mock_execute.call_args_list[2][0][0], "UPDATE members SET status = %s WHERE member_id = %s;")
        self.assertEqual(mock_execute.call_args_list[2][1]["params"], ("Full Member", "MEM-001"))


if __name__ == "__main__":
    unittest.main()
