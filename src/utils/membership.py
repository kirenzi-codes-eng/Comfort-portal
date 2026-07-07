from datetime import date, datetime
from typing import Optional


def normalize_membership_status(status: Optional[str]) -> str:
    if status is None:
        return "Pending"

    normalized = str(status).strip().lower()
    if not normalized:
        return "Pending"

    aliases = {
        "full",
        "full member",
        "full_member",
        "full-members",
        "full-member",
        "full members",
    }
    if normalized in aliases:
        return "Full Member"

    if normalized in {"active", "partial"}:
        return "Active"

    if normalized in {"inactive", "probationary", "pending"}:
        return "Pending" if normalized in {"pending", "probationary"} else "Inactive"

    return str(status).strip() or "Pending"


def get_membership_status_for_db(join_date: Optional[date | str | datetime], saving_balance: float = 0, arrears_balance: float = 0) -> str:
    if join_date is None:
        return "Pending"

    if isinstance(join_date, str):
        clean_date = join_date.strip()
        if not clean_date:
            return "Pending"
        try:
            join_date = datetime.fromisoformat(clean_date.replace("Z", "+00:00"))
        except ValueError:
            try:
                join_date = datetime.strptime(clean_date, "%Y-%m-%d")
            except ValueError:
                return "Pending"

    if isinstance(join_date, datetime):
        join_date = join_date.date()

    if not isinstance(join_date, date):
        return "Pending"

    today = date.today()
    months = (today.year - join_date.year) * 12 + (today.month - join_date.month)

    saving_balance = float(saving_balance or 0)
    arrears_balance = float(arrears_balance or 0)

    if months <= 2:
        return "Pending"
    if arrears_balance >= 40000:
        return "Inactive"
    if saving_balance < 100000:
        return "Active"
    return "Full Member"
