from __future__ import annotations

import logging
import threading
import time
from typing import Optional

from src.utils.reminders import run_reminder_engine

logger = logging.getLogger(__name__)

_worker_thread: Optional[threading.Thread] = None
_worker_started = False
_worker_lock = threading.Lock()
_worker_stop_event: Optional[threading.Event] = None


def _run_worker_loop(interval_minutes: int = 15, stop_event: Optional[threading.Event] = None) -> None:
    while not (stop_event is not None and stop_event.is_set()):
        try:
            run_reminder_engine()
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Reminder worker failed: %s", exc)
        if stop_event is not None and stop_event.is_set():
            break
        time.sleep(interval_minutes * 60)


def start_periodic_reminder_worker(interval_minutes: int = 15) -> bool:
    """Start a background worker that periodically runs the reminder engine."""
    global _worker_thread, _worker_started, _worker_stop_event
    with _worker_lock:
        if _worker_started and _worker_thread is not None and _worker_thread.is_alive():
            return False

        if _worker_stop_event is None or _worker_stop_event.is_set():
            _worker_stop_event = threading.Event()

        _worker_thread = threading.Thread(
            target=_run_worker_loop,
            args=(interval_minutes, _worker_stop_event),
            daemon=True,
            name="reminder-worker",
        )
        _worker_thread.start()
        _worker_started = True
        return True


def stop_periodic_reminder_worker() -> None:
    global _worker_thread, _worker_started, _worker_stop_event
    with _worker_lock:
        if _worker_stop_event is not None:
            _worker_stop_event.set()
        _worker_thread = None
        _worker_started = False
        _worker_stop_event = None
