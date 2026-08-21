import io
import os
import time
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
from html import escape
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

from app import coerce_date_input_value
from src.database.connection import execute_query
from src.utils.audit import (
    build_audit_dashboard_summary,
    fetch_enriched_audit_events,
    fetch_recent_audit_events,
    record_audit_event,
)
from src.utils.notifications import (
    get_notifications_for_user,
    get_unread_notification_count,
    mark_all_notifications_read,
    mark_notification_read,
)
from src.utils.reminders import run_reminder_engine

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def ensure_member_profile_columns() -> None:
    try:
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS members (
                id SERIAL PRIMARY KEY,
                member_id TEXT UNIQUE,
                full_name TEXT,
                email TEXT UNIQUE,
                phone TEXT,
                password_hash TEXT,
                role TEXT,
                status TEXT,
                join_date DATE,
                notes TEXT,
                avatar_url TEXT,
                date_of_birth DATE,
                gender TEXT,
                address TEXT,
                city TEXT,
                country TEXT,
                nationality TEXT,
                occupation TEXT,
                employer TEXT,
                national_id TEXT,
                next_of_kin_name TEXT,
                next_of_kin_relationship TEXT,
                next_of_kin_phone TEXT,
                emergency_contact_name TEXT,
                emergency_contact_phone TEXT
            );
            """,
            params=None,
            fetch=False,
        )
        execute_query(
            """
            ALTER TABLE members
            ADD COLUMN IF NOT EXISTS join_date DATE,
            ADD COLUMN IF NOT EXISTS notes TEXT,
            ADD COLUMN IF NOT EXISTS avatar_url TEXT,
            ADD COLUMN IF NOT EXISTS date_of_birth DATE,
            ADD COLUMN IF NOT EXISTS gender TEXT,
            ADD COLUMN IF NOT EXISTS address TEXT,
            ADD COLUMN IF NOT EXISTS city TEXT,
            ADD COLUMN IF NOT EXISTS country TEXT,
            ADD COLUMN IF NOT EXISTS nationality TEXT,
            ADD COLUMN IF NOT EXISTS occupation TEXT,
            ADD COLUMN IF NOT EXISTS employer TEXT,
            ADD COLUMN IF NOT EXISTS national_id TEXT,
            ADD COLUMN IF NOT EXISTS next_of_kin_name TEXT,
            ADD COLUMN IF NOT EXISTS next_of_kin_relationship TEXT,
            ADD COLUMN IF NOT EXISTS next_of_kin_phone TEXT,
            ADD COLUMN IF NOT EXISTS emergency_contact_name TEXT,
            ADD COLUMN IF NOT EXISTS emergency_contact_phone TEXT;
            """,
            params=None,
            fetch=False,
        )
    except Exception as exc:
        st.warning(f"Unable to prepare member profile fields: {exc}")


def _normalize_join_date(value: Optional[object]) -> Optional[date]:
    if value in (None, "", "None"):
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return date.fromisoformat(cleaned)
        except ValueError:
            try:
                return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).date()
            except ValueError:
                return None
    return None


def _rerun_page() -> None:
    """Safely rerun the current Streamlit page using the current API."""
    rerun = getattr(st, "rerun", None)
    if callable(rerun):
        rerun()
        return

    try:
        st.session_state.setdefault("_rerun_trigger", False)
        st.session_state["_rerun_trigger"] = not st.session_state["_rerun_trigger"]
    except Exception:
        return


def _render_member_profile_summary(member_record: Optional[Dict]) -> None:
    """Render a polished member profile summary card for the selected record."""
    if not member_record:
        st.info("No profile details available yet.")
        return

    full_name = str(member_record.get("full_name") or "Unnamed Member")
    role = str(member_record.get("role") or "Member")
    status = str(member_record.get("status") or "Pending")
    join_date = str(member_record.get("join_date") or "—")
    email = str(member_record.get("email") or "—")
    phone = str(member_record.get("phone") or "—")
    occupation = str(member_record.get("occupation") or "—")
    employer = str(member_record.get("employer") or "—")
    national_id = str(member_record.get("national_id") or "—")
    emergency_name = str(member_record.get("emergency_contact_name") or "—")
    emergency_phone = str(member_record.get("emergency_contact_phone") or "—")

    initials = "".join(part[0].upper() for part in full_name.split()[:2]) or "M"

    st.markdown(
        f"""
        <div class="detail-hero-card">
            <div class="detail-hero-avatar">{escape(initials)}</div>
            <div class="detail-hero-copy">
                <div class="detail-hero-name">{escape(full_name)}</div>
                <div class="detail-hero-meta">{escape(role)} • {escape(status)}</div>
                <div class="detail-hero-meta">Joined {escape(join_date)}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left_col, right_col = st.columns([1.05, 1.0], gap="medium")
    with left_col:
        with st.container(border=True):
            st.markdown("<div class='section-title'>System & Role Details</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='attribute-row'><span class='attribute-label'>Role</span><div class='attribute-value'>{escape(role)}</div></div>", unsafe_allow_html=True)
            st.markdown(f"<div class='attribute-row'><span class='attribute-label'>Status</span><div class='attribute-value'>{escape(status)}</div></div>", unsafe_allow_html=True)
            st.markdown(f"<div class='attribute-row'><span class='attribute-label'>Join Date</span><div class='attribute-value'>{escape(join_date)}</div></div>", unsafe_allow_html=True)
            st.markdown(f"<div class='attribute-row'><span class='attribute-label'>Email</span><div class='attribute-value'>{escape(email)}</div></div>", unsafe_allow_html=True)
            st.markdown(f"<div class='attribute-row'><span class='attribute-label'>Phone</span><div class='attribute-value'>{escape(phone)}</div></div>", unsafe_allow_html=True)

    with right_col:
        with st.container(border=True):
            st.markdown("<div class='section-title'>Employment & Identity</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='attribute-row'><span class='attribute-label'>Occupation</span><div class='attribute-value'>{escape(occupation)}</div></div>", unsafe_allow_html=True)
            st.markdown(f"<div class='attribute-row'><span class='attribute-label'>Employer</span><div class='attribute-value'>{escape(employer)}</div></div>", unsafe_allow_html=True)
            st.markdown(f"<div class='attribute-row'><span class='attribute-label'>National ID</span><div class='attribute-value'>{escape(national_id)}</div></div>", unsafe_allow_html=True)
            st.markdown(f"<div class='attribute-row'><span class='attribute-label'>Emergency Contact</span><div class='attribute-value'>{escape(emergency_name)}<br>{escape(emergency_phone)}</div></div>", unsafe_allow_html=True)


def _build_changed_profile_update_payload(original: Optional[Dict], submitted: Dict) -> Dict:
    """Return only the fields whose submitted values differ from the original record."""
    if not original:
        return {key: value for key, value in submitted.items()}

    payload: Dict = {}
    for key, value in submitted.items():
        original_value = original.get(key)
        if isinstance(value, str):
            normalized_value = value.strip()
            if isinstance(original_value, str):
                normalized_original = original_value.strip()
            else:
                normalized_original = ""
            if normalized_value == "":
                payload[key] = None
            else:
                payload[key] = normalized_value if normalized_value != normalized_original else None
        else:
            payload[key] = value if value != original_value else None

    return payload


