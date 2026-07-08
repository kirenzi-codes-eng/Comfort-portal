import base64
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

import streamlit as st
from src.database.connection import execute_query


LAST_N = 50
UGANDA_TZ = ZoneInfo("Africa/Kampala")

st.set_page_config(layout="wide", initial_sidebar_state="expanded")

ROOMS = [
    {"key": "main", "title": "💬 Main Chat", "subtitle": "Everything in one place"},
]


def _get_logo_base64() -> str:
    logo_path = Path("logo.png")
    if not logo_path.exists():
        return ""
    with logo_path.open("rb") as handle:
        return base64.b64encode(handle.read()).decode("ascii")


def fetch_messages(limit: int = LAST_N) -> List[Dict[str, Any]]:
    query = (
        "SELECT sender_name, sender_role, message_text, timestamp, member_id FROM ("
        " SELECT sender_name, sender_role, message_text, timestamp, member_id FROM group_chat "
        " ORDER BY timestamp DESC LIMIT %s) sub ORDER BY timestamp ASC;"
    )
    try:
        rows = execute_query(query, params=(limit,), fetch=True)
        return rows or []
    except Exception as e:
        st.error(f"Failed to load messages: {e}")
        return []


def post_message(member_id: str, sender_name: str, sender_role: str, text: str) -> None:
    try:
        execute_query(
            "INSERT INTO group_chat (member_id, sender_name, sender_role, message_text, timestamp) VALUES (%s, %s, %s, %s, %s);",
            params=(member_id, sender_name, sender_role, text, datetime.now(timezone.utc).replace(tzinfo=None)),
            fetch=False,
        )
    except Exception as e:
        st.error(f"Failed to post message: {e}")


def fetch_group_members() -> List[Dict[str, Any]]:
    try:
        rows = execute_query(
            "SELECT member_id, full_name, role FROM members ORDER BY full_name;",
            params=None,
            fetch=True,
        )
        return rows or []
    except Exception as e:
        st.error(f"Failed to load members: {e}")
        return []


