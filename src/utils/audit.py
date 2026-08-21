from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from src.database.connection import execute_query


def ensure_audit_log_table() -> None:
    """Create the shared audit log table if it does not exist."""
    try:
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id SERIAL PRIMARY KEY,
                entity_type TEXT NOT NULL,
                entity_id TEXT NOT NULL,
                action TEXT NOT NULL,
                actor_name TEXT,
                actor_role TEXT,
                details TEXT,
                previous_value TEXT,
                new_value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            params=None,
            fetch=False,
        )
    except Exception:
        pass


def _normalize_actor_name(actor_name: Optional[str], actor_role: Optional[str] = None) -> Optional[str]:
    if actor_name is None:
        return None
    cleaned = str(actor_name).strip()
    if not cleaned:
        return None
    if cleaned.lower() in {"member", "chairperson", "secretary", "treasurer", "vice chairperson", "welfare", "system", "admin"}:
        return None
    return cleaned


def record_audit_event(
    entity_type: str,
    entity_id: str,
    action: str,
    actor_name: Optional[str] = None,
    actor_role: Optional[str] = None,
    details: Optional[str] = None,
    previous_value: Optional[Any] = None,
    new_value: Optional[Any] = None,
) -> None:
    """Persist a generic audit event for later review in admin tools."""
    ensure_audit_log_table()
    try:
        normalized_actor_name = _normalize_actor_name(actor_name, actor_role)
        execute_query(
            """
            INSERT INTO audit_logs (
                entity_type,
                entity_id,
                action,
                actor_name,
                actor_role,
                details,
                previous_value,
                new_value
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
            """,
            params=(
                entity_type,
                entity_id,
                action,
                actor_name,
                actor_role,
                details,
                str(previous_value) if previous_value is not None else None,
                str(new_value) if new_value is not None else None,
            ),
            fetch=False,
        )
    except Exception:
        pass


def fetch_recent_audit_events(limit: int = 50) -> list[dict]:
    """Return the latest audit rows, ordered newest first."""
    ensure_audit_log_table()
    try:
        rows = execute_query(
            """
            SELECT entity_type, entity_id, action, actor_name, actor_role, details, previous_value, new_value, created_at
            FROM audit_logs
            ORDER BY created_at DESC, id DESC
            LIMIT %s;
            """,
            params=(limit,),
            fetch=True,
        )
        return rows or []
    except Exception:
        return []


