import logging
import psycopg2
import pandas as pd
import streamlit as st
import time
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import Optional

from src.components.auth import get_avatar
from src.database.connection import execute_query
from src.utils.membership import get_membership_status_for_db
from src.utils.balances import get_effective_member_balance
from src.utils.timezone import now_in_uganda

logger = logging.getLogger(__name__)

MOCK_FINANCIAL_METRICS = {
    "total_paid": 820000.0,
    "loan_balance": 260000.0,
    "arrears": 42000.0,
}

MOCK_ADMIN_METRICS = {
    "total_pool_savings": 7420000.0,
    "total_cash_loaned": 1840000.0,
    "total_repaid": 1320000.0,
    "total_arrears": 203000.0,
}

MOCK_ACTIVE_BORROWERS = [
    {"Member": "Ruth Nakato", "Loan Balance": 280000.0},
    {"Member": "Isaac Mugisha", "Loan Balance": 212000.0},
    {"Member": "Zahara Kiggundu", "Loan Balance": 172000.0},
]

MOCK_ANNOUNCEMENTS = [
    {
        "title": "System test announcement",
        "content": "Announcements will appear here once your database tables are available.",
        "posted_by": "System",
        "created_at": now_in_uganda().strftime("%Y-%m-%d %H:%M:%S"),
    }
]


def _is_table_missing_error(exc: Exception) -> bool:
    missing_table_code = "42P01"
    try:
        return (
            isinstance(exc, psycopg2.errors.UndefinedTable)
            or getattr(exc, "pgcode", None) == missing_table_code
        )
    except Exception:
        return False


def safe_execute_query(query: str, params=None, fetch: bool = False, fallback=None):
    try:
        rows = execute_query(query, params=params, fetch=fetch)
        return fallback if rows is None else rows
    except psycopg2.Error as exc:
        if _is_table_missing_error(exc):
            logger.warning("Missing table detected in query, using fallback data: %s", query)
            return fallback
        logger.exception("Unexpected database error during query: %s", query)
        return fallback


@st.cache_data(ttl=300)
def get_announcements_cached():
    """Cached announcements with 5-minute TTL."""
    rows = safe_execute_query(ANNOUNCEMENTS_QUERY, params=None, fetch=True, fallback=MOCK_ANNOUNCEMENTS)
    return rows or []


ANNOUNCEMENTS_QUERY = "SELECT title, content, posted_by, created_at FROM announcements ORDER BY created_at DESC;"


def post_announcement(title: str, content: str, posted_by: str) -> None:
    insert_sql = (
        "INSERT INTO announcements (title, content, posted_by, created_at) VALUES (%s, %s, %s, %s);"
    )
    execute_query(insert_sql, params=(title, content, posted_by, datetime.utcnow()), fetch=False)
    get_announcements_cached.clear()


def get_announcements():
    """Use cached announcements to improve page load time."""
    return get_announcements_cached()


def today_in_uganda() -> date:
    uganda_offset = timezone(timedelta(hours=3))
    return datetime.now(timezone.utc).astimezone(uganda_offset).date()


def parse_db_datetime(value) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.strptime(cleaned, "%Y-%m-%d")
            except ValueError:
                try:
                    return datetime.combine(date.fromisoformat(cleaned), datetime.min.time())
                except ValueError:
                    return None
    return None


def add_months(value: date | datetime, months: int) -> date:
    base_date = value.date() if isinstance(value, datetime) else value
    year = base_date.year + (base_date.month - 1 + months) // 12
    month = (base_date.month - 1 + months) % 12 + 1
    day = min(base_date.day, monthrange(year, month)[1])
    return date(year, month, day)


def get_next_loan_due_date(user_id: Optional[str]) -> Optional[date]:
    if not user_id:
        return None

    rows = safe_execute_query(
        "SELECT approved_date, applied_date FROM loans WHERE member_id = %s AND status IN ('Active','Approved');",
        params=(user_id,),
        fetch=True,
        fallback=[],
    ) or []
    due_dates = []
    for row in rows:
        base_value = row.get("approved_date") or row.get("applied_date")
        base_datetime = parse_db_datetime(base_value)
        if base_datetime is not None:
            due_dates.append(add_months(base_datetime, 1))

    if due_dates:
        return min(due_dates)

    if rows:
        # There is an active or approved loan, but no valid date could be parsed.
        return datetime.now().date()

    return None


