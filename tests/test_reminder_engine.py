import unittest
from unittest.mock import patch

from src.utils import reminders


class ReminderEngineTests(unittest.TestCase):
    def test_membership_pending_registrations_generate_notification(self):
        calls = []

        def fake_execute_query(query, params=None, fetch=False):
            if "FROM notifications" in query and "WHERE" in query:
                return []
            if "FROM members" in query and "status" in query.lower():
                return [{"member_id": "MEM-100", "full_name": "Jane Doe", "status": "Pending", "join_date": None}]
            calls.append((query, params, fetch))
            return None

        with patch("src.utils.reminders.execute_query", side_effect=fake_execute_query), \
             patch("src.utils.reminders.create_notification") as create_notification, \
             patch("src.utils.reminders.record_audit_event") as record_audit_event:
            reminders._generate_membership_reminders()

        self.assertTrue(create_notification.called)
        self.assertTrue(record_audit_event.called)


if __name__ == "__main__":
    unittest.main()