def build_member_profile_update(
    member_id: str,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    join_date: Optional[object] = None,
    notes: Optional[str] = None,
    date_of_birth: Optional[object] = None,
    gender: Optional[str] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    nationality: Optional[str] = None,
    occupation: Optional[str] = None,
    employer: Optional[str] = None,
    national_id: Optional[str] = None,
    next_of_kin_name: Optional[str] = None,
    next_of_kin_relationship: Optional[str] = None,
    next_of_kin_phone: Optional[str] = None,
    emergency_contact_name: Optional[str] = None,
    emergency_contact_phone: Optional[str] = None,
) -> Tuple[str, Tuple[object, ...]]:
    updates: List[str] = []
    params: List[object] = []

    if full_name is not None:
        updates.append("full_name = %s")
        params.append(full_name)
    if email is not None:
        updates.append("email = %s")
        params.append(email)
    if phone is not None:
        updates.append("phone = %s")
        params.append(phone)
    if role is not None:
        updates.append("role = %s")
        params.append(role)
    if status is not None:
        updates.append("status = %s")
        params.append(status)
    if join_date is not None:
        updates.append("join_date = %s")
        params.append(_normalize_join_date(join_date) or join_date)
    if notes is not None:
        updates.append("notes = %s")
        params.append(notes)
    if date_of_birth is not None:
        updates.append("date_of_birth = %s")
        params.append(_normalize_join_date(date_of_birth) or date_of_birth)
    if gender is not None:
        updates.append("gender = %s")
        params.append(gender)
    if address is not None:
        updates.append("address = %s")
        params.append(address)
    if city is not None:
        updates.append("city = %s")
        params.append(city)
    if country is not None:
        updates.append("country = %s")
        params.append(country)
    if nationality is not None:
        updates.append("nationality = %s")
        params.append(nationality)
    if occupation is not None:
        updates.append("occupation = %s")
        params.append(occupation)
    if employer is not None:
        updates.append("employer = %s")
        params.append(employer)
    if national_id is not None:
        updates.append("national_id = %s")
        params.append(national_id)
    if next_of_kin_name is not None:
        updates.append("next_of_kin_name = %s")
        params.append(next_of_kin_name)
    if next_of_kin_relationship is not None:
        updates.append("next_of_kin_relationship = %s")
        params.append(next_of_kin_relationship)
    if next_of_kin_phone is not None:
        updates.append("next_of_kin_phone = %s")
        params.append(next_of_kin_phone)
    if emergency_contact_name is not None:
        updates.append("emergency_contact_name = %s")
        params.append(emergency_contact_name)
    if emergency_contact_phone is not None:
        updates.append("emergency_contact_phone = %s")
        params.append(emergency_contact_phone)

    if not updates:
        return "", tuple()

    query = f"UPDATE members SET {', '.join(updates)} WHERE member_id = %s;"
    params.append(member_id)
    return query, tuple(params)


def fetch_member_directory() -> List[Dict]:
    """Fetch member directory with 5-minute cache TTL."""
    return fetch_member_directory_cached()


@st.cache_data(ttl=300)
def fetch_member_directory_cached() -> List[Dict]:
    rows = execute_query(
        "SELECT member_id, full_name, email, phone, role, status, join_date, notes, avatar_url FROM members ORDER BY full_name;",
        params=None,
        fetch=True,
    )
    return rows or []


def fetch_member_record(member_id: str) -> Optional[Dict]:
    return fetch_member_record_cached(member_id)


def _resolve_member_profile_detail(member_id: Optional[str], directory_members: List[Dict], fallback_members: Optional[List[Dict]] = None) -> Optional[Dict]:
    if not member_id:
        return None

    full_member = fetch_member_record(str(member_id))
    if full_member:
        directory_match = next((member for member in directory_members if str(member.get("member_id") or "") == str(member_id)), None)
        if directory_match:
            merged = dict(directory_match)
            for key, value in full_member.items():
                if value is None:
                    continue
                if isinstance(value, str) and not value.strip():
                    continue
                merged[key] = value
            return merged
        return full_member

    directory_match = next((member for member in directory_members if str(member.get("member_id") or "") == str(member_id)), None)
    if directory_match:
        return directory_match

    if fallback_members:
        return next((member for member in fallback_members if str(member.get("member_id") or "") == str(member_id)), None)
    return None


@st.cache_data(ttl=300)
def fetch_member_record_cached(member_id: str) -> Optional[Dict]:
    rows = execute_query(
        "SELECT member_id, full_name, email, phone, role, status, join_date, notes, avatar_url, date_of_birth, gender, address, city, country, nationality, occupation, employer, national_id, next_of_kin_name, next_of_kin_relationship, next_of_kin_phone, emergency_contact_name, emergency_contact_phone FROM members WHERE member_id = %s LIMIT 1;",
        params=(member_id,),
        fetch=True,
    )
    return rows[0] if rows else None


def fetch_documents() -> List[Dict]:
    """Fetch documents with 5-minute cache TTL."""
    return fetch_documents_cached()


@st.cache_data(ttl=300)
def fetch_documents_cached() -> List[Dict]:
    rows = execute_query(
        "SELECT title, file_url, uploaded_at FROM group_documents ORDER BY uploaded_at DESC;",
        params=None,
        fetch=True,
    )
    return rows or []


def save_document_record(title: str, file_url: str, uploaded_by: str) -> None:
    execute_query(
        "INSERT INTO group_documents (title, file_url, uploaded_at, uploaded_by) VALUES (%s, %s, %s, %s);",
        params=(title, file_url, datetime.utcnow(), uploaded_by),
        fetch=False,
    )


def update_member_role_status(member_id: str, new_role: str, new_status: str) -> None:
    execute_query(
        "UPDATE members SET role = %s, status = %s WHERE member_id = %s;",
        params=(new_role, new_status, member_id),
        fetch=False,
    )


def build_member_profile_pdf(member_record: Optional[Dict]) -> bytes:
    if not member_record:
        member_record = {}

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    pdf.setTitle(f"Member Profile - {member_record.get('member_id', 'Unknown')}")
    pdf.setFont("Helvetica-Bold", 18)
    pdf.setFillColor(colors.HexColor("#14532D"))
    pdf.drawString(0.75 * inch, height - 0.75 * inch, "Comfort Portal - Member Profile")

    pdf.setFont("Helvetica", 11)
    pdf.setFillColor(colors.HexColor("#1F2937"))
    y = height - 1.25 * inch
    fields = [
        ("Member ID", member_record.get("member_id") or "-"),
        ("Full Name", member_record.get("full_name") or "-"),
        ("Email", member_record.get("email") or "-"),
        ("Phone", member_record.get("phone") or "-"),
        ("Role", member_record.get("role") or "-"),
        ("Status", member_record.get("status") or "-"),
        ("Join Date", member_record.get("join_date") or "-"),
        ("Occupation", member_record.get("occupation") or "-"),
        ("Employer", member_record.get("employer") or "-"),
        ("National ID", member_record.get("national_id") or "-"),
        ("Address", member_record.get("address") or "-"),
        ("City", member_record.get("city") or "-"),
        ("Next of Kin", member_record.get("next_of_kin_name") or "-"),
        ("Emergency Contact", member_record.get("emergency_contact_phone") or "-"),
    ]

    for label, value in fields:
        if y < 1.0 * inch:
            pdf.showPage()
            y = height - 0.75 * inch
        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(0.75 * inch, y, f"{label}:")
        pdf.setFont("Helvetica", 11)
        pdf.drawString(1.8 * inch, y, str(value))
        y -= 0.2 * inch

    pdf.save()
    return buffer.getvalue()


