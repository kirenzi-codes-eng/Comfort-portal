from src.utils.reminder_scheduler import start_periodic_reminder_worker


if __name__ == "__main__":
    start_periodic_reminder_worker(interval_minutes=15)
    while True:
        import time

        time.sleep(60)
