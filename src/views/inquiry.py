from datetime import datetime
from functools import lru_cache
from html import escape
from typing import List, Dict

import psycopg2
import streamlit as st

from src.database.connection import execute_query


def _safe_rerun():
    """Try to trigger a Streamlit rerun; fallback to toggling session state."""
    try:
        # Preferred method when available
        rerun_fn = getattr(st, "experimental_rerun", None)
        if callable(rerun_fn):
            rerun_fn()
            return
    except Exception:
        pass

    # Fallback: toggle a dummy session_state key to cause rerun
    try:
        st.session_state.setdefault("_rerun_trigger", False)
        st.session_state["_rerun_trigger"] = not st.session_state["_rerun_trigger"]
    except Exception:
        # Last resort: do nothing
        return


def fetch_member_inquiries(member_id: str) -> List[Dict]:
    ts_col = _get_inquiry_timestamp_column()
    if ts_col is None:
        ts_col = _ensure_inquiry_timestamp_column()
    query = f"SELECT ticket_id, subject, message, status, {ts_col} AS created_at FROM inquiries WHERE member_id = %s ORDER BY {ts_col} DESC;"
    rows = execute_query(query, params=(member_id,), fetch=True)
    return rows or []


def fetch_open_inquiries() -> List[Dict]:
    ts_col = _get_inquiry_timestamp_column() or _ensure_inquiry_timestamp_column()
    query = f"SELECT ticket_id, member_id, subject, message, status, {ts_col} AS created_at FROM inquiries WHERE status = 'Open' ORDER BY {ts_col} ASC;"
    rows = execute_query(query, params=None, fetch=True)
    return rows or []


def submit_inquiry(member_id: str, subject: str, message: str) -> None:
    ts_col = _get_inquiry_timestamp_column()
    if not ts_col:
        ts_col = _ensure_inquiry_timestamp_column() or "created_at"

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
        # Try to prefer created_at
        if _get_inquiry_timestamp_column() == "created_at":
            return "created_at"
        # If neither exists, attempt to add created_at
        execute_query(
            "ALTER TABLE inquiries ADD COLUMN IF NOT EXISTS created_at TIMESTAMP;",
            params=None,
            fetch=False,
        )
        # Clear cache for getter
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


