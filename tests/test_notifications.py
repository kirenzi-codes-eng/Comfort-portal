import unittest
from unittest.mock import patch

from src.utils import notifications


class NotificationEngineTests(unittest.TestCase):
    def test_create_notification_inserts_row(self):
        calls = []

        def fake_execute_query(query, params=None, fetch=False):
            calls.append((query, params, fetch))
            if "RETURNING id" in query:
                return [{"id": 7}]
            return None

        with patch("src.utils.notifications.execute_query", side_effect=fake_execute_query):
            notification_id = notifications.create_notification(
                recipient_type="member",
                recipient_id="MEM-001",
                title="Welcome",
                message="Your account is ready",
                category="System",
                module_name="Auth",
            )

        self.assertEqual(notification_id, 7)
        self.assertTrue(any("INSERT INTO notifications" in query for query, _, _ in calls))

    def test_push_device_registration_helpers_are_removed(self):
        self.assertFalse(hasattr(notifications, "register_push_device_token"))
        self.assertFalse(hasattr(notifications, "get_push_device_tokens"))
        self.assertFalse(hasattr(notifications, "ensure_push_device_table"))

    def test_update_member_notification_preferences_uses_internal_preferences(self):
        calls = []

        def fake_execute_query(query, params=None, fetch=False):
            calls.append((query, params, fetch))
            return None

        with patch("src.utils.notifications.execute_query", side_effect=fake_execute_query):
            result = notifications.update_member_notification_preferences(
                member_id="MEM-001",
                preferences={
                    "push_enabled": False,
                    "email_enabled": True,
                    "sms_enabled": False,
                    "reminders_enabled": True,
                    "broadcasts_enabled": False,
                },
            )

        self.assertTrue(result)
        self.assertTrue(any("INSERT INTO notification_preferences" in query for query, _, _ in calls))
        self.assertTrue(any("ON CONFLICT (member_id) DO UPDATE SET" in query for query, _, _ in calls))

    def test_create_broadcast_notification_records_audit(self):
        notification_calls = []

        def fake_create_notification(**kwargs):
            notification_calls.append(kwargs)
            return 10

        with patch("src.utils.notifications.create_notification", side_effect=fake_create_notification), \
             patch("src.utils.notifications.record_audit_event") as fake_audit:
            notification_id = notifications.create_broadcast_notification(
                recipient_type="all_members",
                recipient_id=None,
                title="System Update",
                message="A maintenance window is scheduled.",
                recipient_role="Member",
            )

        self.assertEqual(notification_id, 10)
        self.assertTrue(notification_calls)
        fake_audit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