def _render_global_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg: #f0f2f5;
            --surface: #ffffff;
            --border: #e4e6eb;
            --accent: #1877f2;
            --accent-soft: #e7f3ff;
            --teal: #42b883;
            --text: #1c1e21;
            --muted: #65676b;
        }
        html, body {
            background: var(--bg) !important;
            font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
        }
        [data-testid="stAppViewContainer"] {
            background: var(--bg) !important;
            padding: 0 !important;
        }
        .block-container {
            padding-top: 0 !important;
            padding-bottom: 0.25rem !important;
            padding-left: 0.6rem !important;
            padding-right: 0.6rem !important;
            max-width: 100% !important;
        }
        .fb-shell {
            display: flex;
            flex-direction: column;
            gap: 0.85rem;
        }
        .fb-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
        }
        .fb-sidebar, .fb-details {
            padding: 0.9rem;
            background: #ffffff;
        }
        .fb-sidebar-title {
            font-size: 1rem;
            font-weight: 700;
            color: var(--text);
            margin-bottom: 0.2rem;
        }
        .fb-sidebar-subtitle {
            font-size: 0.82rem;
            color: var(--muted);
            margin-bottom: 0.7rem;
        }
        .fb-room-item {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            padding: 0.7rem 0.75rem;
            border-radius: 10px;
            background: #f7f8fa;
            margin-bottom: 0.5rem;
            border: 1px solid #eef0f4;
        }
        .fb-room-item.active {
            background: var(--accent-soft);
            border-color: #cfe3ff;
        }
        .fb-room-badge {
            width: 34px;
            height: 34px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #ffffff;
            font-size: 0.9rem;
        }
        .fb-room-title {
            font-size: 0.92rem;
            font-weight: 700;
            color: var(--text);
        }
        .fb-room-subtitle {
            font-size: 0.78rem;
            color: var(--muted);
        }
        .fb-thread {
            display: flex;
            flex-direction: column;
            overflow: hidden;
            min-height: 78vh;
        }
        .fb-thread-header {
            padding: 0.95rem 1rem;
            border-bottom: 1px solid var(--border);
            background: #ffffff;
        }
        .fb-thread-title {
            font-size: 1rem;
            font-weight: 700;
            color: var(--text);
            margin: 0;
        }
        .fb-thread-subtitle {
            font-size: 0.8rem;
            color: var(--muted);
            margin-top: 0.16rem;
        }
        .fb-thread-scroll {
            flex: 1;
            overflow-y: auto;
            padding: 1rem;
            background: linear-gradient(180deg, #fff 0%, #f8f9fb 100%);
            max-height: 70vh;
        }
        .fb-message-row {
            display: flex;
            margin-bottom: 0.7rem;
        }
        .fb-message-row.me { justify-content: flex-end; }
        .fb-message-row.other { justify-content: flex-start; }
        .fb-message-bubble {
            max-width: 78%;
            padding: 0.72rem 0.8rem;
            border-radius: 16px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05);
        }
        .fb-message-bubble.other {
            background: #f0f2f5;
            color: var(--text);
        }
        .fb-message-bubble.me {
            background: #e7f3ff;
            color: #0f172a;
        }
        .fb-message-meta {
            display: flex;
            align-items: center;
            gap: 0.4rem;
            flex-wrap: wrap;
            margin-bottom: 0.24rem;
        }
        .fb-message-sender {
            font-weight: 700;
            font-size: 0.88rem;
        }
        .fb-message-role {
            font-size: 0.72rem;
            color: var(--muted);
            background: rgba(101, 103, 107, 0.12);
            padding: 0.16rem 0.45rem;
            border-radius: 999px;
        }
        .fb-message-time {
            font-size: 0.72rem;
            color: #8a8d91;
        }
        .fb-message-body {
            font-size: 0.94rem;
            line-height: 1.5;
            white-space: pre-wrap;
            word-break: break-word;
        }
        .fb-composer {
            padding: 0.85rem 1rem 1rem;
            border-top: 1px solid var(--border);
            background: #ffffff;
        }
        .fb-composer .stTextInput > div > div > input {
            border-radius: 999px !important;
            border: 1px solid var(--border) !important;
            padding: 0.72rem 0.9rem !important;
            background: #f0f2f5 !important;
        }
        .fb-composer button {
            border-radius: 999px !important;
            background: var(--accent) !important;
            color: #ffffff !important;
            border: none !important;
            font-weight: 700 !important;
        }
        .fb-details-title {
            font-size: 1rem;
            font-weight: 700;
            color: var(--text);
            margin-bottom: 0.3rem;
        }
        .fb-details-subtitle {
            font-size: 0.82rem;
            color: var(--muted);
            margin-bottom: 0.55rem;
        }
        .fb-avatar {
            width: 50px;
            height: 50px;
            border-radius: 50%;
            background: linear-gradient(135deg, #1877f2, #6a5acd);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
            margin-bottom: 0.7rem;
        }
        .fb-member-row {
            display: flex;
            align-items: center;
            gap: 0.55rem;
            padding: 0.45rem 0.55rem;
            border-radius: 10px;
            background: #f7f8fa;
            margin-bottom: 0.45rem;
        }
        .fb-member-initials {
            width: 30px;
            height: 30px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #e7f3ff;
            color: var(--accent);
            font-size: 0.74rem;
            font-weight: 800;
        }
        .fb-member-name {
            font-size: 0.84rem;
            font-weight: 700;
            color: var(--text);
        }
        .fb-gallery {
            display: grid;
            gap: 0.45rem;
            margin-top: 0.8rem;
        }
        .fb-gallery-item {
            padding: 0.55rem 0.6rem;
            border-radius: 10px;
            background: #f7f8fa;
            color: var(--text);
            font-size: 0.82rem;
            font-weight: 600;
        }
        .desktop-only { display: block; }
        .mobile-only { display: none; }
        @media (max-width: 980px) {
            .desktop-only { display: none !important; }
            .mobile-only { display: block !important; }
            .fb-thread-scroll { max-height: 60vh; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _format_timestamp(ts: Any) -> str:
    if isinstance(ts, str):
        try:
            ts = datetime.fromisoformat(ts)
        except Exception:
            return ""
    if not isinstance(ts, datetime):
        return ""

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    return ts.astimezone(UGANDA_TZ).strftime("%I:%M %p")


def _render_message(message: Dict[str, Any], is_self: bool) -> None:
    sender_name = message.get("sender_name") or "Unknown"
    sender_role = message.get("sender_role") or "Member"
    text = message.get("message_text") or ""
    ts = _format_timestamp(message.get("timestamp"))
    display_name = "You" if is_self else sender_name

    st.markdown(
        f"""
        <div class="fb-message-row {'me' if is_self else 'other'}">
          <div class="fb-message-bubble {'me' if is_self else 'other'}">
            <div class="fb-message-meta">
              <span class="fb-message-sender">{escape(display_name)}</span>
              <span class="fb-message-role">{escape(sender_role)}</span>
              <span class="fb-message-time">{escape(ts)}</span>
            </div>
            <div class="fb-message-body">{escape(text)}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_room_list(active_room: str) -> None:
    st.markdown("<div class='fb-card fb-sidebar'>", unsafe_allow_html=True)
    st.markdown("<div class='fb-sidebar-title'>Community Rooms</div>", unsafe_allow_html=True)
    st.markdown("<div class='fb-sidebar-subtitle'>Browse your group spaces</div>", unsafe_allow_html=True)
    for room in ROOMS:
        is_active = room["title"] == active_room
        st.markdown(
            f"""
            <div class='fb-room-item {'active' if is_active else ''}'>
              <div class='fb-room-badge'>{escape(room['title'][0])}</div>
              <div>
                <div class='fb-room-title'>{escape(room['title'])}</div>
                <div class='fb-room-subtitle'>{escape(room['subtitle'])}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def _render_details_panel(members: List[Dict[str, Any]]) -> None:
    st.markdown("<div class='fb-card fb-details'>", unsafe_allow_html=True)
    st.markdown("<div class='fb-avatar'>CP</div>", unsafe_allow_html=True)
    st.markdown("<div class='fb-details-title'>Comfort Portal Group</div>", unsafe_allow_html=True)
    st.markdown("<div class='fb-details-subtitle'>Private community • social feed style messaging</div>", unsafe_allow_html=True)
    st.markdown("<div class='fb-details-subtitle'>🟢 3 members online</div>", unsafe_allow_html=True)
    st.markdown("<div class='fb-sidebar-title'>Members</div>", unsafe_allow_html=True)
    for member in members[:6]:
        full_name = str(member.get("full_name") or "Unnamed Member").strip() or "Unnamed Member"
        initials = "".join(part[0].upper() for part in full_name.split()[:2]) or "M"
        st.markdown(
            f"""
            <div class='fb-member-row'>
              <div class='fb-member-initials'>{escape(initials)}</div>
              <div class='fb-member-name'>{escape(full_name)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("<div class='fb-gallery'>", unsafe_allow_html=True)
    st.markdown("<div class='fb-gallery-item'>📄 Loan policy update shared today</div>", unsafe_allow_html=True)
    st.markdown("<div class='fb-gallery-item'>🖼️ Profile snapshot shared</div>", unsafe_allow_html=True)
    st.markdown("<div class='fb-gallery-item'>📁 Savings report attached</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)


def _render_welcome_header() -> None:
    st.markdown(
        """
        <div class='fb-thread-header' style='background: linear-gradient(135deg, #1877f2 0%, #3b82f6 100%); border-bottom: 1px solid #1d4ed8; margin-bottom: 0.6rem;'>
          <div class='fb-thread-title' style='font-size: 1.05rem; color: #ffffff;'>Welcome to the Comfort Portal Chat Space</div>
          <div class='fb-thread-subtitle' style='font-size: 0.84rem; color: #eaf2ff;'>Say hello, share updates, and connect with everyone here.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def chat_view() -> None:
    _render_global_styles()
    st.markdown("<div class='fb-shell'>", unsafe_allow_html=True)

    user_id = st.session_state.get("user_id")
    user_name = st.session_state.get("user_name")
    user_role = st.session_state.get("user_role")

    if not user_id:
        st.info("Log in to join the group chat.")
        st.markdown("</div>", unsafe_allow_html=True)
        return

    active_room = st.session_state.get("active_room") or ROOMS[0]["title"]
    _render_welcome_header()

    st.markdown("<div class='desktop-only'>", unsafe_allow_html=True)
    col_thread = st.columns([1])[0]
    with col_thread:
        st.markdown("<div class='fb-thread'>", unsafe_allow_html=True)
        st.markdown("<div class='fb-thread-scroll'>", unsafe_allow_html=True)
        messages = fetch_messages(limit=LAST_N)
        for message in messages:
            _render_message(message, message.get("member_id") == user_id)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='fb-composer'>", unsafe_allow_html=True)
        with st.form("community_chat_form", clear_on_submit=True):
            msg = st.text_input(
                "Message",
                placeholder="Type a message...",
                label_visibility="collapsed",
            )
            submitted = st.form_submit_button("Send", width="stretch")
        st.markdown("</div>", unsafe_allow_html=True)

        if submitted:
            if not msg or not str(msg).strip():
                st.toast("Cannot send an empty message.", icon="⚠️")
            else:
                post_message(user_id, user_name or "", user_role or "Member", str(msg).strip())
                st.rerun()
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='mobile-only'>", unsafe_allow_html=True)
    with st.expander("💬 Conversation", expanded=True):
        st.markdown("<div class='fb-thread-scroll'>", unsafe_allow_html=True)
        messages = fetch_messages(limit=LAST_N)
        for message in messages:
            _render_message(message, message.get("member_id") == user_id)
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("<div class='fb-composer'>", unsafe_allow_html=True)
        with st.form("community_chat_form_mobile", clear_on_submit=True):
            msg = st.text_input(
                "Message",
                placeholder="Type a message...",
                label_visibility="collapsed",
            )
            submitted = st.form_submit_button("Send", width="stretch")
        st.markdown("</div>", unsafe_allow_html=True)
        if submitted:
            if not msg or not str(msg).strip():
                st.toast("Cannot send an empty message.", icon="⚠️")
            else:
                post_message(user_id, user_name or "", user_role or "Member", str(msg).strip())
                st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    chat_view()