def _render_inquiry_styles() -> None:
    st.markdown(
        """
        <style>
        .inquiry-hero,
        .inquiry-card,
        .inquiry-form-card,
        .inquiry-pill {
            box-sizing: border-box;
        }
        .inquiry-hero {
            background: linear-gradient(135deg, #0f4c81 0%, #2563eb 45%, #14b8a6 100%);
            border-radius: 24px;
            padding: 24px;
            color: white;
            box-shadow: 0 18px 40px rgba(15, 76, 129, 0.22);
            margin-bottom: 18px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            max-width: 100%;
            overflow-wrap: anywhere;
        }
        .inquiry-card {
            border-radius: 18px;
            padding: 16px 18px;
            margin-bottom: 12px;
            box-shadow: 0 10px 24px rgba(15, 23, 42, 0.06);
            border: 1px solid rgba(255,255,255,0.7);
            display: flex;
            flex-direction: column;
            gap: 8px;
            max-width: 100%;
            overflow-wrap: anywhere;
        }
        .inquiry-card-open {
            background: linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%);
        }
        .inquiry-card-resolved {
            background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);
        }
        .inquiry-pill {
            display: inline-block;
            padding: 6px 10px;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 700;
            margin-bottom: 4px;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            width: fit-content;
        }
        .inquiry-pill-open {
            background: #dbeafe;
            color: #1d4ed8;
        }
        .inquiry-pill-resolved {
            background: #d1fae5;
            color: #047857;
        }
        .inquiry-form-card {
            background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%);
            border: 1px solid #dbeafe;
            border-radius: 20px;
            padding: 18px;
            margin-bottom: 16px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            max-width: 100%;
            overflow-wrap: anywhere;
        }
        .inquiry-hero-title,
        .inquiry-card-title,
        .inquiry-form-title {
            margin: 0;
            line-height: 1.2;
        }
        .inquiry-hero-copy,
        .inquiry-card-message,
        .inquiry-card-meta,
        .inquiry-form-copy {
            margin: 0;
            line-height: 1.5;
        }
        @media screen and (max-width: 768px) {
            .inquiry-hero {
                padding: 18px;
                border-radius: 18px;
            }
            .inquiry-hero-title {
                font-size: calc(1.35rem * 0.85);
            }
            .inquiry-hero-copy,
            .inquiry-card-message,
            .inquiry-card-meta,
            .inquiry-form-copy {
                font-size: calc(1rem * 0.84);
            }
            .inquiry-card-title,
            .inquiry-form-title {
                font-size: calc(1.02rem * 0.84);
            }
            .inquiry-card,
            .inquiry-form-card {
                padding: 14px;
                border-radius: 16px;
            }
            .inquiry-pill {
                font-size: calc(0.78rem * 0.85);
                padding: 5px 9px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def inquiry_view():
    _render_inquiry_styles()
    st.markdown(
        """
        <div class='inquiry-hero'>
          <h2 class='inquiry-hero-title'>Inquiry Help Desk</h2>
          <p class='inquiry-hero-copy' style='color: rgba(255,255,255,0.95);'>Share concerns, requests, or updates with the team and track the progress of each message.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    user_id = st.session_state.get("user_id")
    user_role = st.session_state.get("user_role")

    if not user_id:
        st.info("Please log in to submit or review inquiries.")
        return

    executive_roles = {"Chairperson", "Secretary", "Treasurer"}

    if user_role in executive_roles:
        st.markdown("### Open Inquiries")
        open_inquiries = fetch_open_inquiries()
        if not open_inquiries:
            st.info("There are no open inquiries at this time.")
            return

        for inquiry in open_inquiries:
            status = inquiry.get("status", "Open")
            card_class = "inquiry-card inquiry-card-open" if status != "Resolved" else "inquiry-card inquiry-card-resolved"
            pill_class = "inquiry-pill inquiry-pill-open" if status != "Resolved" else "inquiry-pill inquiry-pill-resolved"
            title_html = escape(str(inquiry.get('subject') or 'Untitled'))
            message_html = escape(str(inquiry.get('message') or ''))
            meta_html = f"Member: {escape(str(inquiry.get('member_id') or '-'))} • Submitted: {escape(str(inquiry.get('created_at') or '-'))}"

            card_html = f"""
            <div class='{card_class}'>
              <div class='{pill_class}'>{escape(status)}</div>
              <div class='inquiry-card-title' style='font-size: 1.03rem; font-weight: 700; color: #0f172a;'>{title_html}</div>
              <div class='inquiry-card-message' style='color: #334155;'>{message_html}</div>
              <div class='inquiry-card-meta' style='font-size: 0.9rem; color: #475569;'>{meta_html}</div>
            </div>
            """
            st.markdown(card_html, unsafe_allow_html=True)
            if st.button("Mark as Resolved", key=f"resolve_{inquiry['ticket_id']}"):
                resolve_inquiry(inquiry["ticket_id"])
                st.toast("Inquiry marked as resolved.", icon="✅")
                _safe_rerun()
    else:
        st.markdown("### Submit a New Inquiry")
        st.markdown(
            """
            <div class='inquiry-form-card'>
              <div class='inquiry-form-title' style='font-size: 0.9rem; font-weight: 700; color: #1d4ed8;'>Quick help</div>
              <div class='inquiry-form-copy' style='color: #334155;'>Tell us what you need and the team will respond soon.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        with st.form("inquiry_form"):
            subject = st.text_input("Subject")
            message = st.text_area("Message", height=140)
            submitted = st.form_submit_button("Submit Inquiry")

        if submitted:
            if not subject.strip() or not message.strip():
                st.toast("Subject and message are required.", icon="⚠️")
            else:
                submit_inquiry(user_id, subject.strip(), message.strip())
                st.toast("Inquiry submitted.", icon="✅")
                _safe_rerun()

        st.markdown("---")
        st.markdown("### My Inquiry History")
        inquiries = fetch_member_inquiries(user_id)
        if inquiries:
                        for inquiry in inquiries:
                                status = inquiry.get("status", "Open")
                                card_class = "inquiry-card inquiry-card-open" if status != "Resolved" else "inquiry-card inquiry-card-resolved"
                                pill_class = "inquiry-pill inquiry-pill-open" if status != "Resolved" else "inquiry-pill inquiry-pill-resolved"
                                title_html = escape(str(inquiry.get('subject') or 'Untitled'))
                                message_html = escape(str(inquiry.get('message') or ''))
                                meta_html = f"Submitted: {escape(str(inquiry.get('created_at') or '-'))}"

                                card_html = f"""
                                <div class='{card_class}'>
                                    <div class='{pill_class}'>{escape(status)}</div>
                                    <div class='inquiry-card-title' style='font-size: 1.02rem; font-weight: 700; color: #0f172a;'>{title_html}</div>
                                    <div class='inquiry-card-message' style='color: #334155;'>{message_html}</div>
                                    <div class='inquiry-card-meta' style='font-size: 0.9rem; color: #475569;'>{meta_html}</div>
                                </div>
                                """
                                st.markdown(card_html, unsafe_allow_html=True)
        else:
            st.info("You have no inquiries yet.")


if __name__ == "__main__":
    inquiry_view()
