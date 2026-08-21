import unittest
from unittest.mock import patch

from src.utils import audit


class AuditTrailTests(unittest.TestCase):
    def test_fetch_recent_audit_events_returns_latest_rows(self):
        rows = [{"entity_type": "member", "entity_id": "CBO-001", "action": "status_updated"}]

        with patch("src.utils.audit.execute_query", return_value=rows):
            result = audit.fetch_recent_audit_events(limit=5)

        self.assertEqual(result, rows)

    def test_record_audit_event_creates_table_and_inserts_entry(self):
        calls = []

        def fake_execute_query(query, params=None, fetch=False):
            calls.append((query, params, fetch))
            return None

        with patch("src.utils.audit.execute_query", side_effect=fake_execute_query):
            audit.record_audit_event(
                entity_type="member",
                entity_id="CBO-001",
                action="status_updated",
                actor_name="Admin",
                actor_role="Secretary",
                details="Member promoted",
            )

        self.assertGreaterEqual(len(calls), 2)
        create_call = next(call for call in calls if "CREATE TABLE IF NOT EXISTS audit_logs" in call[0])
        self.assertIsNotNone(create_call)
        insert_call = next(call for call in calls if "INSERT INTO audit_logs" in call[0])
        self.assertEqual(insert_call[1][0], "member")
        self.assertEqual(insert_call[1][1], "CBO-001")


if __name__ == "__main__":
    unittest.main()
