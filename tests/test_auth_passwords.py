import unittest
from unittest.mock import patch

import bcrypt

from src.components.auth import check_password, request_password_reset, reset_member_password_by_admin


class CheckPasswordTests(unittest.TestCase):
    def test_accepts_plaintext_legacy_passwords(self):
        self.assertTrue(check_password("secret123", "secret123"))

    def test_rejects_wrong_plaintext_passwords(self):
        self.assertFalse(check_password("wrong", "secret123"))

    def test_accepts_bcrypt_hashes_stored_as_bytes_literal_strings(self):
        hashed = bcrypt.hashpw(b"secret123", bcrypt.gensalt())
        self.assertTrue(check_password("secret123", str(hashed)))

    def test_accepts_hex_encoded_bcrypt_hashes(self):
        hashed = bcrypt.hashpw(b"secret123", bcrypt.gensalt())
        self.assertTrue(check_password("secret123", hashed.hex()))

    @patch("src.components.auth.create_notification", side_effect=[42, 43])
    @patch("src.components.auth.find_member_by_identifier")
    def test_password_recovery_notifies_secretary_for_known_member(self, find_member, create_notification):
        find_member.return_value = {"member_id": "CBO-001", "full_name": "Test User"}

        self.assertTrue(request_password_reset(" test@example.com "))
        find_member.assert_called_once_with("test@example.com")
        self.assertEqual(create_notification.call_count, 2)
        self.assertEqual(
            [call.kwargs["recipient_role"] for call in create_notification.call_args_list],
            ["Secretary", "Chairperson"],
        )
        self.assertEqual(create_notification.call_args_list[1].kwargs["related_record_id"], "CBO-001")

    @patch("src.components.auth.create_notification")
    @patch("src.components.auth.find_member_by_identifier", return_value=None)
    def test_password_recovery_does_not_notify_for_unknown_member(self, find_member, create_notification):
        self.assertFalse(request_password_reset("unknown@example.com"))
        find_member.assert_called_once_with("unknown@example.com")
        create_notification.assert_not_called()

    def test_password_reset_rejects_unauthorized_role(self):
        success, message = reset_member_password_by_admin("CBO-001", "temporary123", "MEM-002", "Treasurer")

        self.assertFalse(success)
        self.assertIn("Secretary or Chairperson", message)

    @patch("src.components.auth.create_notification")
    @patch("src.components.auth.record_audit_event")
    @patch("src.components.auth.execute_query")
    @patch("src.components.auth.find_member_by_identifier")
    def test_password_reset_updates_hash_and_notifies_member(
        self, find_member, execute_query, record_audit_event, create_notification
    ):
        find_member.return_value = {"member_id": "CBO-001", "full_name": "Test User", "role": "Member"}

        success, message = reset_member_password_by_admin("CBO-001", "temporary123", "CBO-999", "Chairperson")

        self.assertTrue(success)
        self.assertIn("reset successfully", message)
        update_call = next(call for call in execute_query.call_args_list if "UPDATE members" in call.args[0])
        self.assertEqual(update_call.kwargs["params"][1], "CBO-001")
        self.assertTrue(check_password("temporary123", update_call.kwargs["params"][0]))
        record_audit_event.assert_called_once()
        create_notification.assert_called_once()


if __name__ == "__main__":
    unittest.main()
