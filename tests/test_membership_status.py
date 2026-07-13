import unittest
from datetime import date

from src.utils.membership import get_membership_status_for_db, normalize_membership_status


class MembershipStatusTests(unittest.TestCase):
    def test_full_status_for_mature_member_with_savings(self):
        status = get_membership_status_for_db(date(2023, 1, 1), saving_balance=150000, arrears_balance=0)
        self.assertEqual(status, "Full Member")

    def test_probationary_status_for_approved_member_within_60_days(self):
        status = get_membership_status_for_db(date.today(), saving_balance=50000, arrears_balance=0)
        self.assertEqual(status, "Probationary")

    def test_inactive_status_for_high_arrears(self):
        status = get_membership_status_for_db(date(2023, 1, 1), saving_balance=150000, arrears_balance=40000)
        self.assertEqual(status, "Inactive")

    def test_partial_member_status_for_low_savings(self):
        status = get_membership_status_for_db(date(2023, 1, 1), saving_balance=50000, arrears_balance=0)
        self.assertEqual(status, "Partial Member")

    def test_normalizes_full_aliases_to_full_member(self):
        self.assertEqual(normalize_membership_status("Full"), "Full Member")
        self.assertEqual(normalize_membership_status("full member"), "Full Member")
        self.assertEqual(normalize_membership_status("full-member"), "Full Member")


if __name__ == "__main__":
    unittest.main()
