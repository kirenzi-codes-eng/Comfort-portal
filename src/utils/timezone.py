from datetime import date, datetime
from zoneinfo import ZoneInfo

UGANDA_TZ = ZoneInfo("Africa/Kampala")


def now_in_uganda() -> datetime:
    return datetime.now(UGANDA_TZ)


def today_in_uganda() -> date:
    return now_in_uganda().date()
