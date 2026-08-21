import io
import logging
import os
import re
from datetime import date, datetime
from html import escape
from typing import Any, Optional

import pandas as pd
import streamlit as st

from src.database.connection import execute_query, get_conn_from_pool
from src.utils.audit import record_audit_event
from src.utils.notifications import create_notification
from src.utils.balances import (
    ensure_member_balance_adjustments_table,
    get_member_welfare_reserve_balance,
)
from src.utils.error_handler import execute_with_error_handling, get_error_display_message
from src.views.subscriptions import upload_subscription_proof_to_cloudinary
from src.utils.timezone import today_in_uganda

logger = logging.getLogger(__name__)

# ===== OPTIMIZATION: Initialization tracking =====
WELFARE_TABLES_INITIALIZED = "welfare_tables_initialized"
WELFARE_CATEGORIES_INITIALIZED = "welfare_categories_initialized"

WELFARE_REQUEST_STATUS_SUBMITTED = "Submitted"
WELFARE_REQUEST_STATUS_WELFARE_REVIEW = "Pending Welfare Officer Review"
WELFARE_REQUEST_STATUS_WELFARE_APPROVED = "Approved by Welfare Officer"
WELFARE_REQUEST_STATUS_CHAIR_REVIEW = "Pending Chairperson Approval"
WELFARE_REQUEST_STATUS_CHAIR_APPROVED = "Approved by Chairperson"
WELFARE_REQUEST_STATUS_TREASURER_PAYMENT = "Pending Treasurer Payment"
WELFARE_REQUEST_STATUS_PAID = "Paid"
WELFARE_REQUEST_STATUS_REJECTED = "Rejected"
WELFARE_REQUEST_STATUS_CANCELLED = "Cancelled"
WELFARE_REQUEST_STATUS_RETURNED_FOR_REVIEW = "Returned for Review"
WELFARE_REQUEST_STATUS_APPROVED_BY_WELFARE = WELFARE_REQUEST_STATUS_WELFARE_APPROVED
WELFARE_REQUEST_STATUS_APPROVED_BY_CHAIR = WELFARE_REQUEST_STATUS_CHAIR_APPROVED
WELFARE_REQUEST_STATUS_PENDING_WELFARE_REVIEW = WELFARE_REQUEST_STATUS_WELFARE_REVIEW
WELFARE_REQUEST_STATUS_PENDING_CHAIR_APPROVAL = WELFARE_REQUEST_STATUS_CHAIR_REVIEW
WELFARE_REQUEST_STATUS_PENDING_TREASURER_PAYMENT = WELFARE_REQUEST_STATUS_TREASURER_PAYMENT

WELFARE_STAFF_ROLES = {"Welfare", "Chairperson", "Treasurer", "Secretary", "Vice Chairperson"}
WELFARE_PAYMENT_AMOUNT = 20000.0


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            return int(text)
        except ValueError:
            return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _get_member_row_value(member: Any, field_name: str, fallback_index: int, default: Any = None) -> Any:
    if member is None:
        return default
    if isinstance(member, dict):
        if field_name in member:
            return member.get(field_name, default)
    elif hasattr(member, "get"):
        try:
            return member.get(field_name, default)
        except Exception:
            pass
    if isinstance(member, (list, tuple)) and 0 <= fallback_index < len(member):
        return member[fallback_index]
    return default


def _is_welfare_contribution_eligible(status: Optional[object]) -> bool:
    normalized = str(status or "").strip().lower()
    if not normalized:
        return True
    return normalized not in {"probationary", "probation", "probation member"}


def _should_suspend_for_zero_balance(current_balance: float, deduction_amount: float) -> bool:
    return float(current_balance or 0.0) < float(deduction_amount or 0.0) and float(deduction_amount or 0.0) > 0.0


def _is_suspended_membership_status(status: Optional[object]) -> bool:
    normalized = str(status or "").strip().lower().replace("_", " ").replace("-", " ")
    return normalized in {"suspended", "suspension", "suspend", "disabled"}


def _get_member_welfare_account_status(member_id: Optional[str]) -> str:
    if not member_id:
        return "Active"
    try:
        rows = execute_query(
            "SELECT status FROM member_welfare_accounts WHERE member_id = %s LIMIT 1;",
            params=(member_id,),
            fetch=True,
        ) or []
    except Exception:
        return "Active"
    if not rows:
        return "Active"
    return str((rows[0] or {}).get("status") or "Active")


def _ensure_member_welfare_account(member_id: Optional[str], member_name: Optional[str] = None) -> None:
    if not member_id:
        return
    try:
        execute_query(
            """
            INSERT INTO member_welfare_accounts (member_id, member_name, balance, created_at)
            VALUES (%s, %s, 0, CURRENT_TIMESTAMP)
            ON CONFLICT (member_id) DO NOTHING;
            """,
            params=(member_id, member_name or ""),
            fetch=False,
        )
    except Exception:
        pass


def _normalize_welfare_account_status(status: Optional[object]) -> str:
    normalized = str(status or "").strip().lower().replace("_", " ").replace("-", " ")
    if not normalized:
        return "Active"
    if normalized in {"active", "active account", "enabled", "unsuspend", "unsuspended"}:
        return "Active"
    if normalized in {"suspended", "suspension", "suspend", "disabled"}:
        return "Suspended"
    return str(status or "Active").strip().title() or "Active"


def set_member_welfare_account_status(member_id: Optional[str], new_status: Optional[str], performed_by: str, actor_role: str, reason: Optional[str] = None) -> bool:
    if not member_id:
        return False
    target_status = _normalize_welfare_account_status(new_status)
    try:
        _ensure_welfare_tables()
    except Exception:
        pass
    try:
        execute_query(
            "ALTER TABLE member_welfare_accounts ADD COLUMN IF NOT EXISTS status TEXT DEFAULT 'Active';",
            params=None,
            fetch=False,
        )
        execute_query(
            "ALTER TABLE member_welfare_accounts ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMP;",
            params=None,
            fetch=False,
        )
        execute_query(
            "ALTER TABLE member_welfare_accounts ADD COLUMN IF NOT EXISTS suspension_reason TEXT;",
            params=None,
            fetch=False,
        )
    except Exception:
        pass

    _ensure_member_welfare_account(member_id)
    current_rows = execute_query(
        "SELECT status FROM member_welfare_accounts WHERE member_id = %s LIMIT 1;",
        params=(member_id,),
        fetch=True,
    ) or []
    previous_status = str((current_rows[0] or {}).get("status") or "Unknown") if current_rows else "Unknown"

    execute_query(
        """
        UPDATE member_welfare_accounts
        SET status = %s,
            updated_at = CURRENT_TIMESTAMP,
            suspended_at = CASE WHEN %s = 'Suspended' THEN CURRENT_TIMESTAMP ELSE NULL END,
            suspension_reason = CASE WHEN %s = 'Suspended' THEN COALESCE(%s, 'Manual enforcement') ELSE NULL END
        WHERE member_id = %s;
        """,
        params=(target_status, target_status, target_status, reason, member_id),
        fetch=False,
    )

    record_audit_event(
        entity_type="welfare_account",
        entity_id=member_id,
        action="welfare_account_status_updated",
        actor_name=performed_by,
        actor_role=actor_role,
        details=reason or f"Welfare account status updated to {target_status}",
        previous_value=previous_status,
        new_value=target_status,
    )
    _create_notification(
        "member",
        member_id,
        "Welfare account status updated",
        f"Your welfare account status was updated to {target_status}.",
        None,
    )
    _create_notification(
        "role",
        actor_role,
        "Welfare account enforcement",
        f"{performed_by} ({actor_role}) updated the welfare account status to {target_status}.",
        None,
    )
    try:
        st.cache_data.clear()
    except Exception:
        pass
    return True


def _ensure_welfare_tables() -> None:
    """OPTIMIZATION: Only execute once per session, tracked via session_state."""
    if st.session_state.get(WELFARE_TABLES_INITIALIZED):
        return
    try:
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS member_welfare_accounts (
                id SERIAL PRIMARY KEY,
                member_id TEXT UNIQUE NOT NULL,
                member_name TEXT,
                balance NUMERIC(12,2) NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            params=None,
            fetch=False,
        )
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS welfare_categories (
                id SERIAL PRIMARY KEY,
                category_name TEXT UNIQUE NOT NULL,
                category_type TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                created_by TEXT
            );
            """,
            params=None,
            fetch=False,
        )
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS welfare_requests (
                id SERIAL PRIMARY KEY,
                case_number TEXT UNIQUE NOT NULL,
                member_id TEXT NOT NULL,
                member_name TEXT NOT NULL,
                email TEXT,
                phone TEXT,
                membership_status TEXT,
                join_date DATE,
                request_date DATE,
                support_category TEXT NOT NULL,
                relationship TEXT,
                event_date DATE,
                location TEXT,
                description TEXT,
                evidence_file_url TEXT,
                evidence_public_id TEXT,
                evidence_name TEXT,
                status TEXT DEFAULT 'Submitted',
                current_stage TEXT,
                welfare_officer_comment TEXT,
                chairperson_comment TEXT,
                treasurer_comment TEXT,
                internal_notes TEXT,
                approved_by_welfare_officer TEXT,
                approved_by_chairperson TEXT,
                paid_by TEXT,
                payment_reference TEXT,
                payment_date TIMESTAMP,
                payment_amount NUMERIC(12, 2) DEFAULT 20000,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            params=None,
            fetch=False,
        )
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS welfare_messages (
                id SERIAL PRIMARY KEY,
                request_id INTEGER NOT NULL,
                member_id TEXT NOT NULL,
                member_name TEXT NOT NULL,
                message TEXT NOT NULL,
                moderation_status TEXT DEFAULT 'Approved',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            params=None,
            fetch=False,
        )
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                recipient_type TEXT NOT NULL,
                recipient_id TEXT,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                related_request_id INTEGER,
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            params=None,
            fetch=False,
        )
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS welfare_audit_log (
                id SERIAL PRIMARY KEY,
                request_id INTEGER NOT NULL,
                user_id TEXT,
                user_name TEXT,
                role TEXT,
                action TEXT NOT NULL,
                previous_status TEXT,
                new_status TEXT,
                details TEXT,
                payment_reference TEXT,
                ip_address TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            params=None,
            fetch=False,
        )
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS welfare_payments (
                id SERIAL PRIMARY KEY,
                request_id INTEGER NOT NULL,
                payment_reference TEXT UNIQUE NOT NULL,
                amount NUMERIC(12, 2) NOT NULL,
                payment_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                treasurer_id TEXT,
                treasurer_name TEXT,
                receipt_text TEXT,
                status TEXT DEFAULT 'Completed',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            params=None,
            fetch=False,
        )
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS ledger_transactions (
                id SERIAL PRIMARY KEY,
                member_id TEXT NOT NULL,
                member_name TEXT,
                transaction_type TEXT NOT NULL,
                amount NUMERIC(12, 2) NOT NULL,
                related_request_id INTEGER,
                description TEXT,
                reference TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """,
            params=None,
            fetch=False,
        )

        execute_query(
            "ALTER TABLE welfare_requests ADD COLUMN IF NOT EXISTS uploaded_by TEXT;",
            params=None,
            fetch=False,
        )
        execute_query(
            "ALTER TABLE welfare_requests ADD COLUMN IF NOT EXISTS uploaded_at TIMESTAMP;",
            params=None,
            fetch=False,
        )
        execute_query(
            "ALTER TABLE welfare_payments ADD COLUMN IF NOT EXISTS receipt_number TEXT;",
            params=None,
            fetch=False,
        )
        execute_query(
            "ALTER TABLE welfare_payments ADD COLUMN IF NOT EXISTS transaction_id TEXT;",
            params=None,
            fetch=False,
        )
        execute_query(
            "ALTER TABLE welfare_payments ADD COLUMN IF NOT EXISTS payment_timestamp TIMESTAMP;",
            params=None,
            fetch=False,
        )
        st.session_state[WELFARE_TABLES_INITIALIZED] = True
    except Exception:
        pass