def calculate_effective_loan_balance(rows: list[dict]) -> float:
    total = 0.0
    for row in rows:
        outstanding = float(row.get("outstanding_balance") or 0.0)
        interest = float(row.get("interest_accumulated") or 0.0)
        amount_requested = float(row.get("amount_requested") or 0.0)

        # If outstanding balance is still recorded as original principal and interest is tracked separately,
        # include the separate interest amount. Otherwise, use the outstanding balance directly.
        if interest > 0 and outstanding == amount_requested:
            total += outstanding + interest
        else:
            total += outstanding
    return total


def get_financial_metrics(user_id: str) -> dict:
    """Fetch financial metrics with 60-second cache TTL."""
    if not user_id:
        return MOCK_FINANCIAL_METRICS.copy()
    return get_financial_metrics_cached(user_id)


@st.cache_data(ttl=60)
def get_financial_metrics_cached(user_id: str) -> dict:
    """Cached version of get_financial_metrics with 1-minute TTL."""
    try:
        total_paid = get_effective_member_balance(user_id)

        # Active Loan Balance including accumulated interest
        loan_sql = (
            "SELECT outstanding_balance, interest_accumulated, amount_requested "
            "FROM loans WHERE member_id = %s AND status IN ('Active','Approved');"
        )
        loan_rows = safe_execute_query(
            loan_sql,
            params=(user_id,),
            fetch=True,
            fallback=[{"outstanding_balance": MOCK_FINANCIAL_METRICS["loan_balance"], "interest_accumulated": 0.0, "amount_requested": MOCK_FINANCIAL_METRICS["loan_balance"]}],
        )
        loan_balance = calculate_effective_loan_balance(loan_rows or [])

        # Pending Subscription Arrears - compute year-to-date due amount
        today = today_in_uganda()
        current_year = today.year
        current_month = today.month
        paid_year_sql = (
            "SELECT COALESCE(SUM(amount_paid),0) AS total_paid_year FROM subscriptions "
            "WHERE member_id = %s AND EXTRACT(YEAR FROM billing_month) = %s;"
        )
        paid_year_rows = safe_execute_query(
            paid_year_sql,
            params=(user_id, current_year),
            fetch=True,
            fallback=[{"total_paid_year": 0}],
        )
        total_paid_year = paid_year_rows[0]["total_paid_year"] if paid_year_rows else 0
        expected_year_to_date = current_month * 20000
        arrears = max(0.0, expected_year_to_date - float(total_paid_year))

        return {
            "total_paid": total_paid,
            "loan_balance": loan_balance,
            "arrears": arrears,
        }
    except psycopg2.Error:
        logger.warning("Falling back to mock financial metrics due to database error")
        return MOCK_FINANCIAL_METRICS.copy()



def calculate_member_status(join_date, saving_balance, arrears_balance):
    db_status = get_membership_status_for_db(join_date, saving_balance=saving_balance, arrears_balance=arrears_balance)

    label_map = {
        "Pending": ("Pending", "#F59E0B"),
        "Probationary": ("Probationary", "#D97706"),
        "Active": ("Active", "#2563EB"),
        "Partial Member": ("Partial", "#2563EB"),
        "Full Member": ("Full", "#059669"),
        "Inactive": ("Inactive", "#EF4444"),
    }
    membership_label, membership_color = label_map.get(db_status, ("Pending", "#F59E0B"))

    arrears_balance = float(arrears_balance or 0)
    activity_label = "Inactive" if arrears_balance >= 40000 else "Active"
    activity_color = "#DC2626" if activity_label == "Inactive" else "#059669"

    return membership_label, membership_color, activity_label, activity_color


def format_currency(value) -> str:
    return f"UGX {float(value or 0):,.0f}"


def get_member_summary_stats() -> dict:
    rows = safe_execute_query(
        "SELECT COUNT(*) AS total_members, "
        "SUM(CASE WHEN status IN ('Active','Probationary','Partial Member','Full Member') THEN 1 ELSE 0 END) AS active_members, "
        "SUM(CASE WHEN status = 'Inactive' THEN 1 ELSE 0 END) AS inactive_members, "
        "SUM(CASE WHEN status = 'Pending' THEN 1 ELSE 0 END) AS pending_members "
        "FROM members;",
        params=None,
        fetch=True,
        fallback=[
            {
                "total_members": 0,
                "active_members": 0,
                "inactive_members": 0,
                "pending_members": 0,
            }
        ],
    ) or [
        {
            "total_members": 0,
            "active_members": 0,
            "inactive_members": 0,
            "pending_members": 0,
        }
    ]

    stats = rows[0]
    total_members = int(stats.get("total_members") or 0)
    active_members = int(stats.get("active_members") or 0)
    inactive_members = int(stats.get("inactive_members") or 0)
    pending_members = int(stats.get("pending_members") or 0)

    if inactive_members > 0:
        required_action = f"Review {inactive_members} inactive member{'s' if inactive_members != 1 else ''}."
    elif pending_members > 0:
        required_action = f"Process {pending_members} pending member{'s' if pending_members != 1 else ''}."
    else:
        required_action = "No immediate membership actions pending."

    return {
        "total_members": total_members,
        "active_members": active_members,
        "inactive_members": inactive_members,
        "required_action": required_action,
    }


