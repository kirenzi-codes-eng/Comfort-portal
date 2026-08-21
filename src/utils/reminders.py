from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from src.database.connection import execute_query
from src.utils.audit import record_audit_event
from src.utils.notifications import create_notification
from src.utils.schema_compat import has_optional_feature


REMINDER_WINDOW_DAYS = 7
REMINDER_FREQUENCY_DAYS = 7


def _get_existing_reminders(reference_key: str) -> list[dict]:
    try:
        rows = execute_query(
            """
            SELECT id, title, category, reference_key, created_at
            FROM notifications
            WHERE category = 'Reminder' AND reference_key = %s
            ORDER BY created_at DESC LIMIT 10;
            """,
            params=(reference_key,),
            fetch=True,
        )
        return rows or []
    except Exception:
        return []


def _should_skip_reminder(reference_key: str, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    rows = _get_existing_reminders(reference_key)
    if not rows:
        return False
    try:
        created_at = rows[0].get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        elif not isinstance(created_at, datetime):
            return False
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return (now - created_at).days < REMINDER_FREQUENCY_DAYS
    except Exception:
        return False


def _emit_reminder_notification(recipient_type: str, recipient_id: Optional[str], recipient_role: Optional[str], title: str, message: str, reference_key: str, category: str = "Reminder") -> None:
    if _should_skip_reminder(reference_key):
        return
    create_notification(
        recipient_type=recipient_type,
        recipient_id=recipient_id,
        recipient_role=recipient_role,
        title=title,
        message=message,
        category=category,
        module_name="Reminder Engine",
        related_record_id=recipient_id,
        priority="High",
    )
    record_audit_event(
        entity_type="reminder",
        entity_id=reference_key,
        action="generated",
        actor_name="Reminder Engine",
        actor_role=recipient_role or "System",
        details=message,
    )


def _generate_membership_reminders() -> int:
    try:
        rows = execute_query(
            """
            SELECT member_id, full_name, status, join_date
            FROM members
            WHERE COALESCE(status, 'Pending') = 'Pending'
            ORDER BY join_date NULLS LAST, full_name;
            """,
            params=None,
            fetch=True,
        ) or []
    except Exception:
        return 0

    generated = 0
    for row in rows:
        member_id = str(row.get("member_id") or "")
        full_name = str(row.get("full_name") or "Member")
        if not member_id:
            continue
        reference_key = f"membership_pending:{member_id}"
        _emit_reminder_notification(
            recipient_type="role",
            recipient_id="Secretary",
            recipient_role="Secretary",
            title="Pending registration review",
            message=f"{full_name} has a pending registration awaiting review.",
            reference_key=reference_key,
            category="Reminder",
        )
        generated += 1
    return generated


def _generate_subscription_reminders() -> int:
    try:
        rows = execute_query(
            """
            SELECT member_id, billing_month, amount_paid, status
            FROM subscriptions
            WHERE status IN ('Pending', 'Overdue') OR billing_month IS NOT NULL
            ORDER BY billing_month DESC NULLS LAST;
            """,
            params=None,
            fetch=True,
        ) or []
    except Exception:
        return 0

    generated = 0
    today = date.today()
    for row in rows:
        member_id = str(row.get("member_id") or "")
        billing_month = row.get("billing_month")
        if not member_id:
            continue
        try:
            if isinstance(billing_month, str):
                parsed_date = datetime.fromisoformat(billing_month.replace("Z", "+00:00")).date()
            elif isinstance(billing_month, datetime):
                parsed_date = billing_month.date()
            elif isinstance(billing_month, date):
                parsed_date = billing_month
            else:
                parsed_date = today
        except Exception:
            parsed_date = today
        due_delta = (parsed_date - today).days
        if due_delta in {0, 1, 3, 7}:
            reference_key = f"subscription_due:{member_id}:{parsed_date}"
            _emit_reminder_notification(
                recipient_type="member",
                recipient_id=member_id,
                recipient_role="Member",
                title="Subscription reminder",
                message=f"Your subscription for {parsed_date.strftime('%b %Y')} is due soon.",
                reference_key=reference_key,
                category="Reminder",
            )
            generated += 1
    return generated


def _generate_loan_reminders() -> int:
    if not has_optional_feature("loans", ["member_id", "loan_id", "status"]):
        return 0

    loan_due_column = None
    for candidate in ("repayment_due_date", "next_payment_date", "due_date", "payment_due_date"):
        if has_optional_feature("loans", ["member_id", "loan_id", "status", candidate]):
            loan_due_column = candidate
            break

    if loan_due_column is None:
        return 0

    try:
        rows = execute_query(
            f"""
            SELECT member_id, loan_id, status, {loan_due_column}
            FROM loans
            WHERE status IN ('Active', 'Approved')
            ORDER BY {loan_due_column} NULLS LAST;
            """,
            params=None,
            fetch=True,
        ) or []
    except Exception:
        return 0

    generated = 0
    today = date.today()
    for row in rows:
        member_id = str(row.get("member_id") or "")
        loan_id = str(row.get("loan_id") or "")
        due_date = row.get(loan_due_column)
        if not member_id or not due_date:
            continue
        try:
            if isinstance(due_date, str):
                parsed_date = datetime.fromisoformat(due_date.replace("Z", "+00:00")).date()
            elif isinstance(due_date, datetime):
                parsed_date = due_date.date()
            elif isinstance(due_date, date):
                parsed_date = due_date
            else:
                continue
        except Exception:
            continue
        if (parsed_date - today).days in {0, 1, 3, 7}:
            reference_key = f"loan_due:{member_id}:{loan_id}"
            _emit_reminder_notification(
                recipient_type="member",
                recipient_id=member_id,
                recipient_role="Member",
                title="Loan repayment reminder",
                message=f"Your loan repayment is due on {parsed_date.strftime('%d %b %Y')}.",
                reference_key=reference_key,
                category="Reminder",
            )
            generated += 1
    return generated


def _generate_meeting_reminders() -> int:
    if not has_optional_feature("meetings", ["id", "title", "meeting_date"]):
        return 0

    generated = 0
    today = date.today()
    try:
        rows = execute_query(
            """
            SELECT id, title, meeting_date
            FROM meetings
            WHERE meeting_date IS NOT NULL
            ORDER BY meeting_date;
            """,
            params=None,
            fetch=True,
        ) or []
    except Exception:
        return 0

    for row in rows:
        meeting_id = str(row.get("id") or "")
        title = str(row.get("title") or "Meeting")
        meeting_date = row.get("meeting_date")
        try:
            if isinstance(meeting_date, str):
                parsed_date = datetime.fromisoformat(meeting_date.replace("Z", "+00:00")).date()
            elif isinstance(meeting_date, datetime):
                parsed_date = meeting_date.date()
            elif isinstance(meeting_date, date):
                parsed_date = meeting_date
            else:
                continue
        except Exception:
            continue

        reminder_offsets = {0, 1, 3, 7}
        for offset in reminder_offsets:
            if (parsed_date - today).days == offset:
                reference_key = f"meeting:{meeting_id}:{offset}"
                _emit_reminder_notification(
                    recipient_type="role",
                    recipient_id="Secretary",
                    recipient_role="Secretary",
                    title="Meeting reminder",
                    message=f"{title} is scheduled for {parsed_date.strftime('%d %b %Y')}.",
                    reference_key=reference_key,
                    category="Reminder",
                )
                generated += 1
    return generated


def run_reminder_engine() -> dict[str, Any]:
    """Run the shared reminder engine and return counts for each reminder category."""
    results = {
        "membership": _generate_membership_reminders(),
        "subscriptions": _generate_subscription_reminders(),
        "loans": _generate_loan_reminders(),
        "meetings": _generate_meeting_reminders(),
    }
    return results