def _requires_evidence(support_category: Optional[str]) -> bool:
    category_value = (support_category or "").strip().upper()
    return any(token in category_value for token in ["BEREAVEMENT", "ILLNESS"])


def _build_welfare_timeline_steps(request: Optional[dict]) -> list[dict]:
    return [
        {"status": WELFARE_REQUEST_STATUS_SUBMITTED, "label": "Submitted", "description": "Request received and awaiting review."},
        {"status": WELFARE_REQUEST_STATUS_PENDING_WELFARE_REVIEW, "label": "Pending Welfare Officer Review", "description": "Welfare review in progress."},
        {"status": WELFARE_REQUEST_STATUS_APPROVED_BY_WELFARE, "label": "Approved by Welfare Officer", "description": "Forwarded to the Chairperson."},
        {"status": WELFARE_REQUEST_STATUS_PENDING_CHAIR_APPROVAL, "label": "Pending Chairperson Approval", "description": "Chairperson review in progress."},
        {"status": WELFARE_REQUEST_STATUS_APPROVED_BY_CHAIR, "label": "Approved by Chairperson", "description": "Ready for payment processing."},
        {"status": WELFARE_REQUEST_STATUS_PENDING_TREASURER_PAYMENT, "label": "Pending Treasurer Payment", "description": "Treasurer is processing the payout."},
        {"status": WELFARE_REQUEST_STATUS_PAID, "label": "Paid", "description": "Payment completed and acknowledged."},
    ]


def can_transition_request(current_status: Optional[str], new_status: Optional[str], actor_role: Optional[str]) -> bool:
    current_status = current_status or ""
    new_status = new_status or ""
    role = (actor_role or "").strip()

    if role == "Welfare":
        return current_status in {WELFARE_REQUEST_STATUS_SUBMITTED, WELFARE_REQUEST_STATUS_PENDING_WELFARE_REVIEW, WELFARE_REQUEST_STATUS_RETURNED_FOR_REVIEW} and new_status in {
            WELFARE_REQUEST_STATUS_PENDING_WELFARE_REVIEW,
            WELFARE_REQUEST_STATUS_APPROVED_BY_WELFARE,
            WELFARE_REQUEST_STATUS_REJECTED,
            WELFARE_REQUEST_STATUS_RETURNED_FOR_REVIEW,
        }

    if role == "Chairperson":
        return current_status in {WELFARE_REQUEST_STATUS_APPROVED_BY_WELFARE, WELFARE_REQUEST_STATUS_PENDING_CHAIR_APPROVAL, WELFARE_REQUEST_STATUS_RETURNED_FOR_REVIEW} and new_status in {
            WELFARE_REQUEST_STATUS_PENDING_CHAIR_APPROVAL,
            WELFARE_REQUEST_STATUS_APPROVED_BY_CHAIR,
            WELFARE_REQUEST_STATUS_REJECTED,
            WELFARE_REQUEST_STATUS_RETURNED_FOR_REVIEW,
        }

    if role == "Treasurer":
        return current_status in {WELFARE_REQUEST_STATUS_APPROVED_BY_CHAIR, WELFARE_REQUEST_STATUS_PENDING_TREASURER_PAYMENT} and new_status in {
            WELFARE_REQUEST_STATUS_PENDING_TREASURER_PAYMENT,
            WELFARE_REQUEST_STATUS_PAID,
            WELFARE_REQUEST_STATUS_REJECTED,
        }

    return False


def validate_welfare_request_payload(
    membership_status: Optional[str],
    support_category: Optional[str],
    relationship: Optional[str],
    event_date: Optional[Any],
    location: Optional[str],
    description: Optional[str],
    uploaded_file: Optional[Any] = None,
    member_id: Optional[str] = None,
) -> list[str]:
    errors: list[str] = []

    if str(membership_status or "").strip() != "Full Member":
        errors.append("Only Full Members can submit a welfare request.")

    if not str(support_category or "").strip():
        errors.append("Please select a support category.")

    if not str(relationship or "").strip():
        errors.append("Please provide the relationship to the affected person.")

    if not event_date:
        errors.append("Please select the event date.")

    if not str(location or "").strip():
        errors.append("Please provide the event location.")

    if not str(description or "").strip():
        errors.append("Please add a description for the request so it can be reviewed properly.")

    if _requires_evidence(support_category) and uploaded_file is None:
        errors.append("Supporting evidence is required for bereavement or illness requests.")

    duplicate_error = _get_duplicate_welfare_error(
        member_id=member_id,
        support_category=support_category,
        relationship=relationship,
        event_date=event_date,
    )
    if duplicate_error:
        errors.append(duplicate_error)

    return errors


def _get_duplicate_welfare_error(
    member_id: Optional[str],
    support_category: Optional[str],
    relationship: Optional[str],
    event_date: Optional[Any],
) -> Optional[str]:
    if not member_id or not support_category or not relationship or not event_date:
        return None

    rows = execute_query(
        """
        SELECT id, case_number, status FROM welfare_requests
        WHERE member_id = %s
          AND LOWER(COALESCE(support_category, '')) = LOWER(%s)
          AND LOWER(COALESCE(relationship, '')) = LOWER(%s)
          AND event_date = %s
          AND status NOT IN ('Rejected', 'Cancelled', 'Paid')
        ORDER BY created_at DESC
        LIMIT 1;
        """,
        params=(member_id, str(support_category).strip(), str(relationship).strip(), event_date),
        fetch=True,
    ) or []
    if not rows:
        return None
    row = rows[0]
    return (
        f"A similar welfare request is already in progress ({row.get('case_number')}). "
        "Please review the existing request before submitting a duplicate."
    )


def _map_welfare_payload_errors(errors: list[str]) -> dict[str, list[str]]:
    field_errors: dict[str, list[str]] = {}
    for error in errors:
        if "Only Full Members can submit a welfare request." in error:
            field_errors.setdefault("membership_status", []).append(error)
        elif "Please select a support category." in error:
            field_errors.setdefault("support_category", []).append(error)
        elif "Please provide the relationship" in error:
            field_errors.setdefault("relationship", []).append(error)
        elif "Please select the event date." in error:
            field_errors.setdefault("event_date", []).append(error)
        elif "Please provide the event location." in error:
            field_errors.setdefault("location", []).append(error)
        elif "Please add a description" in error:
            field_errors.setdefault("description", []).append(error)
        elif "Supporting evidence is required" in error:
            field_errors.setdefault("evidence_file", []).append(error)
        else:
            field_errors.setdefault("form", []).append(error)
    return field_errors


def _build_announcement_content(request: dict, new_status: str, actor_name: str, note: Optional[str] = None) -> str:
    category = str(request.get("support_category") or "General Welfare")
    member_name = str(request.get("member_name") or "a member")
    case_number = str(request.get("case_number") or "")
    status_label = new_status
    note_text = f" {note}" if note else ""

    if "BEREAVEMENT" in category.upper():
        base_message = f"A bereavement welfare request is now {status_label.lower()}."
    else:
        base_message = f"A welfare request for {member_name} is now {status_label.lower()}."

    if note_text.strip():
        return f"{base_message}{note_text}"
    return f"{base_message} Please check the latest update for details."


def _upsert_welfare_announcement(request: dict, new_status: str, actor_name: str, note: Optional[str] = None) -> None:
    if not request:
        return
    case_number = str(request.get("case_number") or "")
    if not case_number:
        return
    title = f"Welfare Update: {case_number}"
    content = _build_announcement_content(request, new_status, actor_name, note)
    try:
        existing = execute_query(
            "SELECT id FROM announcements WHERE title = %s OR content LIKE %s LIMIT 1;",
            params=(title, f"%{case_number}%"),
            fetch=True,
        ) or []
        if existing:
            execute_query(
                "UPDATE announcements SET title = %s, content = %s, posted_by = %s, created_at = %s WHERE id = %s;",
                params=(title, content, actor_name, datetime.utcnow(), existing[0].get("id")),
                fetch=False,
            )
        else:
            execute_query(
                "INSERT INTO announcements (title, content, posted_by, created_at) VALUES (%s, %s, %s, %s);",
                params=(title, content, actor_name, datetime.utcnow()),
                fetch=False,
            )
    except Exception as exc:
        logger.exception("Unable to update welfare announcement: %s", exc)


def _notify_welfare_status_change(request: dict, new_status: str, actor_name: str, actor_role: str, note: Optional[str] = None) -> None:
    if not request:
        return
    request_id_value = request.get("id")
    request_id = _safe_int(request_id_value) if request_id_value is not None else None
    case_number = _safe_str(request.get("case_number"))
    member_id = _safe_str(request.get("member_id"))
    member_name = _safe_str(request.get("member_name"))

    _create_notification(
        "member",
        member_id,
        f"Welfare request updated: {new_status}",
        f"Your request {case_number} is now {new_status}. {note or ''}".strip(),
        request_id,
    )

    recipients = ["Welfare", "Chairperson", "Treasurer", "Secretary", "Vice Chairperson"]
    for recipient in recipients:
        _create_notification(
            "role",
            recipient,
            f"Welfare {new_status}",
            f"{actor_name} ({actor_role}) updated request {case_number} to {new_status} for {member_name}.",
            request_id,
        )


