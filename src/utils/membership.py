from datetime import date, datetime
from typing import Optional


def normalize_membership_status(status: Optional[str]) -> str:
    if status is None:
        return "Pending"

    normalized = str(status).strip().lower().replace("_", " ").replace("-", " ")
    if not normalized:
        return "Pending"

    if normalized in {"pending", "due", "open", "incomplete"}:
        return "Pending"

    if normalized in {"probational", "probationary"}:
        return "Probationary"

    if normalized in {"inactive"}:
        return "Inactive"

    if normalized in {"active"}:
        return "Active"

    if normalized in {"partial", "partial member", "partial members"}:
        return "Partial Member"

    if normalized in {
        "full",
        "full member",
        "full_member",
        "full-members",
        "full-member",
        "full members",
    }:
        return "Full Member"

    return str(status).strip().title() or "Pending"


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
    if join_date > today:
        return "Pending"

    days_since_join = (today - join_date).days
    saving_balance = float(saving_balance or 0)
    arrears_balance = float(arrears_balance or 0)

    if days_since_join < 60:
        return "Probationary"
    if arrears_balance >= 40000:
        return "Inactive"
    if saving_balance < 100000:
        return "Partial Member"
    return "Full Member"
