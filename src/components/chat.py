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


def _render_chat_styles() -> None:
    st.markdown(
        """
        <style>
        .chat-shell {
            border: 1px solid #e5e7eb;
            border-radius: 22px;
            overflow: hidden;
            background: #f8fafc;
            box-shadow: 0 18px 40px rgba(15, 23, 42, 0.08);
        }
        .chat-header {
            display: flex;
            align-items: center;
            gap: 12px;
            padding: 16px 18px;
            background: #075e54;
            color: #ffffff;
            border-bottom: none;
            margin: 0;
        }
        .chat-avatar {
            width: 42px;
            height: 42px;
            border-radius: 50%;
            background: rgba(255,255,255,0.18);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 0.95rem;
        }
        .chat-title {
            font-size: 1rem;
            font-weight: 700;
        }
        .chat-subtitle {
            font-size: 0.82rem;
            color: rgba(255,255,255,0.82);
            margin-top: 2px;
        }
        .chat-body {
            padding: 0;
            margin: 0;
            max-height: 430px;
            overflow-y: auto;
            overflow-x: hidden;
            background: #efeae2;
            box-sizing: border-box;
            position: relative;
        }
        .chat-wallpaper-layer {
            position: absolute;
            inset: 0;
            background-repeat: repeat;
            background-size: 160px 160px;
            opacity: 0.15;
            pointer-events: none;
            z-index: 0;
        }
        .chat-canvas-content {
            position: relative;
            z-index: 1;
            padding: 10px 10px 8px;
            min-height: 100%;
        }
        .msg-row {
            display: flex;
            margin-bottom: 10px;
        }
        .msg-row.self { justify-content: flex-end; }
        .msg-row.other { justify-content: flex-start; }
        .msg-bubble {
            max-width: 78%;
            padding: 10px 12px;
            border-radius: 16px;
            box-shadow: 0 2px 6px rgba(15, 23, 42, 0.08);
            line-height: 1.45;
        }
        .msg-bubble.self {
            background: #dcf8c6;
            color: #111827;
            border-bottom-right-radius: 4px;
        }
        .msg-bubble.other {
            background: #ffffff;
            color: #111827;
            border-bottom-left-radius: 4px;
        }
        .msg-sender {
            font-size: 0.76rem;
            font-weight: 700;
            color: #128c7e;
            margin-bottom: 3px;
        }
        .msg-text {
            font-size: 0.95rem;
            white-space: pre-wrap;
        }
        .msg-meta {
            font-size: 0.72rem;
            color: #667085;
            text-align: right;
            margin-top: 6px;
        }
        .chat-input-wrap {
            padding: 8px 12px 10px;
            background: #f7f7f7;
            border-top: 1px solid #e5e7eb;
            margin-top: 0;
        }
        .chat-input-shell {
            margin-top: 0;
            padding: 0;
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

    return ts.astimezone(UGANDA_TZ).strftime("%H:%M")


def _render_message_bubble(message: Dict[str, Any], is_self: bool, user_id: Any) -> None:
    sender_id = message.get("member_id")
    sender_name = message.get("sender_name") or "Unknown"
    sender_role = message.get("sender_role") or "Member"
    text = message.get("message_text") or ""
    ts = _format_timestamp(message.get("timestamp"))
    # preserve an ISO timestamp on the element for JS polling
    raw_ts = ""
    try:
        raw_val = message.get("timestamp")
        if hasattr(raw_val, "isoformat"):
            raw_ts = raw_val.isoformat()
        else:
            raw_ts = str(raw_val or "")
    except Exception:
        raw_ts = ""
    display_name = "You" if is_self else sender_name
    role_label = f" · {escape(sender_role)}" if sender_role else ""

    st.markdown(
        f"""
        <div class="msg-row {'self' if is_self else 'other'}" data-ts="{escape(raw_ts)}">
          <div class="msg-bubble {'self' if is_self else 'other'}">
            <div class="msg-sender">{escape(display_name)}{role_label}</div>
            <div class="msg-text">{escape(text)}</div>
            <div class="msg-meta">{ts}</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def chat_view():
    _render_chat_styles()
    st.markdown("<div class='chat-shell'>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class='chat-header'>
          <div class='chat-avatar'>GC</div>
          <div>
            <div class='chat-title'>Comfort Portal Group</div>
            <div class='chat-subtitle'>Online · Members are chatting now</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    user_id = st.session_state.get("user_id")
    user_name = st.session_state.get("user_name")
    user_role = st.session_state.get("user_role")

    logo_b64 = _get_logo_base64()
    wallpaper_style = (
        f"background-image: url('data:image/png;base64,{logo_b64}');"
        if logo_b64
        else "background-image: linear-gradient(45deg, rgba(0,0,0,0.03) 25%, transparent 25%, transparent 75%, rgba(0,0,0,0.03) 75%, rgba(0,0,0,0.03));"
    )

    st.markdown(f"<div class='chat-body'><div class='chat-wallpaper-layer' style='{wallpaper_style}'></div><div class='chat-canvas-content'>", unsafe_allow_html=True)
    if not user_id:
        st.info("Log in to join the group chat.")
        st.markdown("</div></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
        return

    messages = fetch_messages()
    for m in messages:
        _render_message_bubble(m, m.get("member_id") == user_id, user_id)
    st.markdown("</div></div>", unsafe_allow_html=True)

    # Inject a lightweight client-side poller to detect new messages and notify the user.
    # It fetches the current page HTML every few seconds, extracts the latest message timestamp
    # and, if newer than the last seen, shows a browser Notification and replaces the chat body.
    st.markdown(
        """
        <script>
        (function(){
            try {
                const POLL_MS = 6000;
                const storageKey = 'cp_last_chat_ts';

                function parseLatestTsFromDoc(doc) {
                    const row = doc.querySelector('.chat-body .msg-row[data-ts]');
                    if(!row) return '';
                    // last message is the last .msg-row inside chat-body
                    const rows = doc.querySelectorAll('.chat-body .msg-row[data-ts]');
                    if(!rows || rows.length === 0) return '';
                    const last = rows[rows.length - 1];
                    return last.getAttribute('data-ts') || '';
                }

                async function pollOnce(){
                    try {
                        const res = await fetch(window.location.href, {cache: 'no-store'});
                        const txt = await res.text();
                        const parser = new DOMParser();
                        const doc = parser.parseFromString(txt, 'text/html');
                        const newTs = parseLatestTsFromDoc(doc);
                        const oldTs = localStorage.getItem(storageKey) || '';
                        if(newTs && oldTs && newTs !== oldTs) {
                            // New message detected
                            const permission = Notification.permission;
                            if(permission === 'granted'){
                                const n = new Notification('Comfort Portal', { body: 'New group chat message' });
                                setTimeout(()=>n.close(), 5000);
                            } else if(permission !== 'denied'){
                                Notification.requestPermission().then(p => { if(p === 'granted'){ new Notification('Comfort Portal', { body: 'New group chat message' }); } });
                            }
                            // Replace the chat-body HTML
                            const newChat = doc.querySelector('.chat-body');
                            if(newChat){
                                const el = document.querySelector('.chat-body');
                                if(el) el.outerHTML = newChat.outerHTML;
                            }
                        }
                        if(newTs) localStorage.setItem(storageKey, newTs);
                    } catch(e) {
                        console.debug('chat poll error', e);
                    }
                }

                // initialize stored timestamp from current DOM
                try{
                    const rows = document.querySelectorAll('.chat-body .msg-row[data-ts]');
                    if(rows && rows.length) {
                        const last = rows[rows.length -1];
                        if(last) localStorage.setItem(storageKey, last.getAttribute('data-ts') || '');
                    }
                } catch(_){ }

                if (!('Notification' in window)) {
                    console.debug('Chat notifications not supported in this browser, poller disabled.');
                    return;
                }

                setInterval(pollOnce, POLL_MS);
            } catch(err){ console.debug('chat-poller-init', err); }
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )

    with st.container():
        st.markdown("<div class='chat-input-shell'>", unsafe_allow_html=True)
        with st.form("group_chat_form", clear_on_submit=True):
            col1, col2 = st.columns([4, 1], vertical_alignment="bottom")
            with col1:
                msg = st.text_input("", placeholder="Type a message...", label_visibility="collapsed")
            with col2:
                submitted = st.form_submit_button("Send", width='stretch')
        st.markdown("</div>", unsafe_allow_html=True)

    if submitted:
        if not msg or not str(msg).strip():
            st.toast("Cannot send empty message.", icon="⚠️")
        else:
            post_message(user_id, user_name or "", user_role or "Member", str(msg).strip())
            st.rerun()

    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    chat_view()