def _seed_default_categories() -> None:
    """OPTIMIZATION: Only execute once per session."""
    if st.session_state.get(WELFARE_CATEGORIES_INITIALIZED):
        return
    default_categories = [
        ("BEREAVEMENT - Spouse", "Bereavement"),
        ("BEREAVEMENT - Child", "Bereavement"),
        ("BEREAVEMENT - Father", "Bereavement"),
        ("BEREAVEMENT - Mother", "Bereavement"),
        ("BEREAVEMENT - Father-in-law", "Bereavement"),
        ("BEREAVEMENT - Mother-in-law", "Bereavement"),
        ("ILLNESS - Spouse", "Illness"),
        ("ILLNESS - Child", "Illness"),
        ("ILLNESS - Member", "Illness"),
        ("CELEBRATION - Traditional Marriage", "Celebration"),
        ("CELEBRATION - Wedding", "Celebration"),
    ]
    for category_name, category_type in default_categories:
        try:
            execute_query(
                "INSERT INTO welfare_categories (category_name, category_type, is_active, created_by) VALUES (%s, %s, TRUE, %s) ON CONFLICT (category_name) DO NOTHING;",
                params=(category_name, category_type, "system"),
                fetch=False,
            )
        except Exception:
            continue
    st.session_state[WELFARE_CATEGORIES_INITIALIZED] = True


@st.cache_data(ttl=3600)
def _get_welfare_categories() -> list[dict]:
    """OPTIMIZATION: Cache categories for 1 hour (they rarely change)."""
    _ensure_welfare_tables()
    _seed_default_categories()
    rows = execute_query(
        "SELECT id, category_name, category_type FROM welfare_categories WHERE is_active = TRUE ORDER BY category_name;",
        params=None,
        fetch=True,
    ) or []
    return rows


def _add_welfare_category(category_name: str, created_by: str) -> bool:
    if not category_name or not category_name.strip():
        return False
    try:
        execute_query(
            "INSERT INTO welfare_categories (category_name, category_type, is_active, created_by) VALUES (%s, %s, TRUE, %s) ON CONFLICT (category_name) DO NOTHING;",
            params=(category_name.strip(), "Custom", created_by),
            fetch=False,
        )
        # Invalidate cache on new category
        st.cache_data.clear()
        return True
    except Exception:
        return False


def _get_current_member_context(member_id: Optional[str]) -> dict:
    """OPTIMIZATION: Use session_state to cache member context across reruns."""
    if not member_id:
        return {}
    cache_key = f"member_context_{member_id}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    rows = execute_query(
        "SELECT member_id, full_name, email, phone, role, status, join_date FROM members WHERE member_id = %s LIMIT 1;",
        params=(member_id,),
        fetch=True,
    ) or []
    result = rows[0] if rows else {}
    st.session_state[cache_key] = result
    return result


@st.cache_data(ttl=300, show_spinner=False)
def get_member_paid_welfare_details(member_id: Optional[str]) -> dict:
    """Return the latest paid welfare request and its contribution breakdown for a member."""
    _ensure_welfare_tables()
    if not member_id:
        return {
            "amount_paid": 0.0,
            "payment_reference": None,
            "payment_date": None,
            "contributions": [],
        }

    request_rows = execute_query(
        """
        SELECT id, case_number, payment_amount, payment_reference, payment_date
        FROM welfare_requests
        WHERE member_id = %s AND status = 'Paid' AND payment_reference IS NOT NULL
        ORDER BY payment_date DESC NULLS LAST, created_at DESC
        LIMIT 1;
        """,
        params=(member_id,),
        fetch=True,
    ) or []

    request_row = request_rows[0] if request_rows else {}
    contribution_rows = execute_query(
        """
        SELECT member_id, member_name, amount AS contribution_amount
        FROM ledger_transactions
        WHERE related_request_id = %s AND transaction_type = 'Welfare Contribution'
        ORDER BY member_name;
        """,
        params=(request_row.get("id"),),
        fetch=True,
    ) or []

    return {
        "amount_paid": float(request_row.get("payment_amount") or 0.0),
        "payment_reference": request_row.get("payment_reference"),
        "payment_date": request_row.get("payment_date"),
        "contributions": [
            {
                "member_id": row.get("member_id"),
                "member_name": row.get("member_name") or "Unknown",
                "contribution_amount": float(row.get("contribution_amount") or 0.0),
            }
            for row in contribution_rows
        ],
    }


def get_member_welfare_summary(member_id: Optional[str]) -> dict:
    """OPTIMIZATION: Combine 5 separate queries into 1 optimized query + session caching."""
    _ensure_welfare_tables()
    if not member_id:
        return {
            "welfare_balance": 0.0,
            "total_contributions": 0.0,
            "cases_requested": 0,
            "cases_received": 0,
            "status": "No request",
            "last_contribution_date": None,
        }

    cache_key = f"welfare_summary_{member_id}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]

    rows = execute_query(
        """
        SELECT
            COUNT(DISTINCT wr1.id) AS cases_requested,
            COUNT(DISTINCT CASE WHEN wr2.status = 'Paid' THEN wr2.id ELSE NULL END) AS cases_received,
            (SELECT status FROM welfare_requests WHERE member_id = %s ORDER BY created_at DESC LIMIT 1) AS latest_status
        FROM welfare_requests wr1
        LEFT JOIN welfare_requests wr2 ON wr2.member_id = %s AND wr2.status = 'Paid'
        WHERE wr1.member_id = %s;
        """,
        params=(member_id, member_id, member_id),
        fetch=True,
    ) or []

    row = rows[0] if rows else {}
    welfare_balance = get_member_welfare_reserve_balance(member_id)

    result = {
        "welfare_balance": round(welfare_balance, 2),
        "total_contributions": round(welfare_balance, 2),
        "cases_requested": int(row.get("cases_requested") or 0),
        "cases_received": int(row.get("cases_received") or 0),
        "status": row.get("latest_status") or "No request",
        "last_contribution_date": None,
    }
    st.session_state[cache_key] = result
    return result


@st.cache_data(ttl=300)
def get_welfare_leader_metrics() -> dict:
    """OPTIMIZATION: Cache metrics for 5 minutes."""
    _ensure_welfare_tables()
    stats = _get_welfare_report_stats()
    monthly_rows = execute_query(
        "SELECT TO_CHAR(created_at, 'YYYY-MM') AS month_key, COUNT(*) AS total FROM welfare_requests GROUP BY TO_CHAR(created_at, 'YYYY-MM') ORDER BY month_key DESC LIMIT 12;",
        params=None,
        fetch=True,
    ) or []
    return {
        "pending_requests": int(stats.get("open_cases") or 0),
        "approved_requests": int(stats.get("approved") or 0),
        "rejected_requests": int(stats.get("rejected") or 0),
        "paid_requests": int(stats.get("paid") or 0),
        "outstanding_requests": int(stats.get("outstanding") or 0),
        "monthly_stats": monthly_rows,
    }


def get_unread_notification_count(user_role: Optional[str] = None, user_id: Optional[str] = None) -> int:
    """OPTIMIZATION: Cache notification count in session state."""
    if not user_id and not user_role:
        return 0
    cache_key = f"notification_count_{user_id}_{user_role}"
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    role_value = (user_role or "").strip()
    user_value = (user_id or "").strip()
    rows = execute_query(
        "SELECT COUNT(*) AS unread_count FROM notifications WHERE is_read = FALSE AND ((recipient_type = 'member' AND recipient_id = %s) OR (recipient_type = 'role' AND recipient_id = %s) OR recipient_type = 'all_members');",
        params=(user_value, role_value),
        fetch=True,
    ) or []
    result = int((rows[0] or {}).get("unread_count") or 0)
    st.session_state[cache_key] = result
    return result


def _is_full_member(member_context: dict) -> bool:
    status_value = str(member_context.get("status") or "").strip()
    return status_value == "Full Member"


def _build_case_number() -> str:
    current_year = today_in_uganda().year
    rows = execute_query(
        "SELECT COUNT(*) AS total_requests FROM welfare_requests WHERE case_number LIKE %s;",
        params=(f"WEL-{current_year}-%",),
        fetch=True,
    ) or []
    count = int((rows[0] or {}).get("total_requests", 0) or 0) + 1
    return f"WEL-{current_year}-{count:04d}"


def _log_welfare_action(request_id: int, user_id: str, user_name: str, role: str, action: str, previous_status: Optional[str], new_status: Optional[str], details: Optional[str] = None, payment_reference: Optional[str] = None) -> None:
    try:
        execute_query(
            """
            INSERT INTO welfare_audit_log (request_id, user_id, user_name, role, action, previous_status, new_status, details, payment_reference)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);
            """,
            params=(request_id, user_id, user_name, role, action, previous_status, new_status, details, payment_reference),
            fetch=False,
        )
        record_audit_event(
            entity_type="welfare_request",
            entity_id=str(request_id),
            action=action,
            actor_name=user_name,
            actor_role=role,
            details=details,
            previous_value=previous_status,
            new_value=new_status,
        )
        if user_name and request_id:
            create_notification(
                recipient_type="member",
                recipient_id=str(request_id),
                recipient_role="Member",
                title="Welfare request updated",
                message=details or f"Your welfare request moved to {new_status}.",
                category="Welfare",
                module_name="Welfare",
                related_record_id=str(request_id),
                priority="High",
            )
    except Exception:
        pass


def _create_notification(recipient_type: str, recipient_id: Optional[str], title: str, message: str, related_request_id: Optional[int] = None) -> None:
    try:
        execute_query(
            """
            INSERT INTO notifications (recipient_type, recipient_id, title, message, related_request_id)
            VALUES (%s, %s, %s, %s, %s);
            """,
            params=(recipient_type, recipient_id, title, message, related_request_id),
            fetch=False,
        )
    except Exception:
        pass


def _publish_announcement(title: str, content: str, posted_by: str = "System") -> None:
    try:
        execute_query(
            "INSERT INTO announcements (title, content, posted_by, created_at) VALUES (%s, %s, %s, %s);",
            params=(title, content, posted_by, datetime.utcnow()),
            fetch=False,
        )
    except Exception:
        pass


