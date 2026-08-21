from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from src.database.connection import execute_query
from src.utils.audit import record_audit_event


NOTIFICATION_PRIORITY_VALUES = {"Critical", "High", "Normal", "Low"}


def ensure_notification_table() -> None:
    """Ensure the shared notifications table exists with the fields needed by the engine."""
    try:
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                recipient_type TEXT NOT NULL,
                recipient_id TEXT,
                recipient_role TEXT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'System',
                module_name TEXT,
                related_record_id TEXT,
                priority TEXT NOT NULL DEFAULT 'Normal',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                read_at TIMESTAMP,
                delivered_at TIMESTAMP,
                is_read BOOLEAN DEFAULT FALSE,
                delivery_status TEXT DEFAULT 'Pending',
                action_link TEXT,
                expires_at TIMESTAMP
            );
            """,
            params=None,
            fetch=False,
        )
    except Exception:
        pass


def ensure_notification_preferences_table() -> None:
    """Ensure notification preference storage exists."""
    try:
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS notification_preferences (
                member_id TEXT PRIMARY KEY,
                push_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                email_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                sms_enabled BOOLEAN NOT NULL DEFAULT FALSE,
                reminders_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                broadcasts_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            params=None,
            fetch=False,
        )
    except Exception:
        pass


def ensure_notification_infrastructure() -> None:
    """Ensure the shared notification infrastructure exists."""
    ensure_notification_table()
    ensure_notification_preferences_table()


def create_notification(
    recipient_type: str,
    recipient_id: Optional[str],
    title: str,
    message: str,
    category: str = "System",
    module_name: Optional[str] = None,
    related_record_id: Optional[str] = None,
    priority: str = "Normal",
    recipient_role: Optional[str] = None,
    action_link: Optional[str] = None,
    expires_at: Optional[datetime] = None,
    delivery_status: str = "Pending",
) -> int | None:
    """Create a single notification record and return its id."""
    ensure_notification_table()
    try:
        result = execute_query(
            """
            INSERT INTO notifications (
                recipient_type,
                recipient_id,
                recipient_role,
                title,
                message,
                category,
                module_name,
                related_record_id,
                priority,
                created_at,
                is_read,
                delivery_status,
                action_link,
                expires_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id;
            """,
            params=(
                recipient_type,
                recipient_id,
                recipient_role,
                title,
                message,
                category,
                module_name,
                related_record_id,
                priority,
                datetime.now(timezone.utc),
                False,
                delivery_status,
                action_link,
                expires_at,
            ),
            fetch=True,
        )
        first_row = (result or [{}])[0] if result else None
        if first_row is None:
            return None
        raw_id = first_row.get("id")
        return int(raw_id) if raw_id is not None else None
    except Exception:
        return None


def get_member_notification_preferences(member_id: str) -> dict[str, Any]:
    """Return the persisted notification preference settings for a member."""
    ensure_notification_preferences_table()
    defaults = {
        "push_enabled": True,
        "email_enabled": False,
        "sms_enabled": False,
        "reminders_enabled": True,
        "broadcasts_enabled": True,
    }
    try:
        rows = execute_query(
            """
            SELECT push_enabled, email_enabled, sms_enabled, reminders_enabled, broadcasts_enabled
            FROM notification_preferences
            WHERE member_id = %s
            LIMIT 1;
            """,
            params=(member_id,),
            fetch=True,
        ) or []
        if rows:
            row = rows[0] or {}
            return {
                "push_enabled": bool(row.get("push_enabled")),
                "email_enabled": bool(row.get("email_enabled")),
                "sms_enabled": bool(row.get("sms_enabled")),
                "reminders_enabled": bool(row.get("reminders_enabled")),
                "broadcasts_enabled": bool(row.get("broadcasts_enabled")),
            }
    except Exception:
        pass
    return defaults


def update_member_notification_preferences(member_id: str, preferences: dict[str, Any]) -> bool:
    """Persist notification preference changes for a member."""
    if not member_id:
        return False

    ensure_notification_preferences_table()
    allowed_keys = {
        "push_enabled",
        "email_enabled",
        "sms_enabled",
        "reminders_enabled",
        "broadcasts_enabled",
    }
    normalized = {key: bool(preferences[key]) for key in allowed_keys if key in preferences}
    if not normalized:
        return False

    try:
        push_enabled = normalized.get("push_enabled", True)
        email_enabled = normalized.get("email_enabled", False)
        sms_enabled = normalized.get("sms_enabled", False)
        reminders_enabled = normalized.get("reminders_enabled", True)
        broadcasts_enabled = normalized.get("broadcasts_enabled", True)
        now = datetime.now(timezone.utc)
        execute_query(
            """
            INSERT INTO notification_preferences (
                member_id,
                push_enabled,
                email_enabled,
                sms_enabled,
                reminders_enabled,
                broadcasts_enabled,
                updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (member_id) DO UPDATE SET
                push_enabled = EXCLUDED.push_enabled,
                email_enabled = EXCLUDED.email_enabled,
                sms_enabled = EXCLUDED.sms_enabled,
                reminders_enabled = EXCLUDED.reminders_enabled,
                broadcasts_enabled = EXCLUDED.broadcasts_enabled,
                updated_at = EXCLUDED.updated_at;
            """,
            params=(
                member_id,
                push_enabled,
                email_enabled,
                sms_enabled,
                reminders_enabled,
                broadcasts_enabled,
                now,
            ),
            fetch=False,
        )
        return True
    except Exception:
        return False


def update_notification_delivery_status(notification_id: int, delivery_status: str) -> bool:
    """Track delivery state for an existing notification record."""
    if not notification_id:
        return False
    ensure_notification_table()
    try:
        execute_query(
            """
            UPDATE notifications
            SET delivery_status = %s,
                delivered_at = CASE WHEN %s = 'Delivered' THEN %s ELSE delivered_at END
            WHERE id = %s;
            """,
            params=(delivery_status, delivery_status, datetime.now(timezone.utc), notification_id),
            fetch=False,
        )
        return True
    except Exception:
        return False


def create_broadcast_notification(
    recipient_type: str,
    recipient_id: Optional[str],
    title: str,
    message: str,
    category: str = "Broadcast",
    module_name: Optional[str] = None,
    related_record_id: Optional[str] = None,
    priority: str = "Normal",
    recipient_role: Optional[str] = None,
    action_link: Optional[str] = None,
    expires_at: Optional[datetime] = None,
) -> int | None:
    """Create a broadcast notification and persist audit metadata."""
    notification_id = create_notification(
        recipient_type=recipient_type,
        recipient_id=recipient_id,
        title=title,
        message=message,
        category=category,
        module_name=module_name or "Notifications",
        related_record_id=related_record_id,
        priority=priority,
        recipient_role=recipient_role,
        action_link=action_link,
        expires_at=expires_at,
        delivery_status="Pending",
    )

    if notification_id is not None:
        record_audit_event(
            entity_type="notification_broadcast",
            entity_id=str(notification_id),
            action="broadcast_created",
            actor_name="System",
            actor_role=recipient_role or "System",
            details=f"Broadcast created for {recipient_type}:{recipient_id or 'all'}",
        )

    return notification_id


def get_unread_notification_count(recipient_type: str, recipient_id: Optional[str], recipient_role: Optional[str] = None) -> int:
    ensure_notification_table()
    try:
        rows = execute_query(
            """
            SELECT COUNT(*) AS unread_count
            FROM notifications
            WHERE is_read = FALSE
              AND (
                (recipient_type = 'all_members')
                OR (recipient_type = 'role' AND recipient_role = %s)
                OR (recipient_type = 'member' AND recipient_id = %s)
              );
            """,
            params=(recipient_role, recipient_id),
            fetch=True,
        )
        first_row = rows[0] if rows else None
        if first_row is None:
            return 0
        return int(first_row.get("unread_count") or 0)
    except Exception:
        return 0


def get_notifications_for_user(recipient_type: str, recipient_id: Optional[str], recipient_role: Optional[str] = None, limit: int = 50) -> list[dict]:
    ensure_notification_table()
    try:
        rows = execute_query(
            """
            SELECT id, recipient_type, recipient_id, recipient_role, title, message, category, module_name, related_record_id, priority, created_at, read_at, is_read, delivery_status, action_link, expires_at
            FROM notifications
            WHERE is_read = FALSE
              AND (
                (recipient_type = 'all_members')
                OR (recipient_type = 'role' AND recipient_role = %s)
                OR (recipient_type = 'member' AND recipient_id = %s)
              )
            ORDER BY created_at DESC, id DESC
            LIMIT %s;
            """,
            params=(recipient_role, recipient_id, limit),
            fetch=True,
        )
        return rows or []
    except Exception:
        return []


def mark_notification_read(notification_id: int) -> bool:
    ensure_notification_table()
    try:
        execute_query(
            "UPDATE notifications SET is_read = TRUE, read_at = %s WHERE id = %s;",
            params=(datetime.now(timezone.utc), notification_id),
            fetch=False,
        )
        return True
    except Exception:
        return False


def mark_all_notifications_read(recipient_type: str, recipient_id: Optional[str], recipient_role: Optional[str] = None) -> bool:
    ensure_notification_table()
    try:
        execute_query(
            """
            UPDATE notifications
            SET is_read = TRUE, read_at = %s
            WHERE (
                (recipient_type = 'all_members')
                OR (recipient_type = 'role' AND recipient_role = %s)
                OR (recipient_type = 'member' AND recipient_id = %s)
            );
            """,
            params=(datetime.now(timezone.utc), recipient_role, recipient_id),
            fetch=False,
        )
        return True
    except Exception:
        return False