def _coerce_date(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def build_audit_dashboard_summary(limit: int = 200) -> dict[str, int]:
    """Create executive summary values from the existing audit log repository."""
    rows = fetch_recent_audit_events(limit=limit)
    if not rows:
        return {
            "today_activities": 0,
            "total_audit_records": 0,
            "new_member_registrations": 0,
            "pending_approvals": 0,
            "loans_approved_today": 0,
            "savings_transactions": 0,
            "subscription_payments": 0,
            "welfare_transactions": 0,
            "failed_login_attempts": 0,
            "suspended_accounts": 0,
            "critical_actions": 0,
            "system_errors": 0,
        }

    today = datetime.now(timezone.utc).date()
    summary = {
        "today_activities": 0,
        "total_audit_records": len(rows),
        "new_member_registrations": 0,
        "pending_approvals": 0,
        "loans_approved_today": 0,
        "savings_transactions": 0,
        "subscription_payments": 0,
        "welfare_transactions": 0,
        "failed_login_attempts": 0,
        "suspended_accounts": 0,
        "critical_actions": 0,
        "system_errors": 0,
    }

    for row in rows:
        created_at = _coerce_date(row.get("created_at"))
        if created_at and created_at.astimezone(timezone.utc).date() == today:
            summary["today_activities"] += 1

        action = str(row.get("action") or "").lower()
        entity_type = str(row.get("entity_type") or "").lower()
        details = str(row.get("details") or "").lower()

        if "register" in action or "registration" in action:
            summary["new_member_registrations"] += 1
        if "approve" in action and "loan" in entity_type:
            summary["loans_approved_today"] += 1
        if entity_type in {"savings", "saving"} or "savings" in action:
            summary["savings_transactions"] += 1
        if entity_type in {"subscription", "subscriptions"} or "payment" in action and "subscription" in details:
            summary["subscription_payments"] += 1
        if entity_type in {"welfare", "support"} or "welfare" in action:
            summary["welfare_transactions"] += 1
        if "login failed" in action or "failed login" in action or "login failure" in action:
            summary["failed_login_attempts"] += 1
        if "suspend" in action or "suspended" in details:
            summary["suspended_accounts"] += 1
        if "critical" in action or "critical" in details or "error" in action or "error" in details:
            summary["critical_actions"] += 1
        if "error" in action or "error" in details or "failed" in action and "login" not in action:
            summary["system_errors"] += 1

    return summary


def _looks_like_test_audit_row(row: dict[str, Any]) -> bool:
    """Return True for obvious test/demo rows that should not be shown in the dashboard."""
    if not row:
        return False
    details = str(row.get("details") or "").lower()
    actor_name = str(row.get("actor_name") or "").lower()
    actor_role = str(row.get("actor_role") or "").lower()
    action = str(row.get("action") or "").lower()
    if any(token in details for token in ["test", "demo", "sample"]):
        return True
    if any(token in actor_name for token in ["test", "demo", "sample"]):
        return True
    if any(token in actor_role for token in ["test", "demo", "sample"]):
        return True
    if any(token in action for token in ["test", "demo", "sample"]):
        return True
    return False


def fetch_enriched_audit_events(limit: int = 100) -> list[dict]:
    """Return audit rows with lightweight enrichment for the executive dashboard."""
    rows = fetch_recent_audit_events(limit=limit)
    if not rows:
        return []

    rows = [row for row in rows if not _looks_like_test_audit_row(row)]
    if not rows:
        return []

    member_lookup: dict[str, dict] = {}
    for row in rows:
        entity_id = str(row.get("entity_id") or "").strip()
        if not entity_id or entity_id in member_lookup:
            continue
        try:
            member_rows = execute_query(
                """
                SELECT member_id, full_name, status, role
                FROM members
                WHERE member_id = %s
                LIMIT 1;
                """,
                params=(entity_id,),
                fetch=True,
            )
        except Exception:
            member_rows = []
        if member_rows:
            member_lookup[entity_id] = member_rows[0]

    enriched: list[dict] = []
    for row in rows:
        entity_id = str(row.get("entity_id") or "").strip()
        member_data = member_lookup.get(entity_id, {})
        action = str(row.get("action") or "").strip()
        details = str(row.get("details") or "").strip()
        previous_value = str(row.get("previous_value") or "").strip() if row.get("previous_value") is not None else ""
        new_value = str(row.get("new_value") or "").strip() if row.get("new_value") is not None else ""

        enriched.append({
            **row,
            "member_name": str(member_data.get("full_name") or "").strip() or "—",
            "member_number": str(member_data.get("member_id") or entity_id or "—"),
            "role": str(row.get("actor_role") or member_data.get("role") or "").strip() or "System",
            "status": _summarize_audit_status(action, details, previous_value, new_value),
            "remarks": details or action,
            "previous_state": previous_value or "—",
            "current_state": new_value or "—",
        })

    return enriched


def _summarize_audit_status(action: str, details: str, previous_value: str, new_value: str) -> str:
    action_lower = action.lower()
    details_lower = details.lower()
    if "approve" in action_lower or "approved" in action_lower or "approved" in details_lower:
        return "Approved"
    if "reject" in action_lower or "rejected" in action_lower or "rejected" in details_lower:
        return "Rejected"
    if "suspend" in action_lower or "suspended" in action_lower or "suspended" in details_lower:
        return "Suspended"
    if "terminate" in action_lower or "terminated" in action_lower:
        return "Terminated"
    if "failed" in action_lower or "failed" in details_lower:
        return "Failed"
    if previous_value and new_value and previous_value != new_value:
        return "Updated"
    return "Recorded"