def _get_welfare_requests_for_role(user_role: str, member_id: Optional[str]) -> list[dict]:
    """OPTIMIZATION: Filter in SQL WHERE clause instead of Python loops."""
    _ensure_welfare_tables()
    if user_role in {"Welfare", "Chairperson", "Treasurer", "Secretary", "Vice Chairperson"}:
        if user_role == "Chairperson":
            rows = execute_query(
                """
                SELECT id, case_number, member_id, member_name, email, phone, membership_status, join_date, request_date, support_category,
                       relationship, event_date, location, description, evidence_file_url, evidence_public_id, evidence_name,
                       status, current_stage, welfare_officer_comment, chairperson_comment, treasurer_comment, internal_notes,
                       approved_by_welfare_officer, approved_by_chairperson, paid_by, payment_reference, payment_date, payment_amount,
                       is_active, created_at, updated_at, uploaded_by, uploaded_at
                FROM welfare_requests
                WHERE status IN (%s, %s, %s)
                ORDER BY created_at DESC;
                """,
                params=(WELFARE_REQUEST_STATUS_APPROVED_BY_WELFARE, WELFARE_REQUEST_STATUS_PENDING_CHAIR_APPROVAL, WELFARE_REQUEST_STATUS_RETURNED_FOR_REVIEW),
                fetch=True,
            ) or []
            return rows
        elif user_role == "Treasurer":
            rows = execute_query(
                """
                SELECT id, case_number, member_id, member_name, email, phone, membership_status, join_date, request_date, support_category,
                       relationship, event_date, location, description, evidence_file_url, evidence_public_id, evidence_name,
                       status, current_stage, welfare_officer_comment, chairperson_comment, treasurer_comment, internal_notes,
                       approved_by_welfare_officer, approved_by_chairperson, paid_by, payment_reference, payment_date, payment_amount,
                       is_active, created_at, updated_at, uploaded_by, uploaded_at
                FROM welfare_requests
                WHERE status IN (%s, %s, %s)
                ORDER BY created_at DESC;
                """,
                params=(WELFARE_REQUEST_STATUS_APPROVED_BY_CHAIR, WELFARE_REQUEST_STATUS_PENDING_TREASURER_PAYMENT, WELFARE_REQUEST_STATUS_PAID),
                fetch=True,
            ) or []
            return rows
        rows = execute_query(
            """
            SELECT id, case_number, member_id, member_name, email, phone, membership_status, join_date, request_date, support_category,
                   relationship, event_date, location, description, evidence_file_url, evidence_public_id, evidence_name,
                   status, current_stage, welfare_officer_comment, chairperson_comment, treasurer_comment, internal_notes,
                   approved_by_welfare_officer, approved_by_chairperson, paid_by, payment_reference, payment_date, payment_amount,
                   is_active, created_at, updated_at, uploaded_by, uploaded_at
            FROM welfare_requests
            ORDER BY created_at DESC;
            """,
            params=None,
            fetch=True,
        ) or []
        return rows
    rows = execute_query(
        """
        SELECT id, case_number, member_id, member_name, email, phone, membership_status, join_date, request_date, support_category,
               relationship, event_date, location, description, evidence_file_url, evidence_public_id, evidence_name,
               status, current_stage, welfare_officer_comment, chairperson_comment, treasurer_comment, internal_notes,
               approved_by_welfare_officer, approved_by_chairperson, paid_by, payment_reference, payment_date, payment_amount,
               is_active, created_at, updated_at, uploaded_by, uploaded_at
        FROM welfare_requests
        WHERE member_id = %s
        ORDER BY created_at DESC;
        """,
        params=(member_id,),
        fetch=True,
    ) or []
    return rows


def _get_welfare_request_by_id(request_id: int) -> Optional[dict]:
    rows = execute_query(
        """
        SELECT id, case_number, member_id, member_name, email, phone, membership_status, join_date, request_date, support_category,
               relationship, event_date, location, description, evidence_file_url, evidence_public_id, evidence_name,
               status, current_stage, welfare_officer_comment, chairperson_comment, treasurer_comment, internal_notes,
               approved_by_welfare_officer, approved_by_chairperson, paid_by, payment_reference, payment_date, payment_amount,
               is_active, created_at, updated_at, uploaded_by, uploaded_at
        FROM welfare_requests
        WHERE id = %s
        LIMIT 1;
        """,
        params=(request_id,),
        fetch=True,
    ) or []
    return rows[0] if rows else None


def _add_welfare_request_comment(request_id: int, member_id: str, member_name: str, message: str) -> None:
    if not message or not message.strip():
        return
    try:
        execute_query(
            "INSERT INTO welfare_messages (request_id, member_id, member_name, message) VALUES (%s, %s, %s, %s);",
            params=(request_id, member_id, member_name, message.strip()),
            fetch=False,
        )
    except Exception:
        pass


def _get_welfare_messages(request_id: int) -> list[dict]:
    rows = execute_query(
        "SELECT id, member_id, member_name, message, moderation_status, created_at FROM welfare_messages WHERE request_id = %s AND COALESCE(moderation_status, 'Approved') != 'Removed' ORDER BY created_at ASC;",
        params=(request_id,),
        fetch=True,
    ) or []
    return rows


def _get_request_audit_logs(request_id: int) -> list[dict]:
    rows = execute_query(
        "SELECT user_name, role, action, previous_status, new_status, details, payment_reference, created_at FROM welfare_audit_log WHERE request_id = %s ORDER BY created_at DESC;",
        params=(request_id,),
        fetch=True,
    ) or []
    return rows


def _get_related_announcements(request: Optional[dict]) -> list[dict]:
    if not request:
        return []
    case_number = str(request.get("case_number") or "")
    if not case_number:
        return []
    rows = execute_query(
        "SELECT id, title, content, posted_by, created_at FROM announcements WHERE title ILIKE %s OR content ILIKE %s ORDER BY created_at DESC LIMIT 8;",
        params=(f"%{case_number}%", f"%{case_number}%"),
        fetch=True,
    ) or []
    return rows


def _toggle_message_visibility(message_id: int, is_removed: bool) -> bool:
    try:
        execute_query(
            "UPDATE welfare_messages SET moderation_status = %s WHERE id = %s;",
            params=("Removed" if is_removed else "Approved", message_id),
            fetch=False,
        )
        return True
    except Exception:
        return False


@st.cache_data(ttl=300)
def _get_welfare_report_stats() -> dict:
    """OPTIMIZATION: Cache stats for 5 minutes."""
    rows = execute_query(
        """
        SELECT
            COUNT(*) FILTER (WHERE status IN ('Submitted', 'Pending Welfare Officer Review', 'Approved by Welfare Officer', 'Pending Chairperson Approval', 'Approved by Chairperson', 'Pending Treasurer Payment')) AS open_cases,
            COUNT(*) FILTER (WHERE status IN ('Paid', 'Rejected', 'Cancelled')) AS closed_cases,
            COUNT(*) FILTER (WHERE status IN ('Approved by Welfare Officer', 'Pending Chairperson Approval', 'Approved by Chairperson', 'Pending Treasurer Payment', 'Paid')) AS approved,
            COUNT(*) FILTER (WHERE status = 'Rejected') AS rejected,
            COUNT(*) FILTER (WHERE status = 'Paid') AS paid,
            COUNT(*) FILTER (WHERE status IN ('Pending Welfare Officer Review', 'Pending Chairperson Approval', 'Pending Treasurer Payment')) AS outstanding,
            COALESCE(SUM(payment_amount) FILTER (WHERE status = 'Paid'), 0) AS total_paid
        FROM welfare_requests;
        """,
        params=None,
        fetch=True,
    ) or []
    return rows[0] if rows else {}


@st.cache_data(ttl=300)
def _get_category_breakdown() -> list[dict]:
    """OPTIMIZATION: Cache breakdown data for 5 minutes."""
    rows = execute_query(
        "SELECT support_category AS category_name, COUNT(*) AS total FROM welfare_requests GROUP BY support_category ORDER BY total DESC;",
        params=None,
        fetch=True,
    ) or []
    return rows


@st.cache_data(ttl=300)
def _get_monthly_breakdown() -> list[dict]:
    """OPTIMIZATION: Cache breakdown data for 5 minutes."""
    rows = execute_query(
        "SELECT TO_CHAR(created_at, 'YYYY-MM') AS month_key, COUNT(*) AS total FROM welfare_requests GROUP BY TO_CHAR(created_at, 'YYYY-MM') ORDER BY month_key DESC;",
        params=None,
        fetch=True,
    ) or []
    return rows


@st.cache_data(ttl=300)
def _get_yearly_breakdown() -> list[dict]:
    """OPTIMIZATION: Cache breakdown data for 5 minutes."""
    rows = execute_query(
        "SELECT EXTRACT(YEAR FROM created_at) AS year_key, COUNT(*) AS total FROM welfare_requests GROUP BY EXTRACT(YEAR FROM created_at) ORDER BY year_key DESC;",
        params=None,
        fetch=True,
    ) or []
    return rows


def create_welfare_request(member_id: str, member_name: str, email: str, phone: str, membership_status: str, join_date, request_date, support_category: str, relationship: str, event_date, location: str, description: str, uploaded_file=None) -> Optional[dict]:
    _ensure_welfare_tables()
    errors = validate_welfare_request_payload(
        membership_status=membership_status,
        support_category=support_category,
        relationship=relationship,
        event_date=event_date,
        location=location,
        description=description,
        uploaded_file=uploaded_file,
        member_id=member_id,
    )
    if errors:
        logger.warning("Blocked welfare request for %s: %s", member_id, errors)
        return None

    case_number = _build_case_number()
    evidence_file_url = None
    evidence_public_id = None
    evidence_name = None

    if uploaded_file is not None:
        try:
            success, url, public_id = upload_subscription_proof_to_cloudinary(uploaded_file, member_id)
            if success and url and public_id:
                evidence_file_url = url
                evidence_public_id = public_id
                evidence_name = getattr(uploaded_file, "name", "") or "evidence"
        except Exception as exc:
            logger.warning("Unable to upload welfare evidence for %s: %s", member_id, exc)

    uploaded_by = member_name or member_id or "Member"
    uploaded_at = datetime.utcnow()
    params = (
        case_number,
        member_id,
        member_name,
        email,
        phone,
        membership_status,
        join_date,
        request_date,
        support_category,
        relationship,
        event_date,
        location,
        description,
        evidence_file_url,
        evidence_public_id,
        evidence_name,
        WELFARE_REQUEST_STATUS_SUBMITTED,
        WELFARE_REQUEST_STATUS_PENDING_WELFARE_REVIEW,
        uploaded_by,
        uploaded_at,
    )
    try:
        execute_query(
            """
            INSERT INTO welfare_requests (
                case_number, member_id, member_name, email, phone, membership_status, join_date, request_date, support_category,
                relationship, event_date, location, description, evidence_file_url, evidence_public_id, evidence_name,
                status, current_stage, uploaded_by, uploaded_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """,
            params=params,
            fetch=False,
        )
    except Exception as exc:
        logger.exception("Unable to create welfare request: %s", exc)
        return None

    request_row = None
    try:
        rows = execute_query(
            "SELECT id, case_number, member_id, member_name, support_category, status, current_stage FROM welfare_requests WHERE member_id = %s ORDER BY created_at DESC LIMIT 1;",
            params=(member_id,),
            fetch=True,
        ) or []
        if rows:
            request_row = rows[0]
    except Exception:
        request_row = None

    if request_row is not None:
        request_id = _safe_int(request_row.get("id"))
        _log_welfare_action(request_id, member_id, member_name, "Member", "Submitted", None, WELFARE_REQUEST_STATUS_SUBMITTED, "New welfare request submitted")
        _create_notification(
            "member",
            member_id,
            "Welfare support request submitted",
            f"Your request {request_row.get('case_number')} is now awaiting review.",
            request_id,
        )
        _notify_welfare_status_change(request_row, WELFARE_REQUEST_STATUS_PENDING_WELFARE_REVIEW, member_name, "Member", "Request submitted")
    # OPTIMIZATION: Invalidate caches when new request is created
    st.cache_data.clear()
    return request_row