def _record_membership_audit_log(member_id: str, old_status: Optional[str], new_status: str, action_performed: str, performed_by: str, admin_role: str, reason: Optional[str] = None) -> None:
    try:
        execute_query(
            """
            INSERT INTO audit_logs (member_id, old_status, new_status, action_performed, performed_by, admin_role, reason, timestamp)
            VALUES (%s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP);
            """,
            params=(member_id, old_status, new_status, action_performed, performed_by, admin_role, reason),
            fetch=False,
        )
    except Exception:
        pass


def _clear_member_cache() -> None:
    for cache_fn in (fetch_member_directory_cached, fetch_member_record_cached):
        try:
            cache_fn.clear()
        except Exception:
            pass


def approve_new_registration(member_id: str, performed_by: str, admin_role: str, reason: Optional[str] = None) -> None:
    current = fetch_member_record(member_id) or {}
    old_status = str(current.get("status") or "Pending")
    execute_query(
        "UPDATE members SET status = %s, role = %s, join_date = COALESCE(join_date, CURRENT_DATE) WHERE member_id = %s;",
        params=("Probationary", "Member", member_id),
        fetch=False,
    )
    _record_membership_audit_log(member_id, old_status, "Probationary", "Approve as Probation", performed_by, admin_role, reason)
    record_audit_event(
        entity_type="member",
        entity_id=member_id,
        action="membership_approved",
        actor_name=performed_by,
        actor_role=admin_role,
        details=reason or "Membership approved as probationary",
        previous_value=old_status,
        new_value="Probationary",
    )
    create_notification(
        recipient_type="member",
        recipient_id=member_id,
        recipient_role="Member",
        title="Registration approved",
        message="Your registration was approved and your membership is now probationary.",
        category="Membership",
        module_name="Admin",
        related_record_id=member_id,
        priority="High",
    )
    _clear_member_cache()


def update_member_status(member_id: str, new_status: str, performed_by: str, admin_role: str, reason: Optional[str] = None) -> bool:
    if not member_id:
        return False
    current = fetch_member_record(member_id) or {}
    old_status = str(current.get("status") or "Pending")
    execute_query(
        "UPDATE members SET status = %s, previous_membership_status = COALESCE(previous_membership_status, %s) WHERE member_id = %s;",
        params=(new_status, old_status, member_id),
        fetch=False,
    )
    _record_membership_audit_log(member_id, old_status, new_status, f"Status update to {new_status}", performed_by, admin_role, reason)
    record_audit_event(
        entity_type="member",
        entity_id=member_id,
        action="membership_status_updated",
        actor_name=performed_by,
        actor_role=admin_role,
        details=reason or f"Status updated to {new_status}",
        previous_value=old_status,
        new_value=new_status,
    )
    create_notification(
        recipient_type="member",
        recipient_id=member_id,
        recipient_role="Member",
        title="Membership status updated",
        message=f"Your membership status was updated to {new_status}.",
        category="Membership",
        module_name="Admin",
        related_record_id=member_id,
        priority="High",
    )
    _clear_member_cache()
    return True


def delete_member_account(member_id: str, performed_by: str, admin_role: str, reason: Optional[str] = None) -> bool:
    if not member_id:
        return False
    return update_member_status(member_id, "Deleted", performed_by, admin_role, reason=reason)


def update_member_profile(
    member_id: str,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    join_date: Optional[object] = None,
    notes: Optional[str] = None,
    date_of_birth: Optional[object] = None,
    gender: Optional[str] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    nationality: Optional[str] = None,
    occupation: Optional[str] = None,
    employer: Optional[str] = None,
    national_id: Optional[str] = None,
    next_of_kin_name: Optional[str] = None,
    next_of_kin_relationship: Optional[str] = None,
    next_of_kin_phone: Optional[str] = None,
    emergency_contact_name: Optional[str] = None,
    emergency_contact_phone: Optional[str] = None,
) -> None:
    ensure_member_profile_columns()
    query, params = build_member_profile_update(
        member_id,
        full_name=full_name,
        email=email,
        phone=phone,
        role=role,
        status=status,
        join_date=join_date,
        notes=notes,
        date_of_birth=date_of_birth,
        gender=gender,
        address=address,
        city=city,
        country=country,
        nationality=nationality,
        occupation=occupation,
        employer=employer,
        national_id=national_id,
        next_of_kin_name=next_of_kin_name,
        next_of_kin_relationship=next_of_kin_relationship,
        next_of_kin_phone=next_of_kin_phone,
        emergency_contact_name=emergency_contact_name,
        emergency_contact_phone=emergency_contact_phone,
    )
    if query:
        execute_query(query, params=params, fetch=False)
        if st.session_state.get("user_id") == member_id:
            st.session_state["join_date"] = join_date
            st.session_state["user_status"] = status
        try:
            fetch_member_directory_cached.clear()
        except Exception:
            pass
        try:
            fetch_member_record_cached.clear()
        except Exception:
            pass


