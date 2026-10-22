from datetime import date, datetime
from typing import Optional

from src.database.connection import execute_query


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
        return "Pending"

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
    if saving_balance < 100000:
        return "Partial Member"
    return "Full Member"


def sanitize_member_status_records() -> int:
    """Convert stored 'Inactive' member statuses to valid membership statuses."""
    from src.utils.balances import get_effective_member_balance, get_member_subscription_arrears

    rows = execute_query(
        "SELECT member_id, join_date FROM members WHERE lower(status) = 'inactive';",
        params=None,
        fetch=True,
    ) or []

    updated_count = 0
    for row in rows:
        member_id = row.get("member_id")
        join_date = row.get("join_date")

        saving_balance = get_effective_member_balance(str(member_id))
        arrears_balance = get_member_subscription_arrears(str(member_id), date.today())

        new_status = get_membership_status_for_db(join_date, saving_balance=saving_balance, arrears_balance=arrears_balance)
        if new_status and new_status != "Inactive":
            execute_query(
                "UPDATE members SET status = %s WHERE member_id = %s;",
                params=(new_status, member_id),
                fetch=False,
            )
            updated_count += 1

    return updated_count
