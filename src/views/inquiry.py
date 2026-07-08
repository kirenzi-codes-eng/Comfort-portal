from datetime import datetime
from functools import lru_cache
from html import escape
from typing import Dict, List

import streamlit as st

from src.database.connection import execute_query


def _safe_rerun() -> None:
    """Try to trigger a Streamlit rerun; fall back to a session-state toggle."""
    try:
        rerun_fn = getattr(st, "experimental_rerun", None)
        if callable(rerun_fn):
            rerun_fn()
            return
    except Exception:
        pass

    try:
        st.session_state.setdefault("_rerun_trigger", False)
        st.session_state["_rerun_trigger"] = not st.session_state["_rerun_trigger"]
    except Exception:
        return


def fetch_member_inquiries(member_id: str) -> List[Dict]:
    ts_col = _get_inquiry_timestamp_column() or _ensure_inquiry_timestamp_column()
    if ts_col is None:
        return []
    query = (
        f"SELECT i.ticket_id, i.member_id, COALESCE(m.full_name, '') AS member_name, i.subject, i.message, i.status, {ts_col} AS created_at "
        f"FROM inquiries i LEFT JOIN members m ON m.member_id = i.member_id WHERE i.member_id = %s ORDER BY {ts_col} DESC;"
    )
    rows = execute_query(query, params=(member_id,), fetch=True)
    return rows or []


def fetch_all_inquiries() -> List[Dict]:
    ts_col = _get_inquiry_timestamp_column() or _ensure_inquiry_timestamp_column()
    if ts_col is None:
        return []
    query = (
        f"SELECT i.ticket_id, i.member_id, COALESCE(m.full_name, '') AS member_name, i.subject, i.message, i.status, {ts_col} AS created_at "
        f"FROM inquiries i LEFT JOIN members m ON m.member_id = i.member_id ORDER BY {ts_col} DESC;"
    )
    rows = execute_query(query, params=None, fetch=True)
    return rows or []


def submit_inquiry(member_id: str, subject: str, message: str) -> None:
    ts_col = _get_inquiry_timestamp_column() or _ensure_inquiry_timestamp_column() or "created_at"
    execute_query(
        f"INSERT INTO inquiries (member_id, subject, message, status, {ts_col}) VALUES (%s, %s, %s, %s, %s);",
        params=(member_id, subject, message, "Open", datetime.utcnow()),
        fetch=False,
    )


@lru_cache(maxsize=1)
def _get_inquiry_timestamp_column() -> str | None:
    try:
        rows = execute_query(
            "SELECT column_name FROM information_schema.columns WHERE table_name = %s AND column_name = ANY(%s);",
            params=("inquiries", ["created_at", "submitted_date"]),
            fetch=True,
        )
        if not rows:
            return None
        return rows[0]["column_name"]
    except Exception:
        return None


def _ensure_inquiry_timestamp_column() -> str | None:
    """Ensure there is a timestamp column for inquiries; prefer `created_at`."""
    try:
        if _get_inquiry_timestamp_column() == "created_at":
            return "created_at"
        execute_query(
            "ALTER TABLE inquiries ADD COLUMN IF NOT EXISTS created_at TIMESTAMP;",
            params=None,
            fetch=False,
        )
        try:
            _get_inquiry_timestamp_column.cache_clear()
        except Exception:
            pass
        return _get_inquiry_timestamp_column() or "created_at"
    except Exception:
        return None


def resolve_inquiry(inquiry_id: int) -> None:
    execute_query(
        "UPDATE inquiries SET status = 'Resolved', resolved_at = %s WHERE ticket_id = %s;",
        params=(datetime.utcnow(), inquiry_id),
        fetch=False,
    )


def _bucket_for_status(status: str | None) -> str:
    normalized = (status or "").strip().lower()
    if normalized in {"resolved", "complete", "closed"}:
        return "resolved"
    if normalized in {"pending", "pending review", "in progress", "awaiting review"}:
        return "pending"
    return "open"


