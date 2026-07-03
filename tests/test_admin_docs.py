import unittest
from datetime import date

from src.views.admin_docs import build_member_profile_update


class BuildMemberProfileUpdateTests(unittest.TestCase):
    def test_builds_update_statement_with_join_date_and_notes(self):
        query, params = build_member_profile_update(
            "CBO-001",
            "Jane Doe",
            "jane@example.com",
            "0772000000",
            "Chairperson",
            "Active",
            "2024-01-15",
            "Backdated profile entry",
        )

        self.assertIn("UPDATE members", query)
        self.assertIn("join_date", query)
        self.assertIn("notes", query)
        self.assertEqual(params[-1], "CBO-001")
        self.assertEqual(params[5], date(2024, 1, 15))


if __name__ == "__main__":
    unittest.main()