def update_welfare_request_status(request_id: int, new_status: str, actor_id: str, actor_name: str, actor_role: str, note: Optional[str] = None, comment_field: Optional[str] = None) -> bool:
    request = _get_welfare_request_by_id(request_id)
    if not request:
        return False

    previous_status = request.get("status")
    if not can_transition_request(previous_status, new_status, actor_role):
        return False

    try:
        current_stage = new_status
        update_sql = "UPDATE welfare_requests SET status = %s, current_stage = %s, updated_at = %s"
        params: list[object] = [new_status, current_stage, datetime.utcnow()]
        if comment_field == "welfare":
            update_sql += ", welfare_officer_comment = %s"
            params.append(note)
        elif comment_field == "chair":
            update_sql += ", chairperson_comment = %s"
            params.append(note)
        elif comment_field == "treasurer":
            update_sql += ", treasurer_comment = %s"
            params.append(note)
        elif comment_field == "internal":
            update_sql += ", internal_notes = COALESCE(internal_notes, '') || %s"
            params.append((note or "") + "\n")
        if actor_role == "Welfare":
            update_sql += ", approved_by_welfare_officer = %s"
            params.append(actor_name)
        if actor_role == "Chairperson":
            update_sql += ", approved_by_chairperson = %s"
            params.append(actor_name)
        update_sql += " WHERE id = %s;"
        params.append(request_id)
        execute_query(update_sql, params=params, fetch=False)
        _log_welfare_action(int(request_id), actor_id, actor_name, actor_role, "Status updated", previous_status, new_status, note)

        refreshed_request = _get_welfare_request_by_id(request_id)
        if refreshed_request is not None:
            _notify_welfare_status_change(refreshed_request, new_status, actor_name, actor_role, note)
            _upsert_welfare_announcement(refreshed_request, new_status, actor_name, note)
        # OPTIMIZATION: Invalidate caches when request status changes
        st.cache_data.clear()
        return True
    except Exception as exc:
        logger.exception("Unable to update welfare request status: %s", exc)
        return False


def process_welfare_payment(request_id: int, treasurer_id: str, treasurer_name: str) -> tuple[bool, Optional[str], Optional[str]]:
    request = _get_welfare_request_by_id(request_id)
    if not request:
        return False, None, "Request not found"
    if request.get("status") not in {WELFARE_REQUEST_STATUS_APPROVED_BY_CHAIR, WELFARE_REQUEST_STATUS_PENDING_TREASURER_PAYMENT}:
        return False, None, "The request must be approved by the Chairperson before payment can be processed."
    if request.get("payment_reference"):
        return False, None, "Payment has already been processed for this request."
    if request.get("is_active") is False:
        return False, None, "The request is no longer active."
    if not request.get("approved_by_chairperson"):
        return False, None, "Chairperson approval is required before payment."

    beneficiary_id = request.get("member_id")
    beneficiary_name = request.get("member_name")

    ensure_member_balance_adjustments_table()
    try:
        with get_conn_from_pool() as conn:
            cur = conn.cursor()
            try:
                cur.execute(
                    "SELECT member_id, full_name, status FROM members ORDER BY full_name;",
                    (),
                )
                eligible_members = cur.fetchall()
                payment_reference = f"WEL-{request.get('case_number')}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
                receipt_number = f"RCPT-{request.get('case_number')}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
                transaction_id = f"TXN-{request.get('case_number')}-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"
                payment_timestamp = datetime.utcnow()
                receipt_text = (
                    f"Welfare Support Payment Receipt\n"
                    f"Case Number: {request.get('case_number')}\n"
                    f"Beneficiary: {beneficiary_name}\n"
                    f"Amount: UGX {int(WELFARE_PAYMENT_AMOUNT):,}\n"
                    f"Payment Reference: {payment_reference}\n"
                    f"Receipt Number: {receipt_number}\n"
                    f"Transaction ID: {transaction_id}\n"
                )

                cur.execute(
                    "INSERT INTO welfare_payments (request_id, payment_reference, receipt_number, transaction_id, payment_timestamp, amount, treasurer_id, treasurer_name, receipt_text, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);",
                    (request_id, payment_reference, receipt_number, transaction_id, payment_timestamp, WELFARE_PAYMENT_AMOUNT, treasurer_id, treasurer_name, receipt_text, "Completed"),
                )

                for member in eligible_members:
                    member_id = _get_member_row_value(member, "member_id", 0)
                    member_name = _get_member_row_value(member, "full_name", 1)
                    member_status = _get_member_row_value(member, "status", 2)
                    if not member_id or member_id == beneficiary_id:
                        continue
                    if not _is_welfare_contribution_eligible(member_status):
                        continue
                    _ensure_member_welfare_account(member_id, member_name)
                    current_balance = float(get_member_welfare_summary(member_id).get("welfare_balance", 0.0))
                    cur.execute(
                        "INSERT INTO ledger_transactions (member_id, member_name, transaction_type, amount, related_request_id, description, reference) VALUES (%s, %s, %s, %s, %s, %s, %s);",
                        (member_id, member_name, "Welfare Contribution", -WELFARE_PAYMENT_AMOUNT, request_id, f"Contribution toward {request.get('case_number')}", payment_reference),
                    )
                    cur.execute(
                        "INSERT INTO member_balance_adjustments (member_id, adjustment_type, amount, reference, reference_id, created_on) VALUES (%s, %s, %s, %s, %s, %s);",
                        (member_id, "welfare_contribution", WELFARE_PAYMENT_AMOUNT, payment_reference, request_id, payment_timestamp.date()),
                    )
                    if _should_suspend_for_zero_balance(current_balance, WELFARE_PAYMENT_AMOUNT):
                        execute_query(
                            "UPDATE members SET status = %s WHERE member_id = %s;",
                            params=("Suspended", member_id),
                            fetch=False,
                        )
                        _create_notification(
                            "member",
                            member_id,
                            "Welfare account suspended",
                            "Your welfare account has been suspended because your balance is zero and the required contribution could not be processed.",
                            request_id,
                        )
                        _create_notification(
                            "role",
                            "Treasurer",
                            "Member welfare account suspended",
                            f"{member_name or member_id} was suspended because their welfare balance is zero and the required contribution could not be processed.",
                            request_id,
                        )
                    else:
                        _create_notification(
                            "member",
                            member_id,
                            "Thank you for your welfare contribution",
                            f"Thank you for supporting {beneficiary_name} through your Welfare Contribution. Your UGX 20,000 contribution has been recorded successfully.",
                            request_id,
                        )

                cur.execute(
                    "INSERT INTO ledger_transactions (member_id, member_name, transaction_type, amount, related_request_id, description, reference) VALUES (%s, %s, %s, %s, %s, %s, %s);",
                    (beneficiary_id, beneficiary_name, "Welfare Support Credit", WELFARE_PAYMENT_AMOUNT, request_id, f"Welfare support for {request.get('case_number')}", payment_reference),
                )

                cur.execute(
                    "UPDATE welfare_requests SET status = %s, current_stage = %s, payment_reference = %s, payment_date = %s, paid_by = %s, payment_amount = %s, updated_at = %s WHERE id = %s;",
                    (WELFARE_REQUEST_STATUS_PAID, WELFARE_REQUEST_STATUS_PAID, payment_reference, payment_timestamp, treasurer_name, WELFARE_PAYMENT_AMOUNT, payment_timestamp, request_id),
                )

                _create_notification("member", beneficiary_id, "Welfare support paid", f"Your welfare support has been paid successfully. Reference: {payment_reference}", request_id)
                _notify_welfare_status_change({**request, "status": WELFARE_REQUEST_STATUS_PAID, "payment_reference": payment_reference}, WELFARE_REQUEST_STATUS_PAID, treasurer_name, "Treasurer", "Payment processed")
                _upsert_welfare_announcement({**request, "status": WELFARE_REQUEST_STATUS_PAID}, WELFARE_REQUEST_STATUS_PAID, treasurer_name, "Payment completed")
                _log_welfare_action(int(request_id), treasurer_id, treasurer_name, "Treasurer", "Paid", request.get("status"), WELFARE_REQUEST_STATUS_PAID, "Welfare payment processed", payment_reference)
                conn.commit()
                # OPTIMIZATION: Invalidate caches when payment is processed
                st.cache_data.clear()
                return True, payment_reference, receipt_text
            except Exception as exc:
                conn.rollback()
                logger.exception("Welfare payment failed for request %s: %s", request_id, exc)
                return False, None, str(exc)
    except Exception as exc:
        logger.exception("Welfare payment failed for request %s: %s", request_id, exc)
        return False, None, str(exc)