def _status_display(status: str | None) -> str:
    bucket = _bucket_for_status(status)
    if bucket == "resolved":
        return "Resolved"
    if bucket == "pending":
        return "Pending Review"
    return "Open"


def _member_label(inquiry: Dict) -> str:
    name = str(inquiry.get("member_name") or "").strip()
    member_id = str(inquiry.get("member_id") or "").strip()
    if name and member_id:
        return f"{name} • {member_id}"
    if name:
        return name
    if member_id:
        return member_id
    return "Unknown member"


def _filter_inquiries(inquiries: List[Dict], query: str, bucket: str) -> List[Dict]:
    search_term = (query or "").strip().lower()
    filtered = [item for item in inquiries if _bucket_for_status(item.get("status")) == bucket]
    if not search_term:
        return filtered
    return [
        item
        for item in filtered
        if search_term in " ".join(
            [
                str(item.get("ticket_id") or ""),
                str(item.get("member_id") or ""),
                str(item.get("member_name") or ""),
                str(item.get("subject") or ""),
                str(item.get("message") or ""),
                str(item.get("status") or ""),
            ]
        ).lower()
    ]


def _render_inquiry_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            color-scheme: light;
        }
        .block-container {
            max-width: 1200px !important;
            margin: 0 auto !important;
            padding-top: 1rem !important;
        }
        .inquiry-shell {
            display: flex;
            flex-direction: column;
            gap: 1rem;
            font-family: 'Inter', 'Plus Jakarta Sans', 'Segoe UI', sans-serif;
        }
        .hero-card,
        .metric-card,
        .ticket-card,
        .empty-state-card,
        .form-card {
            box-sizing: border-box;
            width: 100%;
            overflow-wrap: anywhere;
        }
        .hero-card {
            background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
            border: 1px solid #e2e8f0;
            border-radius: 20px;
            padding: 1.3rem 1.4rem;
            box-shadow: 0 14px 36px rgba(15, 23, 42, 0.06);
        }
        .hero-title {
            margin: 0;
            font-size: clamp(1.55rem, 2.2vw, 2.15rem);
            color: #0f172a;
            font-weight: 800;
        }
        .hero-copy {
            margin: 0.3rem 0 0;
            color: #475569;
            font-size: 0.98rem;
            line-height: 1.55;
        }
        .metric-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 16px;
            padding: 1rem 1rem 0.95rem;
            min-height: 118px;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04);
        }
        .metric-label {
            font-size: 0.82rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            color: #64748b;
            margin-bottom: 0.45rem;
        }
        .metric-value {
            font-size: 1.55rem;
            font-weight: 800;
            color: #0f172a;
            margin-bottom: 0.25rem;
        }
        .metric-caption {
            font-size: 0.9rem;
            color: #64748b;
            line-height: 1.45;
        }
        .metric-accent {
            display: inline-flex;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 0.45rem;
            vertical-align: middle;
        }
        .metric-accent-open { background: #10b981; }
        .metric-accent-pending { background: #f59e0b; }
        .metric-accent-resolved { background: #3b82f6; }
        .action-row {
            display: flex;
            gap: 0.75rem;
            align-items: center;
            flex-wrap: wrap;
            margin-bottom: 0.15rem;
        }
        .primary-action button {
            background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%) !important;
            border: none !important;
            color: #ffffff !important;
            border-radius: 999px !important;
            padding: 0.65rem 1rem !important;
            font-weight: 700 !important;
            box-shadow: 0 10px 24px rgba(37, 99, 235, 0.2) !important;
        }
        .ticket-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 16px;
            padding: 1rem 1rem 0.95rem;
            margin-bottom: 0.8rem;
            box-shadow: 0 8px 20px rgba(15, 23, 42, 0.04);
        }
        .ticket-card:hover {
            border-color: #cbd5e1;
            transform: translateY(-1px);
            transition: all 160ms ease;
        }
        .ticket-badge {
            display: inline-flex;
            align-items: center;
            border-radius: 999px;
            padding: 0.25rem 0.65rem;
            font-size: 0.75rem;
            font-weight: 700;
            margin-bottom: 0.55rem;
        }
        .ticket-badge-open {
            background: #ecfdf5;
            color: #047857;
        }
        .ticket-badge-pending {
            background: #fffbeb;
            color: #b45309;
        }
        .ticket-badge-resolved {
            background: #eff6ff;
            color: #1d4ed8;
        }
        .ticket-title {
            margin: 0 0 0.35rem;
            font-size: 1rem;
            font-weight: 700;
            color: #0f172a;
        }
        .ticket-copy {
            margin: 0;
            color: #475569;
            line-height: 1.6;
        }
        .ticket-meta {
            margin-top: 0.6rem;
            font-size: 0.88rem;
            color: #64748b;
        }
        .empty-state-card {
            background: linear-gradient(135deg, #f8fafc 0%, #ffffff 100%);
            border: 1px dashed #cbd5e1;
            border-radius: 18px;
            padding: 1.5rem 1rem;
            text-align: center;
            box-shadow: inset 0 1px 0 rgba(255,255,255,0.8);
        }
        .empty-state-emoji {
            font-size: 2.35rem;
            margin-bottom: 0.45rem;
        }
        .empty-state-title {
            margin: 0;
            font-size: 1.15rem;
            font-weight: 700;
            color: #0f172a;
        }
        .empty-state-copy {
            margin: 0.35rem auto 0;
            max-width: 560px;
            color: #64748b;
            line-height: 1.6;
        }
        .form-card {
            background: #ffffff;
            border: 1px solid #e2e8f0;
            border-radius: 18px;
            padding: 1rem;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.04);
        }
        @media screen and (max-width: 768px) {
            .hero-card {
                padding: 1rem;
                border-radius: 16px;
            }
            .metric-card,
            .ticket-card,
            .form-card {
                border-radius: 14px;
            }
            .primary-action button {
                width: 100% !important;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_empty_state(title: str, message: str) -> None:
    st.markdown(
        f"""
        <div class='empty-state-card'>
            <div class='empty-state-emoji'>📬</div>
            <div class='empty-state-title'>{escape(title)}</div>
            <div class='empty-state-copy'>{escape(message)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_ticket_card(inquiry: Dict, allow_resolve: bool = False) -> None:
    bucket = _bucket_for_status(inquiry.get("status"))
    badge_class = f"ticket-badge ticket-badge-{bucket}"
    status_text = _status_display(inquiry.get("status"))
    title = str(inquiry.get("subject") or "Untitled request")
    message = str(inquiry.get("message") or "No details provided yet.")
    created_at = str(inquiry.get("created_at") or "-")
    member_line = _member_label(inquiry)

    st.markdown(
        f"""
        <div class='ticket-card'>
            <div class='{badge_class}'>{escape(status_text)}</div>
            <div class='ticket-title'>{escape(title)}</div>
            <div class='ticket-copy'>{escape(message)}</div>
            <div class='ticket-meta'>{escape(member_line)} • Submitted: {escape(created_at)}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if allow_resolve:
        if st.button("Mark as Resolved", key=f"resolve_{inquiry.get('ticket_id')}"):
            resolve_inquiry(inquiry["ticket_id"])
            st.toast("Inquiry marked as resolved.", icon="✅")
            _safe_rerun()


def inquiry_view() -> None:
    _render_inquiry_styles()

    st.markdown('<div class="inquiry-shell">', unsafe_allow_html=True)
    st.markdown(
        """
        <div class='hero-card'>
            <h1 class='hero-title'>Inquiry Help Desk</h1>
            <p class='hero-copy'>Track platform feedback, submit administrative tickets, and monitor active operational inquiries.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    user_id = st.session_state.get("user_id")
    user_role = st.session_state.get("user_role")

    if not user_id:
        st.info("Please log in to submit or review inquiries.")
        st.markdown('</div>', unsafe_allow_html=True)
        return

    executive_roles = {"Chairperson", "Secretary", "Treasurer"}
    inquiries = fetch_all_inquiries() if user_role in executive_roles else fetch_member_inquiries(user_id)
    open_count = sum(1 for item in inquiries if _bucket_for_status(item.get("status")) == "open")
    pending_count = sum(1 for item in inquiries if _bucket_for_status(item.get("status")) == "pending")
    resolved_count = sum(1 for item in inquiries if _bucket_for_status(item.get("status")) == "resolved")

    metric_cols = st.columns(3)
    metric_content = [
        ("Open Tickets", open_count, "open", "Active requests that need action now."),
        ("Pending Review", pending_count, "pending", "Awaiting a follow-up or decision."),
        ("Resolved Inquiries", resolved_count, "resolved", "Closed and archived successfully."),
    ]

    for col, (label, value, accent, caption) in zip(metric_cols, metric_content):
        with col:
            with st.container(border=True):
                st.markdown(
                    f"""
                    <div class='metric-card'>
                        <div class='metric-label'><span class='metric-accent metric-accent-{accent}'></span>{escape(label)}</div>
                        <div class='metric-value'>{escape(str(value))}</div>
                        <div class='metric-caption'>{escape(caption)}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

    action_col_left, action_col_right = st.columns([2.4, 1.0])
    with action_col_left:
        search_query = st.text_input(
            "🔍 Filter inquiries by ID, keyword, or user...",
            placeholder="Search inquiries",
            label_visibility="collapsed",
        )
    with action_col_right:
        with st.container():
            st.markdown('<div class="primary-action">', unsafe_allow_html=True)
            if st.button("➕ Open New Ticket", use_container_width=True):
                st.session_state["show_ticket_form"] = True
            st.markdown('</div>', unsafe_allow_html=True)

    if st.session_state.get("show_ticket_form", False) or user_role not in executive_roles:
        with st.container(border=True):
            st.markdown(
                """
                <div class='form-card'>
                    <div style='font-weight: 700; color: #0f172a; margin-bottom: 0.4rem;'>Create a support request</div>
                    <div style='color: #64748b; margin-bottom: 0.8rem;'>Share the issue clearly so the team can respond faster.</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.form("inquiry_form"):
                subject = st.text_input("Subject", placeholder="Briefly describe the issue")
                message = st.text_area("Message", placeholder="Add context, impact, and any relevant timeframe", height=135)
                submitted = st.form_submit_button("Submit Inquiry")

            if submitted:
                if not subject.strip() or not message.strip():
                    st.toast("Subject and message are required.", icon="⚠️")
                else:
                    submit_inquiry(user_id, subject.strip(), message.strip())
                    st.toast("Inquiry submitted.", icon="✅")
                    st.session_state["show_ticket_form"] = False
                    _safe_rerun()

    open_tab, pending_tab, resolved_tab = st.tabs(["📥 Open Inquiries", "⏳ Pending Response", "✅ Resolved Archive"])

    with open_tab:
        open_inquiries = _filter_inquiries(inquiries, search_query, "open")
        if open_inquiries:
            for inquiry in open_inquiries:
                _render_ticket_card(inquiry, allow_resolve=user_role in executive_roles)
        else:
            _render_empty_state(
                "All Quiet Here",
                "There are no active or open inquiries assigned to your queue at this moment. If you need assistance, submit a new ticket above.",
            )

    with pending_tab:
        pending_inquiries = _filter_inquiries(inquiries, search_query, "pending")
        if pending_inquiries:
            for inquiry in pending_inquiries:
                _render_ticket_card(inquiry, allow_resolve=user_role in executive_roles)
        else:
            _render_empty_state(
                "Nothing Waiting",
                "No pending responses are waiting for review right now.",
            )

    with resolved_tab:
        resolved_inquiries = _filter_inquiries(inquiries, search_query, "resolved")
        if resolved_inquiries:
            for inquiry in resolved_inquiries:
                _render_ticket_card(inquiry, allow_resolve=False)
        else:
            _render_empty_state(
                "Archive Is Clear",
                "Resolved tickets will appear here once they are closed out.",
            )

    st.markdown('</div>', unsafe_allow_html=True)


if __name__ == "__main__":
    inquiry_view()
