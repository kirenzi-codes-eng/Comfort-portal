import unittest
from unittest.mock import patch

from src.utils import reminder_scheduler


class ReminderSchedulerTests(unittest.TestCase):
    def test_start_periodic_reminder_worker_starts_once(self):
        reminder_scheduler._worker_started = False
        reminder_scheduler._worker_thread = None
        reminder_scheduler._worker_stop_event = None

        with patch("src.utils.reminder_scheduler.threading.Thread") as mock_thread:
            started = reminder_scheduler.start_periodic_reminder_worker(interval_minutes=5)

        self.assertTrue(started)
        mock_thread.assert_called_once()

    def test_start_periodic_reminder_worker_skips_duplicate_thread(self):
        reminder_scheduler._worker_started = True
        reminder_scheduler._worker_thread = object()
        reminder_scheduler._worker_stop_event = None

        with patch("src.utils.reminder_scheduler.threading.Thread") as mock_thread:
            started = reminder_scheduler.start_periodic_reminder_worker(interval_minutes=5)

        self.assertFalse(started)
        mock_thread.assert_not_called()


if __name__ == "__main__":
    unittest.main()