def _inject_admin_docs_css() -> None:
    st.markdown(
        """
        <style>
            .stApp { background: #f8fafc; }
            .block-container { padding-top: 1rem; padding-bottom: 2rem; max-width: 1400px; }
            .admin-shell { padding: 0.25rem 0 1.25rem; }
            .page-title { margin: 0 0 0.35rem; font-size: clamp(1.55rem, 2.2vw, 2.15rem); color: #0f172a; font-weight: 800; letter-spacing: -0.02em; }
            .page-caption { margin: 0 0 1rem; color: #475569; font-size: 0.95rem; line-height: 1.55; }
            .surface-card { background: #ffffff; border: 1px solid #e2e8f0; border-radius: 20px; padding: 1rem 1rem 1.1rem; box-shadow: 0 16px 40px rgba(15, 23, 42, 0.04); margin-bottom: 1rem; }
            .section-title { font-size: 1rem; font-weight: 800; color: #0f172a; margin-bottom: 0.65rem; }
            .directory-row { display: flex; align-items: center; gap: 0.75rem; padding: 0.9rem 0.8rem; border-radius: 16px; border: 1px solid #e2e8f0; background: #fff; margin-bottom: 0.7rem; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.03); }
            .directory-row:hover { border-color: #c7d2fe; }
            .avatar-circle { width: 44px; height: 44px; border-radius: 999px; background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%); color: white; font-size: 0.92rem; font-weight: 800; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }
            .member-name { font-weight: 800; color: #0f172a; margin-bottom: 0.2rem; }
            .member-id { font-size: 0.8rem; color: #64748b; }
            .pill { display: inline-flex; align-items: center; border-radius: 999px; padding: 0.28rem 0.7rem; font-size: 0.74rem; font-weight: 700; white-space: nowrap; }
            .pill-role { background: #eef2ff; color: #4338ca; }
            .pill-active { background: #ecfdf3; color: #047857; }
            .pill-pending { background: #fef3c7; color: #b45309; }
            .pill-inactive { background: #fef2f2; color: #b91c1c; }
            .detail-hero-card { display: flex; align-items: center; gap: 1rem; padding: 1rem; border-radius: 22px; background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%); border: 1px solid #e2e8f0; box-shadow: 0 18px 40px rgba(15, 23, 42, 0.04); margin-bottom: 1rem; }
            .detail-hero-avatar { width: 64px; height: 64px; border-radius: 18px; background: linear-gradient(135deg, #4f46e5 0%, #6366f1 100%); color: white; font-size: 1.1rem; font-weight: 800; display: inline-flex; align-items: center; justify-content: center; flex-shrink: 0; }
            .detail-hero-name { font-size: 1.15rem; font-weight: 800; color: #0f172a; margin-bottom: 0.2rem; }
            .detail-hero-meta { font-size: 0.9rem; color: #475569; }
            .metric-card { background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%); border: 1px solid #e2e8f0; border-radius: 18px; padding: 0.9rem 0.95rem; box-shadow: 0 12px 28px rgba(15, 23, 42, 0.04); }
            .metric-label { font-size: 0.78rem; letter-spacing: 0.08em; text-transform: uppercase; color: #64748b; font-weight: 700; margin-bottom: 0.3rem; }
            .metric-value { font-size: 1.25rem; font-weight: 800; color: #0f172a; }
            .chip { display: inline-flex; align-items: center; border-radius: 999px; padding: 0.28rem 0.7rem; font-size: 0.72rem; font-weight: 700; margin-right: 0.35rem; }
            .chip-approved { background: #ecfdf3; color: #047857; }
            .chip-rejected { background: #fef2f2; color: #b91c1c; }
            .chip-pending { background: #fef3c7; color: #b45309; }
            .chip-warning { background: #eff6ff; color: #1d4ed8; }
            .chip-critical { background: #fef2f2; color: #b91c1c; }
            .audit-row { border: 1px solid #e2e8f0; border-radius: 16px; padding: 0.85rem 0.95rem; margin-bottom: 0.7rem; background: #ffffff; }
            .audit-row-header { display: flex; justify-content: space-between; align-items: center; gap: 0.7rem; margin-bottom: 0.45rem; }
            .audit-row-title { font-weight: 800; color: #0f172a; }
            .audit-row-subtitle { font-size: 0.88rem; color: #64748b; }
            .attribute-row { margin-bottom: 0.6rem; }
            .attribute-label { display: block; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em; color: #64748b; font-weight: 700; margin-bottom: 0.2rem; }
            .attribute-value { font-size: 0.95rem; font-weight: 700; color: #0f172a; line-height: 1.45; }
            .empty-state { text-align: center; padding: 1.3rem 0.6rem; border: 1px dashed #cbd5e1; border-radius: 18px; background: #f8fafc; color: #64748b; }
            .empty-state-icon { font-size: 2rem; margin-bottom: 0.4rem; }
            .empty-state-title { font-size: 1rem; font-weight: 800; color: #0f172a; margin-bottom: 0.2rem; }
            .empty-state-copy { font-size: 0.9rem; color: #64748b; }
            .stButton > button { border-radius: 999px !important; padding: 0.55rem 0.95rem !important; font-weight: 700; }
            .stButton > button[kind="primary"] { background: #4f46e5 !important; color: white !important; border: none !important; }
            @media (max-width: 768px) {
                .block-container { padding-left: 0.7rem; padding-right: 0.7rem; }
                .directory-row { flex-direction: column; align-items: flex-start; }
                .detail-hero-card { flex-direction: column; align-items: flex-start; }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_directory_rows(members: List[Dict], selected_member_id: Optional[str]) -> None:
    if not members:
        st.markdown(
            """
            <div class="empty-state">
                <div class="empty-state-icon">📁</div>
                <div class="empty-state-title">No members match the current filters</div>
                <div class="empty-state-copy">Try adjusting the search terms or role filter.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    for member in members:
        member_id = str(member.get("member_id") or "")
        full_name = str(member.get("full_name") or "Unnamed Member")
        role = str(member.get("role") or "Member")
        status = str(member.get("status") or "Pending")
        email = str(member.get("email") or "—")
        phone = str(member.get("phone") or "—")
        initials = "".join(part[0].upper() for part in full_name.split()[:2]) or "M"

        if status.lower() in {"active", "probationary", "partial member", "full member"}:
            status_class = "pill-active"
        elif status.lower() == "pending":
            status_class = "pill-pending"
        else:
            status_class = "pill-inactive"
        role_class = "pill-role"

        with st.container(border=True):
            cols = st.columns([0.7, 2.0, 1.7, 0.9, 0.9, 0.7], gap="small")
            with cols[0]:
                st.markdown(f"<div class='avatar-circle'>{escape(initials)}</div>", unsafe_allow_html=True)
            with cols[1]:
                st.markdown(f"<div class='member-name'>{escape(full_name)}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='member-id'>{escape(member_id)}</div>", unsafe_allow_html=True)
            with cols[2]:
                st.markdown(f"<div class='member-id'>{escape(email)}</div>", unsafe_allow_html=True)
                st.markdown(f"<div class='member-id'>{escape(phone)}</div>", unsafe_allow_html=True)
            with cols[3]:
                st.markdown(f"<span class='pill {role_class}'>{escape(role)}</span>", unsafe_allow_html=True)
            with cols[4]:
                st.markdown(f"<span class='pill {status_class}'>{escape(status)}</span>", unsafe_allow_html=True)
            with cols[5]:
                if st.button("View", key=f"view_member_{member_id}", width="stretch"):
                    st.session_state["admin_docs_selected_member_id"] = member_id
                    st.session_state["admin_docs_selected_member_id"] = member_id
                    st.rerun()

            if selected_member_id and member_id == selected_member_id:
                st.caption("Selected for profile review")


def _render_membership_action_controls(member: Dict, acting_role: str, acting_user_id: str) -> None:
    member_id = str(member.get("member_id") or "")
    current_status = str(member.get("status") or "Pending")
    current_status_key = current_status.lower()

    if acting_role not in {"Secretary", "Chairperson"}:
        return

    st.markdown("#### Membership actions")
    if current_status_key in {"pending", "new"}:
        if st.button("Approve as Probation", key=f"approve_probation_{member_id}", width="stretch"):
            if st.dialog("Confirm approval"):
                pass
        if st.button("Reject Registration", key=f"reject_registration_{member_id}", width="stretch"):
            update_member_status(member_id, "Rejected", acting_user_id, acting_role, reason="Rejected by admin")
            st.success("Membership rejected successfully.")
            st.rerun()
    elif current_status_key in {"probationary", "probation", "probation member"}:
        if st.button("Promote to Partial Member", key=f"promote_partial_{member_id}", width="stretch"):
            update_member_status(member_id, "Partial Member", acting_user_id, acting_role, reason="Promoted by admin")
            st.success("Membership promoted successfully.")
            st.rerun()
    elif current_status_key in {"partial member", "partial"}:
        if st.button("Promote to Full Member", key=f"promote_full_{member_id}", width="stretch"):
            update_member_status(member_id, "Full Member", acting_user_id, acting_role, reason="Promoted by admin")
            st.success("Membership promoted successfully.")
            st.rerun()
    elif current_status_key in {"suspended", "suspension"}:
        if st.button("Reinstate Member", key=f"reinstate_{member_id}", width="stretch"):
            previous_status = str(member.get("previous_membership_status") or "Probationary")
            update_member_status(member_id, previous_status, acting_user_id, acting_role, reason="Reinstated by admin")
            st.success("Membership reinstated successfully.")
            st.rerun()
    elif current_status_key in {"active", "probationary", "partial member", "full member", "full", "partial"}:
        if st.button("Suspend Member", key=f"suspend_{member_id}", width="stretch"):
            update_member_status(member_id, "Suspended", acting_user_id, acting_role, reason="Suspended by admin")
            st.success("Membership suspended successfully.")
            st.rerun()
        if st.button("Terminate Membership", key=f"terminate_{member_id}", width="stretch"):
            update_member_status(member_id, "Terminated", acting_user_id, acting_role, reason="Terminated by admin")
            st.success("Membership terminated successfully.")
            st.rerun()

    if acting_role == "Chairperson":
        st.markdown("#### Chairperson enforcement")
        if current_status_key not in {"deleted", "terminated"}:
            if st.button("Delete Account", key=f"delete_account_{member_id}", width="stretch"):
                delete_member_account(member_id, acting_user_id, acting_role, reason="Account deleted by Chairperson")
                st.success("Account deleted successfully.")
                st.rerun()


def notifications_center_view() -> None:
    try:
        st.set_page_config(layout="wide", initial_sidebar_state="expanded")
    except Exception:
        pass

    _inject_admin_docs_css()
    st.markdown("<div class='admin-shell'>", unsafe_allow_html=True)
    st.markdown("<h1 class='page-title'>Notifications</h1>", unsafe_allow_html=True)
    st.markdown("<p class='page-caption'>Review your latest notifications, unread items, and recent system updates.</p>", unsafe_allow_html=True)

    user_role = st.session_state.get("user_role")
    user_id = st.session_state.get("user_id")
    if not user_id:
        st.info("You need to be signed in to view notifications.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    unread_count = get_unread_notification_count("member", user_id, recipient_role=user_role)
    st.metric("Unread", unread_count)
    if st.button("Mark all as read", width="content"):
        mark_all_notifications_read("member", user_id, recipient_role=user_role)
        st.success("All notifications marked as read.")
        st.rerun()

    notifications = get_notifications_for_user("member", user_id, recipient_role=user_role, limit=100)
    if not notifications:
        st.info("No notifications yet.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    for notification in notifications:
        is_read = bool(notification.get("is_read"))
        priority = str(notification.get("priority") or "Normal")
        with st.container(border=True):
            cols = st.columns([4, 1])
            with cols[0]:
                title = str(notification.get("title") or "Notification")
                body = str(notification.get("message") or "")
                st.markdown(f"<div style='font-weight:700; color:#0f172a;'>{escape(title)}</div>", unsafe_allow_html=True)
                st.caption(body)
                st.caption(f"Category: {escape(str(notification.get('category') or 'System'))} • Module: {escape(str(notification.get('module_name') or '-'))}")
            with cols[1]:
                st.caption(f"Priority: {escape(priority)}")
                if not is_read and st.button("Mark read", key=f"mark_read_{notification.get('id')}", width="stretch"):
                    mark_notification_read(int(notification.get("id")))
                    st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)


def reminder_engine_view() -> None:
    try:
        st.set_page_config(layout="wide", initial_sidebar_state="expanded")
    except Exception:
        pass

    _inject_admin_docs_css()
    st.markdown("<div class='admin-shell'>", unsafe_allow_html=True)
    st.markdown("<h1 class='page-title'>Reminder Engine</h1>", unsafe_allow_html=True)
    st.markdown("<p class='page-caption'>Run the shared reminder engine to generate scheduled reminders through the existing notification system.</p>", unsafe_allow_html=True)

    if st.button("Run reminder checks", width="content"):
        results = run_reminder_engine()
        st.success("Reminder checks completed.")
        st.json(results)

    st.caption("This engine reuses the shared notification and audit services and prevents duplicate reminders within the configured window.")
    st.markdown("</div>", unsafe_allow_html=True)


def audit_center_view() -> None:
    try:
        st.set_page_config(layout="wide", initial_sidebar_state="expanded")
    except Exception:
        pass

    _inject_admin_docs_css()
    st.markdown("<div class='admin-shell'>", unsafe_allow_html=True)
    st.markdown("<h1 class='page-title'>Executive Audit Dashboard</h1>", unsafe_allow_html=True)
    st.markdown("<p class='page-caption'>Track executive-level activity across membership, loans, savings, subscriptions, welfare, authentication, and administration using the existing audit log repository.</p>", unsafe_allow_html=True)

    user_role = st.session_state.get("user_role")
    allowed_roles = {"Chairperson", "Secretary", "Treasurer", "Vice Chairperson", "Welfare"}
    if user_role not in allowed_roles:
        st.info("You do not have access to the audit center.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    limit = st.selectbox("Display recent entries", options=[10, 25, 50, 100], index=2, key="audit_center_limit")
    audit_rows = fetch_enriched_audit_events(limit=limit)
    if not audit_rows:
        st.info("No audit events have been recorded yet.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    summary = build_audit_dashboard_summary(limit=max(limit, 200))
    metric_cols = st.columns(6)
    metric_payload = [
        ("Today's Activities", summary.get("today_activities", 0)),
        ("Total Audit Records", summary.get("total_audit_records", 0)),
        ("New Registrations", summary.get("new_member_registrations", 0)),
        ("Loans Approved", summary.get("loans_approved_today", 0)),
        ("Failed Logins", summary.get("failed_login_attempts", 0)),
        ("Suspended Accounts", summary.get("suspended_accounts", 0)),
    ]
    for col, (label, value) in zip(metric_cols, metric_payload):
        with col:
            st.markdown(f"<div class='metric-card'><div class='metric-label'>{escape(label)}</div><div class='metric-value'>{escape(str(value))}</div></div>", unsafe_allow_html=True)

    st.markdown("<div class='surface-card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Quick Filters</div>", unsafe_allow_html=True)
    filter_col_1, filter_col_2, filter_col_3, filter_col_4 = st.columns([1, 1, 1, 1.2], gap="small")
    with filter_col_1:
        module_filter = st.selectbox("Module", options=["All", "Membership", "Loans", "Savings", "Subscriptions", "Welfare", "Authentication", "Reports", "Administration", "Notifications", "Reminder Engine", "Audit System"], key="audit_module_filter")
    with filter_col_2:
        status_filter = st.selectbox("Status", options=["All", "Approved", "Rejected", "Pending", "Suspended", "Terminated", "Failed", "Updated", "Recorded"], key="audit_status_filter")
    with filter_col_3:
        action_filter = st.selectbox("Action", options=["All", "Approved", "Rejected", "Updated", "Recorded", "Login failed", "Member registered", "Account suspended", "Loan approved", "Payment"], key="audit_action_filter")
    with filter_col_4:
        search_term = st.text_input("Search", placeholder="Member, loan, ref, officer, remarks", key="audit_search_filter")

    filtered_rows = []
    for row in audit_rows:
        entity_type = str(row.get("entity_type") or "").lower()
        action_text = str(row.get("action") or "").lower()
        details_text = str(row.get("details") or "").lower()
        role_text = str(row.get("role") or "").lower()
        member_name = str(row.get("member_name") or "").lower()
        member_number = str(row.get("member_number") or "").lower()
        remarks_text = str(row.get("remarks") or "").lower()
        entity_id = str(row.get("entity_id") or "").lower()
        status_text = str(row.get("status") or "").lower()
        if module_filter != "All":
            module_key = module_filter.lower()
            if module_key == "membership" and "member" not in entity_type and "registration" not in action_text:
                continue
            if module_key == "loans" and "loan" not in entity_type and "loan" not in action_text:
                continue
            if module_key == "savings" and "saving" not in entity_type and "savings" not in action_text:
                continue
            if module_key == "subscriptions" and "subscription" not in entity_type and "subscription" not in action_text and "payment" not in action_text:
                continue
            if module_key == "welfare" and "welfare" not in entity_type and "welfare" not in action_text:
                continue
            if module_key == "authentication" and "login" not in action_text and "auth" not in entity_type:
                continue
            if module_key == "reports" and "report" not in entity_type and "report" not in action_text:
                continue
            if module_key == "administration" and "admin" not in entity_type and "admin" not in action_text:
                continue
            if module_key == "notifications" and "notification" not in entity_type and "notification" not in action_text:
                continue
            if module_key == "reminder engine" and "reminder" not in entity_type and "reminder" not in action_text:
                continue
            if module_key == "audit system" and "audit" not in entity_type and "audit" not in action_text:
                continue
        if status_filter != "All" and status_filter.lower() != status_text:
            continue
        if action_filter != "All" and action_filter.lower() not in action_text and action_filter.lower() not in details_text:
            continue
        if search_term:
            needle = search_term.lower()
            if needle not in " ".join([member_name, member_number, entity_id, action_text, details_text, role_text, remarks_text]):
                continue
        filtered_rows.append(row)

    if not filtered_rows:
        st.info("No matching audit activity found for the selected filters.")
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        return

    st.markdown("<div class='section-title'>Security Alerts</div>", unsafe_allow_html=True)
    alerts = []
    for row in filtered_rows:
        action_text = str(row.get("action") or "").lower()
        details_text = str(row.get("details") or "").lower()
        if "failed" in action_text or "error" in details_text or "suspend" in action_text or "suspended" in details_text:
            alerts.append(row)
    if alerts:
        for alert in alerts[:5]:
            st.markdown(f"<div class='audit-row'><div class='audit-row-header'><div class='audit-row-title'>{escape(str(alert.get('action') or 'Alert'))}</div><span class='chip chip-critical'>Security Alert</span></div><div class='audit-row-subtitle'>{escape(str(alert.get('remarks') or alert.get('details') or ''))}</div></div>", unsafe_allow_html=True)
    else:
        st.caption("No unusual activity detected in the current view.")

    st.markdown("<div class='section-title'>Executive Activity Timeline</div>", unsafe_allow_html=True)
    for row in filtered_rows[:8]:
        created_at = row.get("created_at")
        created_str = created_at.strftime("%Y-%m-%d %H:%M") if created_at is not None and hasattr(created_at, "strftime") else str(created_at or "")
        st.markdown(f"<div class='audit-row'><div class='audit-row-header'><div class='audit-row-title'>{escape(str(row.get('action') or 'Audit Event'))}</div><span class='chip chip-approved'>{escape(str(row.get('status') or 'Recorded'))}</span></div><div class='audit-row-subtitle'>{escape(created_str)} • {escape(str(row.get('member_name') or '—'))} • {escape(str(row.get('member_number') or '—'))}</div><div class='audit-row-subtitle'>{escape(str(row.get('remarks') or row.get('details') or ''))}</div></div>", unsafe_allow_html=True)

    st.markdown("<div class='section-title'>Detailed Audit Records</div>", unsafe_allow_html=True)
    for row in filtered_rows[:20]:
        created_at = row.get("created_at")
        created_str = created_at.strftime("%Y-%m-%d %H:%M") if created_at is not None and hasattr(created_at, "strftime") else str(created_at or "")
        status = str(row.get("status") or "Recorded")
        chip_class = "chip-approved" if status.lower() == "approved" else "chip-rejected" if status.lower() == "rejected" else "chip-pending" if status.lower() == "pending" else "chip-warning" if status.lower() in {"updated", "recorded"} else "chip-critical"
        action_text = str(row.get("action") or "Audit Event")
        entity_type = str(row.get("entity_type") or "Audit")
        details_text = str(row.get("remarks") or row.get("details") or "—")
        member_name = str(row.get("member_name") or "—")
        member_number = str(row.get("member_number") or "—")

        if "subscription" in entity_type.lower() or "proof" in action_text.lower() or "subscription" in action_text.lower():
            amount_value = str(row.get("current_state") or "—")
            if amount_value == "—" and "amount" in details_text.lower():
                amount_value = details_text
            extra_fields_html = (
                f"<div class='attribute-row'><span class='attribute-label'>Member Name</span><div class='attribute-value'>{escape(member_name)}</div></div>"
                f"<div class='attribute-row'><span class='attribute-label'>Member ID</span><div class='attribute-value'>{escape(member_number)}</div></div>"
                f"<div class='attribute-row'><span class='attribute-label'>Amount Paid</span><div class='attribute-value'>{escape(amount_value)}</div></div>"
                f"<div class='attribute-row'><span class='attribute-label'>Date</span><div class='attribute-value'>{escape(created_str)}</div></div>"
            )
        else:
            extra_fields_html = (
                f"<div class='attribute-row'><span class='attribute-label'>Member Number</span><div class='attribute-value'>{escape(member_number)}</div></div>"
                f"<div class='attribute-row'><span class='attribute-label'>Reference</span><div class='attribute-value'>{escape(str(row.get('entity_id') or '—'))}</div></div>"
                f"<div class='attribute-row'><span class='attribute-label'>Previous State</span><div class='attribute-value'>{escape(str(row.get('previous_state') or '—'))}</div></div>"
                f"<div class='attribute-row'><span class='attribute-label'>Current State</span><div class='attribute-value'>{escape(str(row.get('current_state') or '—'))}</div></div>"
            )

        st.markdown(
            f"<div class='audit-row'><div class='audit-row-header'><div class='audit-row-title'>{escape(action_text)}</div><span class='chip {chip_class}'>{escape(status)}</span></div><div class='audit-row-subtitle'>{escape(created_str)} • Module: {escape(entity_type)} • Member: {escape(member_name)}</div>{extra_fields_html}<div class='attribute-row'><span class='attribute-label'>Performed By</span><div class='attribute-value'>{escape(str(row.get('actor_name') or row.get('role') or 'System'))}</div></div><div class='attribute-row'><span class='attribute-label'>Role</span><div class='attribute-value'>{escape(str(row.get('role') or 'System'))}</div></div><div class='attribute-row'><span class='attribute-label'>Remarks</span><div class='attribute-value'>{escape(details_text)}</div></div></div>",
            unsafe_allow_html=True,
        )

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def admin_docs_view():
    try:
        st.set_page_config(layout="wide", initial_sidebar_state="expanded")
    except Exception:
        pass

    _inject_admin_docs_css()
    st.markdown("<div class='admin-shell'>", unsafe_allow_html=True)
    st.markdown("<h1 class='page-title'>Administrative Hub</h1>", unsafe_allow_html=True)
    st.markdown("<p class='page-caption'>Manage member records, review operational metadata, and access secure document vaults.</p>", unsafe_allow_html=True)

    user_role = st.session_state.get("user_role")
    user_name = st.session_state.get("user_name")

    allowed_roles = {"Chairperson", "Secretary", "Treasurer", "Vice Chairperson", "Welfare"}
    if user_role not in allowed_roles:
        st.info("You do not have access to the admin directory or document repository.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    ensure_member_profile_columns()

    with st.spinner("Loading directory data..."):
        members = fetch_member_directory()

    search_term = st.text_input("🔍 Search members by name, ID, or email...", key="admin_docs_search", placeholder="Search members")
    search_col, filter_col = st.columns([1.7, 1.0], gap="small")
    with search_col:
        search_value = search_term.strip().lower()
    with filter_col:
        filter_value = st.selectbox(
            "Filter by Role/Status",
            options=["All", "Active", "Pending", "Probationary", "Partial Member", "Full Member", "Chairperson", "Secretary", "Treasurer", "Vice Chairperson", "Welfare", "Member"],
            key="admin_docs_filter",
        )

    filtered_members = []
    for member in members:
        member_id = str(member.get("member_id") or "")
        full_name = str(member.get("full_name") or "")
        email = str(member.get("email") or "")
        role = str(member.get("role") or "")
        status = str(member.get("status") or "")
        if search_value and not any(search_value in value.lower() for value in [full_name, member_id, email]):
            continue
        if filter_value != "All":
            if filter_value in {"Active", "Pending", "Probationary", "Partial Member", "Full Member"} and filter_value.lower() not in status.lower():
                continue
            if filter_value in {"Chairperson", "Secretary", "Treasurer", "Vice Chairperson", "Welfare", "Member"} and filter_value.lower() not in role.lower():
                continue
        filtered_members.append(member)

    selected_member_id = st.session_state.get("admin_docs_selected_member_id")
    if selected_member_id not in {str(member.get("member_id") or "") for member in filtered_members}:
        selected_member_id = str(filtered_members[0].get("member_id") or "") if filtered_members else None
        st.session_state["admin_docs_selected_member_id"] = selected_member_id

    st.markdown("<div class='surface-card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Member Directory</div>", unsafe_allow_html=True)
    _render_directory_rows(filtered_members, selected_member_id)
    st.markdown("</div>", unsafe_allow_html=True)

    if user_role == "Chairperson":
        pending_members = [row for row in filtered_members if str(row.get("status") or "").lower() in {"pending", "new"}]
        st.markdown("<div class='surface-card'>", unsafe_allow_html=True)
        st.markdown("<div class='section-title'>Pending Registration Queue</div>", unsafe_allow_html=True)
        if pending_members:
            for member in pending_members:
                member_id = str(member.get("member_id") or "")
                full_name = str(member.get("full_name") or "Unnamed Member")
                email = str(member.get("email") or "—")
                phone = str(member.get("phone") or "—")
                with st.container(border=True):
                    cols = st.columns([2.2, 1.0], gap="small")
                    with cols[0]:
                        st.markdown(f"**{escape(full_name)}**")
                        st.caption(f"{escape(email)} • {escape(phone)}")
                    with cols[1]:
                        if st.button("Approve", key=f"approve_{member_id}"):
                            approve_new_registration(member_id, st.session_state.get("user_id") or "", user_role or "Chairperson")
                            st.toast(f"Approved registration for {member_id}", icon="✅")
                            st.rerun()
        else:
            st.markdown(
                """
                <div class='empty-state'>
                    <div class='empty-state-icon'>✅</div>
                    <div class='empty-state-title'>No pending approvals</div>
                    <div class='empty-state-copy'>New registrations will appear here once submitted.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        st.markdown("</div>", unsafe_allow_html=True)

    if selected_member_id:
        selected_member_detail = _resolve_member_profile_detail(selected_member_id, filtered_members, members)
        if selected_member_detail is None:
            selected_member_detail = members[0] if members else None

        if selected_member_detail is None:
            st.error("Unable to load the selected member's profile. Please try again.")
            return

        st.markdown("<div class='surface-card'>", unsafe_allow_html=True)
        st.markdown("<div class='section-title'>Member Profile Summary</div>", unsafe_allow_html=True)
        _render_member_profile_summary(selected_member_detail)
        action_col_a, action_col_b, action_col_c = st.columns([1, 1, 1], gap="small")
        with action_col_a:
            if st.button("Edit Member Profile", width="stretch", type="primary"):
                st.session_state["admin_docs_edit_mode"] = True
                st.rerun()
        with action_col_b:
            pdf_bytes = build_member_profile_pdf(selected_member_detail)
            st.download_button(
                label="Download Member Profile PDF",
                data=pdf_bytes,
                file_name=f"member_{selected_member_detail.get('member_id', 'profile')}.pdf" if selected_member_detail else "member_profile.pdf",
                mime="application/pdf",
                key="admin_docs_download_pdf",
                width="stretch",
            )
        with action_col_c:
            _render_membership_action_controls(selected_member_detail, user_role, st.session_state.get("user_id") or "")
        st.markdown("</div>", unsafe_allow_html=True)

        edit_mode = st.session_state.get("admin_docs_edit_mode", False)
        if edit_mode and user_role == "Chairperson":
            st.markdown("<div class='surface-card'>", unsafe_allow_html=True)
            st.markdown("<div class='section-title'>Edit Member Profile</div>", unsafe_allow_html=True)
            selected_member_detail = fetch_member_record(selected_member_id) or selected_member_detail
            with st.form("chairperson_member_profile_form"):
                col_a, col_b = st.columns(2, gap="medium")
                with col_a:
                    full_name = st.text_input("Full name", value=str(selected_member_detail.get("full_name") or ""), key="chairperson_full_name")
                    email = st.text_input("Email", value=str(selected_member_detail.get("email") or ""), key="chairperson_email")
                    phone = st.text_input("Phone", value=str(selected_member_detail.get("phone") or ""), key="chairperson_phone")
                    safe_dob = _normalize_join_date(selected_member_detail.get("date_of_birth"))
                    safe_dob = coerce_date_input_value(safe_dob, date(1900, 1, 1), date(date.today().year, 12, 31))
                    date_of_birth_value = st.date_input("Date of birth", value=safe_dob, min_value=date(1900, 1, 1), max_value=date(date.today().year, 12, 31), key="chairperson_date_of_birth")
                    gender = st.text_input("Gender", value=str(selected_member_detail.get("gender") or ""), key="chairperson_gender")
                    address = st.text_input("Address", value=str(selected_member_detail.get("address") or ""), key="chairperson_address")
                    city = st.text_input("City", value=str(selected_member_detail.get("city") or ""), key="chairperson_city")
                    country = st.text_input("Country", value=str(selected_member_detail.get("country") or ""), key="chairperson_country")
                    nationality = st.text_input("Nationality", value=str(selected_member_detail.get("nationality") or ""), key="chairperson_nationality")
                with col_b:
                    role_options = ["Member", "Secretary", "Treasurer", "Chairperson", "Vice Chairperson", "Welfare"]
                    selected_role = str(selected_member_detail.get("role") or "")
                    new_role = st.selectbox("Role", options=role_options, index=role_options.index(selected_role) if selected_role in role_options else 0, key="chairperson_role")
                    status_options = ["Pending", "Probationary", "Active", "Partial Member", "Full Member"]
                    selected_status = str(selected_member_detail.get("status") or "")
                    new_status = st.selectbox("Status", options=status_options, index=status_options.index(selected_status) if selected_status in status_options else 0, key="chairperson_status")
                    safe_join_date = _normalize_join_date(selected_member_detail.get("join_date"))
                    safe_join_date = coerce_date_input_value(safe_join_date, date(1900, 1, 1), date(date.today().year, 12, 31))
                    join_date_value = st.date_input("Join date", value=safe_join_date, min_value=date(1900, 1, 1), max_value=date(date.today().year, 12, 31), key="chairperson_join_date")
                    occupation = st.text_input("Occupation", value=str(selected_member_detail.get("occupation") or ""), key="chairperson_occupation")
                    employer = st.text_input("Employer", value=str(selected_member_detail.get("employer") or ""), key="chairperson_employer")
                    national_id = st.text_input("National ID", value=str(selected_member_detail.get("national_id") or ""), key="chairperson_national_id")
                    notes = st.text_area("Admin notes", value=str(selected_member_detail.get("notes") or ""), key="chairperson_notes")
                st.markdown("---")
                st.markdown("<div class='section-title'>Emergency Contact</div>", unsafe_allow_html=True)
                next_of_kin_name = st.text_input("Next of kin name", value=str(selected_member_detail.get("next_of_kin_name") or ""), key="chairperson_next_of_kin_name")
                next_of_kin_relationship = st.text_input("Next of kin relationship", value=str(selected_member_detail.get("next_of_kin_relationship") or ""), key="chairperson_next_of_kin_relationship")
                next_of_kin_phone = st.text_input("Next of kin phone", value=str(selected_member_detail.get("next_of_kin_phone") or ""), key="chairperson_next_of_kin_phone")
                emergency_contact_name = st.text_input("Emergency contact name", value=str(selected_member_detail.get("emergency_contact_name") or ""), key="chairperson_emergency_contact_name")
                emergency_contact_phone = st.text_input("Emergency contact phone", value=str(selected_member_detail.get("emergency_contact_phone") or ""), key="chairperson_emergency_contact_phone")

                save_clicked = st.form_submit_button("Save Member Profile")

            if save_clicked:
                submitted_values = {
                    "full_name": (full_name or "").strip() or None,
                    "email": (email or "").strip() or None,
                    "phone": (phone or "").strip() or None,
                    "role": new_role,
                    "status": new_status,
                    "join_date": join_date_value,
                    "notes": (notes or "").strip() or None,
                    "date_of_birth": date_of_birth_value,
                    "gender": (gender or "").strip() or None,
                    "address": (address or "").strip() or None,
                    "city": (city or "").strip() or None,
                    "country": (country or "").strip() or None,
                    "nationality": (nationality or "").strip() or None,
                    "occupation": (occupation or "").strip() or None,
                    "employer": (employer or "").strip() or None,
                    "national_id": (national_id or "").strip() or None,
                    "next_of_kin_name": (next_of_kin_name or "").strip() or None,
                    "next_of_kin_relationship": (next_of_kin_relationship or "").strip() or None,
                    "next_of_kin_phone": (next_of_kin_phone or "").strip() or None,
                    "emergency_contact_name": (emergency_contact_name or "").strip() or None,
                    "emergency_contact_phone": (emergency_contact_phone or "").strip() or None,
                }
                changed_values = _build_changed_profile_update_payload(selected_member_detail, submitted_values)
                update_member_profile(
                    selected_member_detail["member_id"],
                    changed_values.get("full_name"),
                    changed_values.get("email"),
                    changed_values.get("phone"),
                    changed_values.get("role"),
                    changed_values.get("status"),
                    changed_values.get("join_date"),
                    changed_values.get("notes"),
                    changed_values.get("date_of_birth"),
                    changed_values.get("gender"),
                    changed_values.get("address"),
                    changed_values.get("city"),
                    changed_values.get("country"),
                    changed_values.get("nationality"),
                    changed_values.get("occupation"),
                    changed_values.get("employer"),
                    changed_values.get("national_id"),
                    changed_values.get("next_of_kin_name"),
                    changed_values.get("next_of_kin_relationship"),
                    changed_values.get("next_of_kin_phone"),
                    changed_values.get("emergency_contact_name"),
                    changed_values.get("emergency_contact_phone"),
                )
                st.session_state["admin_docs_edit_mode"] = False
                st.success("Member profile updated successfully.")
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='surface-card'>", unsafe_allow_html=True)
    st.markdown("<div class='section-title'>Document Repository</div>", unsafe_allow_html=True)
    st.caption("Secure vault for operational records, meeting minutes, and member files.")
    if user_role == "Secretary":
        uploaded_file = st.file_uploader("Upload a document", type=None, accept_multiple_files=False)
        if uploaded_file is not None:
            title = st.text_input("Document title", value=uploaded_file.name)
            if st.button("Upload Document", width="stretch"):
                title_text = (title or "").strip()
                if not title_text:
                    st.toast("Please provide a title for the document.", icon="⚠️")
                else:
                    file_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uploaded_file.name}"
                    save_path = os.path.join(UPLOAD_DIR, file_name)
                    with open(save_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    save_document_record(title_text, save_path, user_name or "Secretary")
                    st.toast("Document uploaded successfully.", icon="✅")
                    st.rerun()

    documents = fetch_documents()
    if documents:
        for doc in documents:
            title = str(doc.get("title") or "Untitled")
            file_url = str(doc.get("file_url") or "")
            uploaded_at = doc.get("uploaded_at")
            uploaded_at_str = uploaded_at.strftime("%Y-%m-%d %H:%M") if uploaded_at is not None and hasattr(uploaded_at, "strftime") else str(uploaded_at or "-")
            with st.container(border=True):
                col_a, col_b = st.columns([2.2, 1.0], gap="small")
                with col_a:
                    st.markdown(f"**{escape(title)}**")
                    st.caption(f"Uploaded {escape(uploaded_at_str)}")
                with col_b:
                    if os.path.exists(file_url):
                        with open(file_url, "rb") as handle:
                            st.download_button("Download", data=handle.read(), file_name=os.path.basename(file_url), mime="application/octet-stream", width="stretch")
                    else:
                        st.info("Unavailable")
    else:
        st.markdown(
            """
            <div class='empty-state'>
                <div class='empty-state-icon'>🗂️</div>
                <div class='empty-state-title'>No Documents Uploaded</div>
                <div class='empty-state-copy'>Upload a file to begin building the operational repository.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    admin_docs_view()