def _export_welfare_report(rows: list[dict], file_name: str) -> bytes:
    if not rows:
        return b""
    df = pd.DataFrame(rows)
    buffer = io.BytesIO()
    if file_name.endswith(".csv"):
        df.to_csv(buffer, index=False)
    elif file_name.endswith(".pdf"):
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

            doc = SimpleDocTemplate(buffer, pagesize=letter)
            styles = getSampleStyleSheet()
            elements = [Paragraph("Welfare Support Report", styles["Title"]), Spacer(1, 12)]
            table_data = [[str(col) for col in df.columns]] + df.astype(str).values.tolist()
            table = Table(table_data, repeatRows=1)
            table.setStyle(
                TableStyle([
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F766E")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ])
            )
            elements.append(table)
            doc.build(elements)
        except Exception:
            return b""
    buffer.seek(0)
    return buffer.getvalue()


def _render_metric_cards(items: list[tuple[str, str, str]]) -> None:
    cards_html = "".join(
        f"<div class='welfare-card'><div class='welfare-card-label'>{escape(title)}</div><div class='welfare-card-value'>{escape(value)}</div><div class='welfare-card-subtitle'>{escape(subtitle)}</div></div>"
        for title, value, subtitle in items
    )
    st.markdown(f"<div class='welfare-grid'>{cards_html}</div>", unsafe_allow_html=True)


def _render_announcement_card(announcement: dict) -> str:
    title = escape(str(announcement.get("title") or "Update"))
    content = escape(str(announcement.get("content") or ""))
    posted_by = escape(str(announcement.get("posted_by") or "System"))
    created_at = escape(str(announcement.get("created_at") or ""))
    return (
        "<div class='welfare-announcement-card'>"
        f"<div class='welfare-announcement-title'>{title}</div>"
        f"<div class='welfare-announcement-content'>{content}</div>"
        f"<div class='welfare-announcement-meta'>Posted by {posted_by} • {created_at}</div>"
        "</div>"
    )


def _inject_welfare_styles() -> None:
    stylesheet = """
    <style>
    .welfare-shell {
        font-family: 'Inter', 'Segoe UI', Roboto, Arial, sans-serif;
    }
    .welfare-hero {
        background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 55%, #0f766e 100%);
        border-radius: 24px;
        padding: 22px 24px;
        color: #f8fafc;
        box-shadow: 0 18px 48px rgba(15, 23, 42, 0.18);
        margin-bottom: 18px;
    }
    .welfare-hero-kicker {
        font-size: 0.76rem;
        font-weight: 700;
        letter-spacing: 0.22em;
        text-transform: uppercase;
        opacity: 0.85;
        margin-bottom: 8px;
    }
    .welfare-hero-title {
        font-size: 1.5rem;
        font-weight: 800;
        margin-bottom: 6px;
    }
    .welfare-hero-subtitle {
        font-size: 0.96rem;
        color: rgba(248, 250, 252, 0.86);
        line-height: 1.5;
    }
    .welfare-panel-title {
        font-size: 1.02rem;
        font-weight: 700;
        color: #0f172a;
        margin-bottom: 8px;
    }
    .welfare-stat-card {
        border-radius: 16px;
        padding: 14px;
        min-height: 122px;
        border: 1px solid #e2e8f0;
        background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
        box-shadow: 0 8px 28px rgba(15, 23, 42, 0.05);
    }
    .welfare-stat-title {
        font-size: 0.74rem;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.16em;
        color: #64748b;
        margin-bottom: 8px;
    }
    .welfare-stat-value {
        font-size: 1.18rem;
        font-weight: 800;
        color: #0f172a;
        margin-bottom: 6px;
        line-height: 1.3;
    }
    .welfare-stat-subtitle {
        font-size: 0.84rem;
        color: #475569;
        line-height: 1.45;
    }
    .welfare-amber { border-left: 4px solid #d97706; }
    .welfare-green { border-left: 4px solid #059669; }
    .welfare-red { border-left: 4px solid #dc2626; }
    .welfare-blue { border-left: 4px solid #2563eb; }
    .welfare-announcement-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-left: 4px solid #0f766e;
        border-radius: 14px;
        padding: 12px 14px;
        margin-bottom: 10px;
    }
    .welfare-announcement-title {
        font-size: 0.95rem;
        font-weight: 700;
        color: #0f172a;
        margin-bottom: 4px;
    }
    .welfare-announcement-content {
        font-size: 0.9rem;
        color: #334155;
        line-height: 1.5;
        white-space: pre-wrap;
    }
    .welfare-announcement-meta {
        margin-top: 8px;
        font-size: 0.76rem;
        color: #64748b;
    }
    .welfare-form-shell {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 18px;
        padding: 14px;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.04);
    }
    .welfare-action-row {
        display: flex;
        gap: 8px;
        flex-wrap: wrap;
        margin-top: 8px;
    }
    .welfare-action-row button {
        min-height: 42px;
        border-radius: 10px;
    }
    .welfare-chip {
        display: inline-block;
        padding: 6px 10px;
        border-radius: 999px;
        background: #eef2ff;
        color: #3730a3;
        font-size: 0.78rem;
        font-weight: 700;
        margin-bottom: 8px;
    }
    </style>
    """
    if hasattr(st, "html"):
        st.html(stylesheet)
    else:
        st.markdown(stylesheet, unsafe_allow_html=True)


def _render_hero_banner(user_role: str, user_name: str) -> None:
    role_title = "Treasurer View" if user_role == "Treasurer" else "Leadership View" if user_role in {"Chairperson", "Welfare", "Secretary", "Vice Chairperson"} else "Regular Member View"
    subtitle = (
        f"Welcome back, {user_name}. Review and manage welfare cases with a premium, secure operating view."
        if user_role == "Treasurer"
        else f"Welcome back, {user_name}. Manage your welfare journey with clarity and confidence."
    )
    st.markdown(
        f"""
        <div class='welfare-hero'>
            <div class='welfare-hero-kicker'>Welfare Support Module</div>
            <div class='welfare-hero-title'>{escape(role_title)}</div>
            <div class='welfare-hero-subtitle'>{escape(subtitle)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_role_access_notice(user_role: str, is_staff_view: bool, is_full_member: bool) -> None:
    role_label = (user_role or "Member").strip() or "Member"
    if is_staff_view:
        if role_label == "Treasurer":
            capabilities = "review approved requests, process welfare payments, and mark them as paid."
        elif role_label == "Chairperson":
            capabilities = "review requests approved by the Welfare team, approve or reject them, and send them back for review when needed."
        elif role_label == "Welfare":
            capabilities = "review new welfare requests, request more details, and approve or reject them for the next stage."
        elif role_label in {"Secretary", "Vice Chairperson"}:
            capabilities = "monitor welfare requests, review updates, and support oversight of the workflow."
        else:
            capabilities = "review welfare requests and help manage the welfare workflow."
        st.info(f"You are logged in as {role_label}. In the Welfare page, you can {capabilities}")
    else:
        if is_full_member:
            capabilities = "submit a new welfare request, track your request history, post messages, and view your welfare portfolio."
        else:
            capabilities = "view your welfare portfolio and request updates, but only Full Members can submit new welfare requests."
        st.info(f"You are logged in as {role_label}. In the Welfare page, you can {capabilities}")


def _render_stat_card(title: str, value: str, subtitle: str, tone: str = "navy") -> None:
    with st.container(border=True):
        st.markdown(
            f"""
            <div class='welfare-stat-card welfare-{tone}'>
                <div class='welfare-stat-title'>{escape(title)}</div>
                <div class='welfare-stat-value'>{escape(value)}</div>
                <div class='welfare-stat-subtitle'>{escape(subtitle)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_welfare_support_page() -> Optional[list[dict]]:
    """
    Main page renderer for welfare support module with comprehensive error handling.
    Ensures database failures never crash the application.
    """
    _ensure_welfare_tables()
    _inject_welfare_styles()

    user_role = st.session_state.get("user_role") or "Member"
    user_id = st.session_state.get("user_id")
    user_name = st.session_state.get("user_name") or "Member"
    
    # Safely load member context with error handling
    def load_member_context():
        return _get_current_member_context(user_id)

    def load_member_requests():
        return _get_welfare_requests_for_role("Member", user_id)
    
    member_context = execute_with_error_handling(
        load_member_context,
        "Loading member profile"
    ) or {}
    
    is_full_member = _is_full_member(member_context)
    is_staff_view = user_role in WELFARE_STAFF_ROLES
    member_welfare_account_status = _normalize_welfare_account_status(_get_member_welfare_account_status(user_id))
    is_suspended_account = _is_suspended_membership_status(member_context.get("status")) or member_welfare_account_status == "Suspended"

    _render_role_access_notice(user_role, is_staff_view, is_full_member)
    _render_hero_banner(user_role, user_name)

    if not is_staff_view and is_suspended_account:
        st.warning("Your welfare account is currently suspended. Please contact the SACCO leadership to have it reopened before you can submit new welfare requests.")
        if user_role in {"Chairperson", "Secretary"}:
            if st.button("Reopen welfare account", use_container_width=True, key="reopen_welfare_account"):
                ok = set_member_welfare_account_status(user_id, "Active", user_id or "system", user_role, reason="Reopened from welfare page")
                if ok:
                    st.success("Welfare account reopened successfully.")
                    st.rerun()
                else:
                    st.error("Unable to reopen the welfare account right now.")
        return

    if is_staff_view:
        # Safely load leader metrics with error handling
        def load_metrics():
            return get_welfare_leader_metrics()
        
        leader_metrics = execute_with_error_handling(
            load_metrics,
            "Loading dashboard metrics"
        ) or {
            "pending_requests": 0,
            "approved_requests": 0,
            "rejected_requests": 0,
            "paid_requests": 0,
            "outstanding_requests": 0,
            "monthly_stats": [],
        }
        st.markdown("<div class='welfare-panel-title'>Executive operating view</div>", unsafe_allow_html=True)
        metric_cols = st.columns(5)
        metric_items = [
            ("Pending", str(leader_metrics["pending_requests"]), "Needs immediate review", "amber"),
            ("Approved", str(leader_metrics["approved_requests"]), "Ready to progress", "green"),
            ("Rejected", str(leader_metrics["rejected_requests"]), "Requires follow-up", "red"),
            ("Paid", str(leader_metrics["paid_requests"]), "Completed disbursements", "blue"),
            ("Outstanding", str(leader_metrics["outstanding_requests"]), "Active workflow", "navy"),
        ]
        for column, (title, value, subtitle, tone) in zip(metric_cols, metric_items):
            with column:
                _render_stat_card(title, value, subtitle, tone)

        with st.container(border=True):
            control_cols = st.columns(3)
            with control_cols[0]:
                search_term = st.text_input(
                    "Search cases",
                    placeholder="Case number, member name, member ID, category, relationship, status",
                    key="welfare_search",
                )
            with control_cols[1]:
                status_filter = st.selectbox(
                    "Status",
                    options=[
                        "All",
                        WELFARE_REQUEST_STATUS_SUBMITTED,
                        WELFARE_REQUEST_STATUS_PENDING_WELFARE_REVIEW,
                        WELFARE_REQUEST_STATUS_APPROVED_BY_WELFARE,
                        WELFARE_REQUEST_STATUS_PENDING_CHAIR_APPROVAL,
                        WELFARE_REQUEST_STATUS_APPROVED_BY_CHAIR,
                        WELFARE_REQUEST_STATUS_PENDING_TREASURER_PAYMENT,
                        WELFARE_REQUEST_STATUS_PAID,
                        WELFARE_REQUEST_STATUS_REJECTED,
                        WELFARE_REQUEST_STATUS_RETURNED_FOR_REVIEW,
                    ],
                    key="welfare_status_filter",
                )
            with control_cols[2]:
                category_options = ["All", *sorted({str(r.get("support_category") or "") for r in _get_welfare_requests_for_role(user_role, user_id) if str(r.get("support_category") or "").strip()})]
                category_filter = st.selectbox("Category", options=category_options, key="welfare_category_filter")

            second_row = st.columns([1, 1, 1])
            with second_row[0]:
                year_options = ["All", *sorted({str(r.get("created_at", "") or "")[:4] for r in _get_welfare_requests_for_role(user_role, user_id) if str(r.get("created_at") or "")[:4].isdigit()}, reverse=True)]
                year_filter = st.selectbox("Year", options=year_options, key="welfare_year_filter")
            with second_row[1]:
                payment_filter = st.selectbox("Payment Status", options=["All", "Paid", "Pending"], key="welfare_payment_filter")
            with second_row[2]:
                st.caption("Pagination")

        # Load requests with error handling
        def load_requests():
            return _get_welfare_requests_for_role(user_role, user_id)
        
        requests = execute_with_error_handling(
            load_requests,
            "Loading welfare requests"
        ) or []
        
        filtered_requests = []
        for request in requests:
            status_value = str(request.get("status") or "")
            category_value = str(request.get("support_category") or "")
            case_value = str(request.get("case_number") or "")
            member_name = str(request.get("member_name") or "")
            member_id = str(request.get("member_id") or "")
            relationship = str(request.get("relationship") or "")
            searchable_text = " ".join([case_value, member_name, member_id, category_value, relationship, status_value]).lower()
            if search_term and search_term.lower() not in searchable_text:
                continue
            if status_filter != "All" and status_value != status_filter:
                continue
            if category_filter != "All" and category_value != category_filter:
                continue
            if year_filter != "All" and str(request.get("created_at") or "")[:4] != year_filter:
                continue
            if payment_filter == "Paid" and not request.get("payment_reference"):
                continue
            if payment_filter == "Pending" and request.get("payment_reference"):
                continue
            filtered_requests.append(request)

        left_col, right_col = st.columns([1.05, 1.2])
        with left_col:
            with st.container(border=True):
                st.markdown("<div class='welfare-panel-title'>Operational snapshot</div>", unsafe_allow_html=True)
                stats = _get_welfare_report_stats()
                st.metric("Open cases", stats.get("open_cases") or 0)
                st.metric("Closed cases", stats.get("closed_cases") or 0)
                st.metric("Approved", stats.get("approved") or 0)
                st.metric("Paid", stats.get("paid") or 0)
        with right_col:
            tabs = st.tabs(["Category Split", "Monthly Dynamics", "Annual Forecasts"])
            category_breakdown = pd.DataFrame(_get_category_breakdown())
            monthly_breakdown = pd.DataFrame(_get_monthly_breakdown())
            yearly_breakdown = pd.DataFrame(_get_yearly_breakdown())
            with tabs[0]:
                if not category_breakdown.empty:
                    category_breakdown = category_breakdown.rename(columns={"category_name": "Category", "total": "Requests"})
                    st.bar_chart(category_breakdown.set_index("Category"), width="stretch")
                else:
                    st.info("No category data yet.")
            with tabs[1]:
                if not monthly_breakdown.empty:
                    monthly_breakdown = monthly_breakdown.rename(columns={"month_key": "Month", "total": "Requests"})
                    st.line_chart(monthly_breakdown.set_index("Month"), width="stretch")
                else:
                    st.info("No monthly trend data yet.")
            with tabs[2]:
                if not yearly_breakdown.empty:
                    yearly_breakdown = yearly_breakdown.rename(columns={"year_key": "Year", "total": "Requests"})
                    st.line_chart(yearly_breakdown.set_index("Year"), width="stretch")
                else:
                    st.info("No annual trend data yet.")

        st.markdown("<div class='welfare-panel-title' style='margin-top: 12px;'>Case queue</div>", unsafe_allow_html=True)
        page_size = 8
        total_pages = max(1, (len(filtered_requests) + page_size - 1) // page_size)
        page_number = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1, key="welfare_page")
        start = (page_number - 1) * page_size
        paged_requests = filtered_requests[start:start + page_size]
        request = None
        if paged_requests:
            selected_request = st.selectbox(
                "Select request",
                options=[f"{r.get('case_number')} - {r.get('member_name')}" for r in paged_requests],
                key="welfare_select_request",
            )
            selected_id = next((int(r.get("id")) for r in paged_requests if f"{r.get('case_number')} - {r.get('member_name')}" == selected_request), None)
            request = _get_welfare_request_by_id(selected_id) if selected_id is not None else None

        if request:
            with st.container(border=True):
                st.markdown(
                    f"""
                    <div class='welfare-chip'>Case {escape(str(request.get('case_number') or ''))}</div>
                    <div class='welfare-panel-title'>Member: {escape(str(request.get('member_name') or ''))}</div>
                    <div style='color:#475569; line-height:1.7;'>Category: {escape(str(request.get('support_category') or ''))} • Status: {escape(str(request.get('status') or ''))}</div>
                    """,
                    unsafe_allow_html=True,
                )
                col_a, col_b = st.columns([1, 1])
                with col_a:
                    evidence_url = _safe_str(request.get("evidence_file_url"))
                    if evidence_url:
                        st.markdown("**Supporting document**")
                        st.link_button("Open uploaded evidence", evidence_url)
                        if request.get("uploaded_by") or request.get("uploaded_at"):
                            st.caption(f"Uploaded by: {request.get('uploaded_by') or '-'} • {request.get('uploaded_at') or '-'}")
                    if user_role == "Welfare":
                        action = st.selectbox("Welfare action", options=["Approve", "Reject", "Request more information", "Add internal note"], key="welfare_action")
                        note = st.text_area("Comment", value="")
                        if st.button("Apply welfare action"):
                            request_id = _safe_int(request.get("id"))
                            if action == "Approve":
                                ok = update_welfare_request_status(request_id, WELFARE_REQUEST_STATUS_WELFARE_APPROVED, user_id or "system", user_name, user_role, note, "welfare")
                            elif action == "Reject":
                                ok = update_welfare_request_status(request_id, WELFARE_REQUEST_STATUS_REJECTED, user_id or "system", user_name, user_role, note, "welfare")
                            elif action == "Request more information":
                                ok = update_welfare_request_status(request_id, WELFARE_REQUEST_STATUS_WELFARE_REVIEW, user_id or "system", user_name, user_role, note, "welfare")
                            else:
                                ok = update_welfare_request_status(request_id, WELFARE_REQUEST_STATUS_WELFARE_REVIEW, user_id or "system", user_name, user_role, note, "internal")
                            st.success("Action recorded.") if ok else st.error("Action could not be completed.")
                    elif user_role in {"Chairperson", "Secretary"}:
                        if user_role == "Chairperson":
                            action = st.selectbox("Chairperson action", options=["Approve", "Reject", "Return for review"], key="chair_action")
                            note = st.text_area("Chairperson comment", value="")
                            if st.button("Apply chairperson action"):
                                request_id = _safe_int(request.get("id"))
                                if action == "Approve":
                                    ok = update_welfare_request_status(request_id, WELFARE_REQUEST_STATUS_CHAIR_APPROVED, user_id or "system", user_name, user_role, note, "chair")
                                elif action == "Reject":
                                    ok = update_welfare_request_status(request_id, WELFARE_REQUEST_STATUS_REJECTED, user_id or "system", user_name, user_role, note, "chair")
                                else:
                                    ok = update_welfare_request_status(request_id, WELFARE_REQUEST_STATUS_WELFARE_REVIEW, user_id or "system", user_name, user_role, note, "chair")
                                st.success("Action recorded.") if ok else st.error("Action could not be completed.")

                        st.markdown("**Leadership welfare account controls**")
                        request_id = _safe_int(request.get("id"))
                        member_id = str(request.get("member_id") or "")
                        if member_id:
                            current_account_status = execute_query(
                                "SELECT status FROM member_welfare_accounts WHERE member_id = %s LIMIT 1;",
                                params=(member_id,),
                                fetch=True,
                            ) or []
                            account_status = str((current_account_status[0] or {}).get("status") or "Active") if current_account_status else "Active"
                            if account_status.lower() == "suspended":
                                if st.button("Reopen welfare account", key=f"unsuspend_welfare_{request_id}"):
                                    ok = set_member_welfare_account_status(member_id, "Active", user_id or "system", user_role, reason=f"Reopened by {user_role}")
                                    st.success("Welfare account reopened.") if ok else st.error("Unable to update welfare account status.")
                            else:
                                if st.button("Suspend welfare account", key=f"suspend_welfare_{request_id}"):
                                    ok = set_member_welfare_account_status(member_id, "Suspended", user_id or "system", user_role, reason=f"Suspended by {user_role}")
                                    st.success("Welfare account suspended.") if ok else st.error("Unable to update welfare account status.")
                    elif user_role == "Treasurer":
                        st.markdown("**Calculated payout**")
                        payment_amount = _safe_int(request.get("payment_amount"), default=int(WELFARE_PAYMENT_AMOUNT))
                        st.write(f"UGX {payment_amount:,}")
                        st.info(
                            "Treasurer rule: UGX 20,000 will be deducted from each eligible member except probationary members and the beneficiary when this payment is processed."
                        )
                        if st.button("Pay welfare support"):
                            request_id = _safe_int(request.get("id"))
                            ok, payment_reference, message = process_welfare_payment(request_id, user_id or "system", user_name)
                            if ok:
                                st.success(f"Payment processed. Reference: {payment_reference}")
                            else:
                                st.error(message or "Payment failed")
                    else:
                        st.info("Leadership review tools are available to Welfare, Chairperson, and Treasurer roles.")
                with col_b:
                    st.subheader("Audit Trail")
                    request_id = _safe_int(request.get("id"))
                    for audit in _get_request_audit_logs(request_id):
                        st.caption(f"{audit.get('created_at')} • {audit.get('user_name')} ({audit.get('role')}) • {audit.get('action')}")
                        if audit.get("details"):
                            st.write(audit.get("details"))
        else:
            st.info("No welfare requests available for review.")

        report_rows = [dict(row) for row in filtered_requests]
        if report_rows:
            csv_bytes = _export_welfare_report(report_rows, "welfare_report.csv")
            pdf_bytes = _export_welfare_report(report_rows, "welfare_report.pdf")
            col_a, col_b = st.columns(2)
            with col_a:
                st.download_button("Export welfare report (CSV)", csv_bytes, file_name="welfare_report.csv", mime="text/csv")
            with col_b:
                if pdf_bytes:
                    st.download_button("Export welfare report (PDF)", pdf_bytes, file_name="welfare_report.pdf", mime="application/pdf")
        return

    welfare_summary = get_member_welfare_summary(user_id)
    balance_col, action_col = st.columns([2, 1])
    with balance_col:
        with st.container(border=True):
            st.markdown("<div class='welfare-panel-title'>Your welfare portfolio</div>", unsafe_allow_html=True)
            st.markdown("<div class='welfare-chip'>Member view</div>", unsafe_allow_html=True)
            st.metric("Welfare reserve", f"UGX {welfare_summary['welfare_balance']:,.0f}")
            st.metric("Historical claims", welfare_summary["cases_requested"])
            if welfare_summary["last_contribution_date"]:
                st.caption(f"Last welfare contribution: {welfare_summary['last_contribution_date']}")
            st.caption(f"Current request status: {welfare_summary['status']}")

            paid_details = get_member_paid_welfare_details(user_id)
            if paid_details["amount_paid"] > 0:
                st.divider()
                st.subheader("Latest paid welfare support")
                st.metric("Amount paid to you", f"UGX {paid_details['amount_paid']:,.0f}")
                if paid_details.get("payment_reference"):
                    st.caption(f"Reference: {paid_details['payment_reference']}")
                if paid_details.get("payment_date"):
                    st.caption(f"Paid on: {paid_details['payment_date']}")
                if paid_details["contributions"]:
                    st.caption("Contributing members:")
                    for contribution in paid_details["contributions"]:
                        st.write(f"- {contribution['member_name']}: UGX {contribution['contribution_amount']:,.0f}")
    with action_col:
        with st.container(border=True):
            st.markdown("<div class='welfare-panel-title'>Submit new support</div>", unsafe_allow_html=True)
            st.caption("Start a fresh welfare claim with supporting evidence and a clear review trail.")
            if is_full_member:
                if st.button("Submit New Support Request", width="stretch"):
                    st.session_state["selected_page"] = "Welfare Support"
                    st.rerun()
            else:
                st.warning("Only Full Members can submit welfare support requests.")

    st.markdown("<div class='welfare-panel-title' style='margin-top: 16px;'>Request your support</div>", unsafe_allow_html=True)
    if not is_full_member:
        st.warning("Only Full Members are eligible to request Welfare Support.")
        return

    # Load categories with error handling
    def load_categories():
        return _get_welfare_categories()
    
    categories = execute_with_error_handling(
        load_categories,
        "Loading support categories"
    ) or []
    
    if not categories:
        st.info("No welfare categories are available yet. Please contact the Welfare team.")
        return

    field_errors: dict[str, list[str]] = st.session_state.get("welfare_form_field_errors", {})
    form_errors: list[str] = st.session_state.get("welfare_form_errors", [])
    submission_attempted: bool = st.session_state.get("welfare_form_submit_attempted", False)

    if field_errors:
        invalid_selectors = []
        invalid_map = {
            "membership_status": "#welfare_membership_status",
            "support_category": "#welfare_support_category",
            "relationship": "#welfare_relationship",
            "event_date": "#welfare_event_date",
            "location": "#welfare_location",
            "description": "#welfare_description",
            "evidence_file": "#welfare_evidence_file",
        }
        for field_name in field_errors:
            selector = invalid_map.get(field_name)
            if selector:
                invalid_selectors.append(selector)
        if invalid_selectors:
            st.markdown(
                "<style>" +
                "".join(
                    f"{selector} {{ border: 2px solid #dc2626 !important; border-radius: 0.65rem !important; }}"
                    for selector in invalid_selectors
                ) +
                "</style>",
                unsafe_allow_html=True,
            )

    if submission_attempted and form_errors:
        st.error("Please fix the fields highlighted below before resubmitting.")
        for error in form_errors:
            st.error(error)

    with st.form("welfare_request_form"):
        st.markdown("<div class='welfare-form-shell'>", unsafe_allow_html=True)
        st.markdown("#### Member Details")
        member_name = st.text_input("Member Name", value=member_context.get("full_name") or user_name, key="welfare_member_name")
        membership_number = st.text_input("Membership Number", value=member_context.get("member_id") or "", key="welfare_membership_number")
        phone_number = st.text_input("Phone Number", value=member_context.get("phone") or "", key="welfare_phone_number")
        email_address = st.text_input("Email", value=member_context.get("email") or "", key="welfare_email_address")
        membership_status = st.text_input("Membership Status", value=member_context.get("status") or "Full Member", key="welfare_membership_status")
        if field_errors.get("membership_status"):
            st.markdown(
                f"<div style='color:#dc2626; font-size:0.92rem; margin-top:-0.5rem;'>{field_errors['membership_status'][0]}</div>",
                unsafe_allow_html=True,
            )
        date_joined = st.date_input("Date Joined", value=member_context.get("join_date") or datetime.utcnow().date(), min_value=date(1964, 1, 1), max_value=today_in_uganda(), key="welfare_join_date")
        request_date = st.date_input("Request Date", value=today_in_uganda(), min_value=date(2000, 1, 1), max_value=today_in_uganda(), key="welfare_request_date")
        category_options = [_safe_str(row.get("category_name") or "General") for row in categories]
        support_category = st.selectbox("Support Category", options=category_options, index=0 if category_options else None, key="welfare_support_category")
        if field_errors.get("support_category"):
            st.markdown(
                f"<div style='color:#dc2626; font-size:0.92rem; margin-top:-0.5rem;'>{field_errors['support_category'][0]}</div>",
                unsafe_allow_html=True,
            )
        relationship = st.text_input("Relationship", value="", key="welfare_relationship")
        if field_errors.get("relationship"):
            st.markdown(
                f"<div style='color:#dc2626; font-size:0.92rem; margin-top:-0.5rem;'>{field_errors['relationship'][0]}</div>",
                unsafe_allow_html=True,
            )
        event_date = st.date_input("Event Date", value=today_in_uganda(), min_value=date(2000, 1, 1), max_value=today_in_uganda(), key="welfare_event_date")
        if field_errors.get("event_date"):
            st.markdown(
                f"<div style='color:#dc2626; font-size:0.92rem; margin-top:-0.5rem;'>{field_errors['event_date'][0]}</div>",
                unsafe_allow_html=True,
            )
        location = st.text_input("Location", value="", key="welfare_location")
        if field_errors.get("location"):
            st.markdown(
                f"<div style='color:#dc2626; font-size:0.92rem; margin-top:-0.5rem;'>{field_errors['location'][0]}</div>",
                unsafe_allow_html=True,
            )
        description = st.text_area("Description", height=120, value="", key="welfare_description")
        if field_errors.get("description"):
            st.markdown(
                f"<div style='color:#dc2626; font-size:0.92rem; margin-top:-0.5rem;'>{field_errors['description'][0]}</div>",
                unsafe_allow_html=True,
            )
        evidence_file = st.file_uploader("Supporting Evidence (optional)", type=["jpg", "jpeg", "png", "pdf"], help="Upload death announcement, funeral programme, invitation card, hospital letter, or other supporting evidence.", key="welfare_evidence_file")
        if field_errors.get("evidence_file"):
            st.markdown(
                f"<div style='color:#dc2626; font-size:0.92rem; margin-top:-0.5rem;'>{field_errors['evidence_file'][0]}</div>",
                unsafe_allow_html=True,
            )
        st.markdown("#### Submit Request")
        submitted = st.form_submit_button("Submit Welfare Request")
        st.markdown("</div>", unsafe_allow_html=True)

    if submitted:
        errors = validate_welfare_request_payload(
            membership_status=_safe_str(membership_status),
            support_category=_safe_str(support_category),
            relationship=_safe_str(relationship),
            event_date=event_date,
            location=_safe_str(location),
            description=_safe_str(description),
            uploaded_file=evidence_file,
            member_id=_safe_str(user_id),
        )
        field_errors = _map_welfare_payload_errors(errors)
        st.session_state["welfare_form_field_errors"] = field_errors
        st.session_state["welfare_form_errors"] = errors
        st.session_state["welfare_form_submit_attempted"] = True
        if errors:
            rerun_fn = getattr(st, "rerun", None)
            if callable(rerun_fn):
                rerun_fn()
        request_data = create_welfare_request(
            member_id=_safe_str(user_id),
            member_name=_safe_str(member_name),
            email=_safe_str(email_address),
            phone=_safe_str(phone_number),
            membership_status=_safe_str(membership_status),
            join_date=date_joined,
            request_date=request_date,
            support_category=_safe_str(support_category),
            relationship=_safe_str(relationship),
            event_date=event_date,
            location=_safe_str(location),
            description=_safe_str(description),
            uploaded_file=evidence_file,
        )
        return _get_welfare_requests_for_role("Member", user_id)
    
    member_requests = execute_with_error_handling(
        load_member_requests,
        "Loading your welfare history"
    ) or []
    
    if not member_requests:
        st.info("You have no welfare requests yet.")
    else:
        # OPTIMIZATION: Implement pagination for member history
        page_size = 10
        total_pages = max(1, (len(member_requests) + page_size - 1) // page_size)
        history_page = st.number_input("History page", min_value=1, max_value=total_pages, value=1, step=1, key="welfare_history_page")
        start = (history_page - 1) * page_size
        paged_member_requests = member_requests[start:start + page_size]
        
        for request in paged_member_requests:
            with st.expander(f"{request.get('case_number')} • {request.get('support_category')} • {request.get('status')}"):
                st.write(request.get("description") or "")
                st.caption(f"Relationship: {request.get('relationship') or '-'} • Location: {request.get('location') or '-'}")
                st.write("Timeline")
                status_steps = _build_welfare_timeline_steps(request)
                current_index = next((idx for idx, step in enumerate(status_steps) if step.get("status") == request.get("status")), None)
                if current_index is None:
                    current_index = 0
                completed_steps = [
                    _safe_str(step.get("label"))
                    for idx, step in enumerate(status_steps)
                    if idx <= current_index and _safe_str(step.get("label"))
                ]
                pending_steps = [
                    _safe_str(step.get("label"))
                    for idx, step in enumerate(status_steps)
                    if idx > current_index and _safe_str(step.get("label"))
                ]
                st.caption(f"Current step: {status_steps[current_index].get('label')}" if current_index is not None else "Current step: Submitted")
                st.caption(f"Completed steps: {', '.join(completed_steps) if completed_steps else 'None'}")
                st.caption(f"Pending steps: {', '.join(pending_steps) if pending_steps else 'None'}")
                for idx, step in enumerate(status_steps):
                    status_icon = "✅" if idx <= current_index else "○"
                    st.write(f"{status_icon} {step.get('label')} — {step.get('description')}")
                st.caption(f"Officer responsible: {request.get('approved_by_welfare_officer') or request.get('approved_by_chairperson') or request.get('paid_by') or '-'}")
                st.caption(f"Date: {request.get('updated_at') or request.get('created_at') or '-'}")
                st.caption(f"Comments: {request.get('welfare_officer_comment') or request.get('chairperson_comment') or request.get('treasurer_comment') or 'No comments yet.'}")

                st.write("Announcements related to this case")
                related_announcements = _get_related_announcements(request)
                if related_announcements:
                    for announcement in related_announcements:
                        st.markdown(_render_announcement_card(announcement), unsafe_allow_html=True)
                else:
                    st.info("No related announcements yet.")

                st.write("Messages")
                message_text = st.text_area("Add a message", value="", key=f"welfare_message_{request.get('id')}")
                st.markdown("<div class='welfare-action-row'>", unsafe_allow_html=True)
                if st.button("Post message", key=f"welfare_post_{request.get('id')}"):
                    request_id = _safe_int(request.get("id"))
                    _add_welfare_request_comment(request_id, _safe_str(user_id), _safe_str(user_name), _safe_str(message_text))
                    st.success("Message posted.")
                st.markdown("</div>", unsafe_allow_html=True)

                request_id = _safe_int(request.get("id"))
                for message in _get_welfare_messages(request_id):
                    st.caption(f"{message.get('member_name')} • {message.get('created_at')}")
                    st.write(message.get("message"))
                    if user_role in {"Chairperson", "Secretary", "Welfare", "Treasurer", "Vice Chairperson"}:
                        st.markdown("<div class='welfare-action-row'>", unsafe_allow_html=True)
                        if st.button("Remove", key=f"remove_message_{message.get('id')}"):
                            _toggle_message_visibility(_safe_int(message.get("id")), True)
                            st.rerun()
                        st.markdown("</div>", unsafe_allow_html=True)


def welfare_support_view() -> None:
    render_welfare_support_page()