def get_member_join_date(member_id: Optional[str]):
    """Fetch member join date with 1-hour TTL caching."""
    if not member_id:
        return None
    return get_member_join_date_cached(member_id)


@st.cache_data(ttl=3600)
def get_member_join_date_cached(member_id: str):
    """Cached version of get_member_join_date."""
    rows = execute_query(
        "SELECT join_date FROM members WHERE member_id = %s LIMIT 1;",
        params=(member_id,),
        fetch=True,
    )
    if not rows:
        return None
    return rows[0].get("join_date")


def get_featured_announcement(announcements):
    if "announcement_index" not in st.session_state:
        st.session_state.announcement_index = 0

    if not announcements:
        return None

    index = st.session_state.announcement_index % len(announcements)
    ann = announcements[index]
    st.session_state.announcement_index = (index + 1) % len(announcements)
    return ann


@st.fragment(run_every=30)
def render_announcements_carousel(announcements):
    ann = get_featured_announcement(announcements)

    title_text = escape(str(ann.get("title") or "No announcements yet")) if ann else "No announcements yet"
    content_text = escape(str(ann.get("content") or "New updates will appear here.")) if ann else "New updates will appear here."
    author_text = escape(str(ann.get("posted_by") or "System")) if ann else "System"
    meta_text = escape(str(ann.get("created_at") or "")) if ann else ""

    st.markdown(
        f"""
        <div class="hero-shell" style="margin-top: 10px;">
          <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; flex-wrap: wrap;">
            <div style="flex: 1 1 320px;">
              <div style="font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.2em; opacity: 0.8;">System Updates & Announcements</div>
              <div style="font-size: 1.14rem; font-weight: 700; color: #ffffff; margin: 8px 0 8px;">{title_text}</div>
              <div style="color: rgba(255,255,255,0.92); font-size: 0.96rem; line-height: 1.6; margin-bottom: 8px;">{content_text}</div>
              <div style="display: flex; justify-content: space-between; align-items: center; gap: 10px; flex-wrap: wrap; margin-top: 10px;">
                <div style="font-size: 0.82rem; color: rgba(255,255,255,0.82);">Posted by {author_text}{f' • {meta_text}' if meta_text else ''}</div>
                <div style="background: rgba(255,255,255,0.16); border: 1px solid rgba(255,255,255,0.22); padding: 7px 10px; border-radius: 999px; font-size: 0.8rem; font-weight: 700; color: #ffffff;">Latest Update • {now_in_uganda().strftime('%d %b %Y')}</div>
              </div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_identity_bar(user_name: str, user_role: str, saving_balance: float = 0, arrears_balance: float = 0, join_date=None, avatar_url: str | None = None) -> None:
    display_name = user_name or "KIRENZI Christopher"
    role = user_role or "Member"
    membership_label, membership_color, activity_label, activity_color = calculate_member_status(join_date, saving_balance, arrears_balance)
    formatted_balance = f"{float(saving_balance or 0):,.0f}"
    formatted_arrears = f"{float(arrears_balance or 0):,.0f}"
    activity_class = "status-active" if activity_label == "Active" else "status-inactive"
    avatar_html = (
        f"<img src=\"{escape(avatar_url)}\" width=52 height=52 style=\"border-radius:50%;object-fit:cover;border:2px solid rgba(255,255,255,0.85);\" />"
        if avatar_url
        else "<div style=\"width:52px;height:52px;border-radius:50%;background:rgba(255,255,255,0.95);color:#064E3B;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:1rem;box-shadow:inset 0 0 0 2px rgba(255,255,255,0.2);flex-shrink:0;\">" + "".join(part[0].upper() for part in display_name.split()[:2]) + "</div>"
    )
    st.markdown(
        f"""
        <style>
        .status-active {{
            animation: pulse-green 1.8s ease-in-out infinite;
            box-shadow: 0 0 0 0 rgba(5, 150, 105, 0.45);
        }}
        .status-inactive {{
            animation: pulse-red 1.8s ease-in-out infinite;
            box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.45);
        }}
        @keyframes pulse-green {{
            0% {{ transform: scale(1); box-shadow: 0 0 0 0 rgba(5, 150, 105, 0.35); }}
            50% {{ transform: scale(1.03); box-shadow: 0 0 0 8px rgba(5, 150, 105, 0); }}
            100% {{ transform: scale(1); box-shadow: 0 0 0 0 rgba(5, 150, 105, 0); }}
        }}
        @keyframes pulse-red {{
            0% {{ transform: scale(1); box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.35); }}
            50% {{ transform: scale(1.03); box-shadow: 0 0 0 8px rgba(220, 38, 38, 0); }}
            100% {{ transform: scale(1); box-shadow: 0 0 0 0 rgba(220, 38, 38, 0); }}
        }}
        </style>
        <div class="user-identity" style="background: linear-gradient(90deg, #064E3B 0%, #0F766E 100%); border-radius: 18px; padding: 14px 18px; margin-bottom: 18px; color: white; box-shadow: 0 12px 24px rgba(6, 78, 59, 0.16); box-sizing: border-box;">
          <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap;">
            <div style="display: flex; align-items: center; gap: 12px; min-width: 0; flex: 1 1 auto;">
              {avatar_html}
              <div style="min-width: 0;">
                <div style="font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.2em; opacity: 0.8;">Comfort Portal • CBO Workspace</div>
                <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 4px;">
                  <div style="font-size: 1.02rem; font-weight: 700;">{display_name}</div>
                  <div style="width: 1px; height: 14px; background: rgba(255,255,255,0.5);"></div>
                  <span style="display: inline-block; padding: 4px 8px; border-radius: 999px; background: {membership_color}; color: white; font-size: 0.72rem; font-weight: 700;">{membership_label}</span>
                                    <span class="{activity_class}" style="display: inline-block; padding: 6px 10px; border-radius: 999px; background: {activity_color}; color: white; font-size: 0.88rem; font-weight: 900; letter-spacing: 0.02em; box-shadow: 0 2px 6px rgba(0,0,0,0.12);">
                                        <strong style="font-weight:900; text-transform:uppercase;">{activity_label}</strong>
                                    </span>
                </div>
              </div>
            </div>
                        <div style="display:flex; align-items:center; gap:8px; background: rgba(255,255,255,0.12); border: 1px solid rgba(255,255,255,0.14); padding: 6px 10px; border-radius: 999px; min-width:0; flex:0 0 auto; white-space:nowrap;">
                            <div style="display:flex; align-items:center; gap:8px;">
                                <span style="font-size:0.72rem; text-transform:uppercase; font-weight:700; opacity:0.95; letter-spacing:0.08em;">Savings</span>
                                <span style="font-size:0.95rem; font-weight:900;">UGX {formatted_balance}</span>
                            </div>
                        </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_admin_announcement_manager() -> None:
    user_role = st.session_state.get("user_role", "Chairperson")
    if user_role not in ["Chairperson", "Secretary"]:
        return

    try:
        existing_rows = execute_query(
            "SELECT id, title, content, posted_by, created_at FROM announcements ORDER BY created_at DESC LIMIT 20;",
            params=None,
            fetch=True,
        ) or []
    except psycopg2.Error as exc:
        # Surface DB errors in the admin UI to aid debugging (missing table, connection issues, etc.)
        err_msg = str(exc)
        pgcode = getattr(exc, "pgcode", None)
        st.error(f"Database error while loading announcements: {err_msg} (pgcode={pgcode})")
        return

    with st.expander("Admin: Manage Announcements", expanded=False):
        action = st.radio("Choose action", ["Post new announcement", "Update existing announcement"], horizontal=True)

        if action == "Post new announcement":
            title = st.text_input("Title", key="admin_announcement_title")
            content = st.text_area("Content", key="admin_announcement_content")
            posted_by = st.text_input("Posted by", key="admin_announcement_author")

            if st.button("Post announcement"):
                if not title.strip() or not content.strip():
                    st.warning("Title and content are required.")
                else:
                    try:
                        execute_query(
                            "INSERT INTO announcements (title, content, posted_by, created_at) VALUES (%s, %s, %s, %s);",
                            params=(title.strip(), content.strip(), posted_by.strip() or "Admin", now_in_uganda()),
                            fetch=False,
                        )
                        st.success("Announcement posted successfully.")
                    except psycopg2.Error as exc:
                        st.error(f"Failed to post announcement: {exc}")

        else:
            if not existing_rows:
                st.info("No announcements available to update.")
                return

            options = {f"{row.get('title') or 'Untitled'} ({row.get('id')})": row for row in existing_rows}
            selected_label = st.selectbox("Select announcement", options=list(options.keys()))
            selected_row = options[selected_label]

            title = st.text_input("Title", value=str(selected_row.get("title") or ""), key="admin_update_title")
            content = st.text_area("Content", value=str(selected_row.get("content") or ""), key="admin_update_content")
            posted_by = st.text_input("Posted by", value=str(selected_row.get("posted_by") or ""), key="admin_update_author")

            if st.button("Update announcement"):
                if not title.strip() or not content.strip():
                    st.warning("Title and content are required.")
                else:
                    try:
                        execute_query(
                            "UPDATE announcements SET title = %s, content = %s, posted_by = %s, created_at = %s WHERE id = %s;",
                            params=(title.strip(), content.strip(), posted_by.strip() or "Admin", now_in_uganda(), selected_row["id"]),
                            fetch=False,
                        )
                        st.success("Announcement updated successfully.")
                    except psycopg2.Error as exc:
                        st.error(f"Failed to update announcement: {exc}")


