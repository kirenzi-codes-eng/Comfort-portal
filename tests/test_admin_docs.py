import unittest
from datetime import date
from unittest.mock import patch

from src.views import admin_docs
from src.views.admin_docs import build_member_profile_update


class BuildMemberProfileUpdateTests(unittest.TestCase):
    def test_build_changed_profile_update_payload_uses_only_modified_fields(self):
        original = {
            "full_name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "0772000000",
            "role": "Member",
            "status": "Active",
            "join_date": date(2024, 1, 15),
            "notes": "Original note",
        }
        submitted = {
            "full_name": "Jane Doe",
            "email": "jane.updated@example.com",
            "phone": "0772000000",
            "role": "Member",
            "status": "Active",
            "join_date": date(2024, 1, 15),
            "notes": "   ",
        }

        payload = admin_docs._build_changed_profile_update_payload(original, submitted)

        self.assertEqual(payload["full_name"], None)
        self.assertEqual(payload["email"], "jane.updated@example.com")
        self.assertEqual(payload["phone"], None)
        self.assertEqual(payload["notes"], None)

    def test_rerun_page_uses_streamlit_rerun_when_available(self):
        with patch.object(admin_docs.st, "rerun", create=True) as rerun_mock, patch.object(admin_docs.st, "experimental_rerun", create=True) as experimental_rerun_mock:
            admin_docs._rerun_page()
            rerun_mock.assert_called_once_with()
            experimental_rerun_mock.assert_not_called()

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
