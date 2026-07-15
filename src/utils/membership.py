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
    rows = execute_query(
        "SELECT member_id, join_date FROM members WHERE lower(status) = 'inactive';",
        params=None,
        fetch=True,
    ) or []

    updated_count = 0
    for row in rows:
        member_id = row.get("member_id")
        join_date = row.get("join_date")

        metrics_rows = execute_query(
            "SELECT COALESCE(SUM(amount_paid),0) AS total_paid, COALESCE(SUM(CASE WHEN status = 'Pending' THEN amount_paid ELSE 0 END),0) AS pending_paid FROM subscriptions WHERE member_id = %s;",
            params=(member_id,),
            fetch=True,
        ) or [{"total_paid": 0, "pending_paid": 0}]

        metrics = metrics_rows[0] if metrics_rows else {"total_paid": 0, "pending_paid": 0}
        saving_balance = float(metrics.get("total_paid") or 0)
        arrears_balance = float(metrics.get("pending_paid") or 0)

        new_status = get_membership_status_for_db(join_date, saving_balance=saving_balance, arrears_balance=arrears_balance)
        if new_status and new_status != "Inactive":
            execute_query(
                "UPDATE members SET status = %s WHERE member_id = %s;",
                params=(new_status, member_id),
                fetch=False,
            )
            updated_count += 1

    return updated_count