def home_view():
    st.markdown(
        """
        <style>
        .stApp { background: #F8FAFC; }
        .stMainBlockContainer {
            padding-top: 2.5rem !important;
        }
        .user-identity {
            box-sizing: border-box;
        }
        .block-container {
            padding-top: 1rem;
            padding-bottom: 2rem;
            max-width: 1500px;
        }
        .hero-shell {
            background: linear-gradient(135deg, #0F766E 0%, #115E59 100%);
            color: #ffffff;
            padding: 24px 26px;
            border-radius: 24px;
            box-shadow: 0 16px 32px rgba(6, 78, 59, 0.16);
            margin-bottom: 16px;
        }
        .hero-shell h2 {
            margin: 0 0 8px 0;
            font-size: 1.5rem;
            color: #ffffff;
        }
        .hero-shell p {
            margin: 0;
            color: rgba(255,255,255,0.92);
            line-height: 1.5;
        }
        .module-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
            gap: 14px;
            margin-top: 10px;
        }
        .module-card {
            background: #ffffff;
            border: 1px solid #E2E8F0;
            border-radius: 16px;
            padding: 14px 16px;
            box-shadow: 0 6px 16px rgba(15, 23, 42, 0.04);
            transition: all 0.24s ease;
        }
        .module-card:hover {
            transform: translateY(-3px);
            border-color: #0F766E;
            background: #F8FFFD;
        }
        .module-badge {
            display: inline-flex;
            width: 42px;
            height: 42px;
            align-items: center;
            justify-content: center;
            border-radius: 50%;
            background: #ECFEFF;
            font-size: 1.15rem;
            margin-bottom: 10px;
        }
        .module-title {
            font-size: 0.98rem;
            font-weight: 700;
            color: #064E3B;
            margin-bottom: 2px;
        }
        .module-subtitle {
            font-size: 0.76rem;
            color: #64748B;
            text-transform: uppercase;
            letter-spacing: 0.12em;
        }
        .kpi-card {
            background: #ffffff;
            border: 1px solid #E2E8F0;
            border-radius: 16px;
            padding: 14px 16px;
            box-shadow: 0 6px 16px rgba(15, 23, 42, 0.04);
            margin-top: 10px;
        }
        .kpi-label {
            font-size: 0.74rem;
            color: #64748B;
            text-transform: uppercase;
            letter-spacing: 0.12em;
        }
        .kpi-value {
            font-size: 1.2rem;
            font-weight: 700;
            color: #064E3B;
            margin-top: 6px;
        }
        .timeline-card {
            background: #ffffff;
            border-left: 4px solid #D97706;
            border-radius: 12px;
            padding: 12px 14px;
            box-shadow: 0 6px 16px rgba(15, 23, 42, 0.03);
            margin-bottom: 10px;
        }
        .timeline-time {
            display: block;
            font-size: 0.74rem;
            font-weight: 700;
            color: #D97706;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            margin-bottom: 4px;
        }
        .timeline-title {
            font-size: 0.95rem;
            font-weight: 600;
            color: #0F172A;
        }
        .timeline-desc {
            margin-top: 4px;
            font-size: 0.87rem;
            color: #475569;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    if "user_role" not in st.session_state:
        st.session_state.user_role = "Chairperson"

    user_role = st.session_state.get("user_role", "Member")
    user_id = st.session_state.get("user_id")
    user_name = st.session_state.get("user_name", "Guest")
    join_date = st.session_state.get("join_date")

    metrics = {"total_paid": 0, "loan_balance": 0, "arrears": 0}
    announcements = []

    if user_id:
        with st.spinner("Loading data..."):
            refreshed_join_date = get_member_join_date(user_id)
            if refreshed_join_date is not None:
                st.session_state["join_date"] = refreshed_join_date
                join_date = refreshed_join_date

            metrics = get_financial_metrics(user_id)
            announcements = get_announcements()
    
    saving_balance = metrics.get("total_paid", 0)
    arrears_balance = metrics.get("arrears", 0)

    allowed_roles = [
        "Chairperson",
        "Vice Chairperson",
        "Secretary",
        "Treasurer",
        "Welfare",
    ]
    column_weights = [7, 3] if user_role in allowed_roles else [9, 1]
    left_col, right_col = st.columns(column_weights, gap="large")

    with left_col:
        avatar_url = None
        if user_id:
            avatar_url = get_avatar(user_id, user_name)

        _render_identity_bar(
            user_name,
            user_role,
            saving_balance=saving_balance,
            arrears_balance=arrears_balance,
            join_date=join_date,
            avatar_url=avatar_url,
        )
        announcements = get_announcements()
        recent_announcements = announcements[:4]
        older_announcements = announcements[4:]

        render_admin_announcement_manager()
        render_announcements_carousel(recent_announcements)

        with st.expander("View Older Announcements History"):
            if older_announcements:
                for ann in older_announcements:
                    st.markdown(
                        f"""
                        <div style="background: #ffffff; border: 1px solid #E2E8F0; border-radius: 12px; padding: 12px 14px; margin-bottom: 10px; box-shadow: 0 6px 16px rgba(15, 23, 42, 0.03);">
                          <div style="font-weight: 700; color: #064E3B; margin-bottom: 4px;">{escape(str(ann['title']))}</div>
                          <div style="color: #334155; font-size: 0.95rem;">{escape(str(ann['content']))}</div>
                          <div style="margin-top: 8px; font-size: 0.76rem; color: #64748B;">Posted by {escape(str(ann['posted_by']))} • {escape(str(ann['created_at']))}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No older announcements yet.")

        st.markdown(
            "<div style='font-size: 1.05rem; font-weight: 700; color: #064E3B; margin: 10px 0 6px;'>Action Desks</div>",
            unsafe_allow_html=True,
        )

        if user_id:
            metrics = get_financial_metrics(user_id)
        else:
            metrics = {"total_paid": 0, "loan_balance": 0, "arrears": 0}

        subscriptions_contributed = float(metrics.get("total_paid", 0) or 0)
        arrears_balance = float(metrics.get("arrears", 0) or 0)
        loan_balance = float(metrics.get("loan_balance", 0) or 0)
        next_due_date = get_next_loan_due_date(user_id) if user_id else None
        if next_due_date:
            next_due_display = next_due_date.strftime("%d %b %Y")
        elif loan_balance > 0:
            next_due_display = "Active loan pending due date"
        else:
            next_due_display = "No active loan"
        projected_share = subscriptions_contributed * 0.08 if subscriptions_contributed > 0 else 0.0
        alert_class = "action-card--alert" if arrears_balance > 0 else ""
        summary_stats = get_member_summary_stats() if user_role in allowed_roles else None

        st.markdown(
            f"""
            <style>
            .action-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 12px;
                margin-top: 8px;
            }}
            .action-card {{
                background: linear-gradient(135deg, #eff6ff 0%, #ffffff 100%);
                border: 1px solid #dbeafe;
                border-radius: 16px;
                padding: 14px 14px 12px;
                box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
                position: relative;
                overflow: hidden;
            }}
            .action-card::before {{
                content: "";
                position: absolute;
                top: 0;
                left: 0;
                width: 100%;
                height: 4px;
                background: #93c5fd;
            }}
            .action-card--alert {{
                border-color: #dc2626;
                box-shadow: 0 10px 24px rgba(220, 38, 38, 0.14);
            }}
            .action-card--subscriptions::before {{
                background: #93c5fd;
            }}
            .action-card--loans::before {{
                background: #93c5fd;
            }}
            .action-card--sharing::before {{
                background: linear-gradient(90deg, #059669 0%, #34d399 100%);
            }}
            .action-icon {{
                width: 42px;
                height: 42px;
                display: inline-flex;
                align-items: center;
                justify-content: center;
                border-radius: 50%;
                background: #dbeafe;
                font-size: 1.1rem;
                margin-bottom: 10px;
            }}
            .action-card--subscriptions .action-icon {{
                background: #dbeafe;
            }}
            .action-card--loans .action-icon {{
                background: #dbeafe;
            }}
            .action-card--sharing .action-icon {{
                background: #dcfce7;
            }}
            .action-title {{
                font-size: 0.98rem;
                font-weight: 700;
                color: #0f172a;
                margin-bottom: 8px;
            }}
            .action-stats {{
                background: #eff6ff;
                border: 1px solid #bfdbfe;
                border-radius: 12px;
                padding: 10px;
                display: flex;
                flex-direction: column;
                gap: 6px;
            }}
            .action-stats--green {{
                background: #f0fdf4;
                border-color: #bbf7d0;
            }}
            .action-card--subscriptions .action-stats {{
                background: #eff6ff;
                border-color: #bfdbfe;
            }}
            .action-card--loans .action-stats {{
                background: #eff6ff;
                border-color: #bfdbfe;
            }}
            .action-card--sharing .action-stats {{
                background: #f0fdf4;
                border-color: #bbf7d0;
            }}
            .action-stat {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                gap: 8px;
                font-size: 0.82rem;
            }}
            .action-stat-label {{
                color: #64748b;
            }}
            .action-stat-value {{
                font-weight: 700;
                color: #0f172a;
            }}
            .action-card--alert .action-stat-value {{
                color: #991b1b;
            }}
            .action-card--alert .action-title {{
                color: #b91c1c;
            }}
            .summary-grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
                gap: 12px;
                margin-top: 20px;
            }}
            .summary-card {{
                background: #ffffff;
                border: 1px solid #dbeafe;
                border-radius: 16px;
                padding: 14px 16px;
                box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
            }}
            .summary-card-title {{
                font-size: 0.78rem;
                font-weight: 700;
                color: #475569;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                margin-bottom: 8px;
            }}
            .summary-card-value {{
                font-size: 1.45rem;
                font-weight: 700;
                color: #0f172a;
            }}
            .summary-card-action {{
                margin-top: 10px;
                font-size: 0.9rem;
                color: #334155;
                line-height: 1.5;
            }}
            </style>
            <div class="action-grid">
              <div class="action-card action-card--subscriptions {alert_class}">
                <div class="action-icon">💳</div>
                <div class="action-title">Subscriptions</div>
                <div class="action-stats">
                  <div class="action-stat"><span class="action-stat-label">Total Contributed</span><span class="action-stat-value">{format_currency(subscriptions_contributed)}</span></div>
                  <div class="action-stat"><span class="action-stat-label">Pending Arrears</span><span class="action-stat-value">{format_currency(arrears_balance)}</span></div>
                </div>
              </div>
              <div class="action-card action-card--loans">
                <div class="action-icon">🏦</div>
                <div class="action-title">Loans &amp; Credit</div>
                <div class="action-stats">
                  <div class="action-stat"><span class="action-stat-label">Outstanding Balance</span><span class="action-stat-value">{format_currency(loan_balance)}</span></div>
                  <div class="action-stat"><span class="action-stat-label">Next Due Date</span><span class="action-stat-value">{next_due_display}</span></div>
                </div>
              </div>
              <div class="action-card action-card--sharing">
                <div class="action-icon">🤝</div>
                <div class="action-title">End-of-Year Sharing</div>
                <div class="action-stats action-stats--green">
                  <div style="font-size: 0.82rem; color: #334155; line-height: 1.45;">
                    Your year-end reward is growing steadily. Strong savings habits and active borrowing and repayment help build the central interest pool, which directly increases your final end-of-year take-home package.
                  </div>
                </div>
              </div>
            </div>            {f"<div class='summary-grid'>\n              <div class='summary-card'>\n                <div class='summary-card-title'>Total members</div>\n                <div class='summary-card-value'>{summary_stats['total_members']}</div>\n              </div>\n              <div class='summary-card'>\n                <div class='summary-card-title'>Active members</div>\n                <div class='summary-card-value'>{summary_stats['active_members']}</div>\n              </div>\n              <div class='summary-card'>\n                <div class='summary-card-title'>Inactive members</div>\n                <div class='summary-card-value'>{summary_stats['inactive_members']}</div>\n              </div>\n              <div class='summary-card'>\n                <div class='summary-card-title'>Required action</div>\n                <div class='summary-card-action'>{escape(summary_stats['required_action'])}</div>\n              </div>\n            </div>" if summary_stats else ""}            """,
            unsafe_allow_html=True,
        )

    with right_col:
        allowed_roles = [
            "Chairperson",
            "Vice Chairperson",
            "Secretary",
            "Treasurer",
            "Welfare",
        ]
        if user_role in allowed_roles:
            st.markdown(
                "<div style='font-size: 1.05rem; font-weight: 700; color: #064E3B; margin-bottom: 10px;'>Global Financial Updates</div>",
                unsafe_allow_html=True,
            )

            admin_pool_rows = safe_execute_query(
                "SELECT COALESCE(SUM(amount_paid),0) AS total_pool_savings FROM subscriptions;",
                params=None,
                fetch=True,
                fallback=[{"total_pool_savings": MOCK_ADMIN_METRICS["total_pool_savings"]}],
            ) or [{"total_pool_savings": MOCK_ADMIN_METRICS["total_pool_savings"]}]
            admin_loan_rows = safe_execute_query(
                "SELECT COALESCE(SUM(outstanding_balance),0) AS total_cash_loaned FROM loans WHERE status IN ('Active','Approved');",
                params=None,
                fetch=True,
                fallback=[{"total_cash_loaned": MOCK_ADMIN_METRICS["total_cash_loaned"]}],
            ) or [{"total_cash_loaned": MOCK_ADMIN_METRICS["total_cash_loaned"]}]
            admin_repaid_rows = safe_execute_query(
                "SELECT COALESCE(SUM(outstanding_balance),0) AS total_repaid "
                "FROM loans "
                "WHERE status IN ('Active','Approved') AND COALESCE(outstanding_balance,0) > 0;",
                params=None,
                fetch=True,
                fallback=[{"total_repaid": MOCK_ADMIN_METRICS["total_repaid"]}],
            ) or [{"total_repaid": MOCK_ADMIN_METRICS["total_repaid"]}]
            admin_arrears_rows = safe_execute_query(
                "SELECT COALESCE(SUM(GREATEST(0, (EXTRACT(MONTH FROM CURRENT_DATE) * 20000) - COALESCE(paid_year.total_paid_year, 0))), 0) AS total_arrears "
                "FROM members m "
                "LEFT JOIN ("
                "  SELECT member_id, SUM(COALESCE(amount_paid, 0)) AS total_paid_year "
                "  FROM subscriptions "
                "  WHERE EXTRACT(YEAR FROM billing_month) = EXTRACT(YEAR FROM CURRENT_DATE) "
                "  GROUP BY member_id"
                ") paid_year ON paid_year.member_id = m.member_id;",
                params=None,
                fetch=True,
                fallback=[{"total_arrears": MOCK_ADMIN_METRICS["total_arrears"]}],
            ) or [{"total_arrears": MOCK_ADMIN_METRICS["total_arrears"]}]
            admin_borrowers_rows = safe_execute_query(
                "SELECT m.full_name AS member_name, l.status AS loan_status "
                "FROM loans l JOIN members m ON m.member_id = l.member_id "
                "WHERE l.status IN ('Active','Approved') AND COALESCE(l.outstanding_balance,0) > 0 "
                "ORDER BY l.outstanding_balance DESC;",
                params=None,
                fetch=True,
                fallback=[],
            ) or []

            total_pool_savings = float(admin_pool_rows[0].get("total_pool_savings") or 0)
            total_cash_loaned = float(admin_loan_rows[0].get("total_cash_loaned") or 0)
            total_repaid = float(admin_repaid_rows[0].get("total_repaid") or 0)
            total_arrears = float(admin_arrears_rows[0].get("total_arrears") or 0)

            st.markdown(
                f"""
                <div style="display: grid; grid-template-columns: repeat(1, minmax(0, 1fr)); gap: 12px;">
                  <div class="kpi-card"><div class="kpi-label">Total Savings Pool</div><div class="kpi-value">{format_currency(total_pool_savings)}</div></div>
                  <div class="kpi-card"><div class="kpi-label">Total Cash Loaned</div><div class="kpi-value">{format_currency(total_cash_loaned)}</div></div>
                  <div class="kpi-card"><div class="kpi-label">Total Unrepaid Loan Amount</div><div class="kpi-value">{format_currency(total_repaid)}</div></div>
                  <div class="kpi-card"><div class="kpi-label">Total Outstanding Arrears</div><div class="kpi-value">{format_currency(total_arrears)}</div></div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            borrower_table = []
            for row in admin_borrowers_rows:
                borrower_table.append({
                    "Member": row.get("member_name") or "Unknown",
                    "Loan Status": row.get("loan_status") or "Unknown",
                })

            if borrower_table:
                st.dataframe(
                    pd.DataFrame(borrower_table),
                    width="stretch",
                    hide_index=True,
                    column_config={column: {"width": "small"} for column in pd.DataFrame(borrower_table).columns},
                )
            else:
                st.info("No active borrowers found.")
        else:
            pass


if __name__ == "__main__":
    home_view()
