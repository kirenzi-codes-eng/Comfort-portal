import logging
import os
import sys
import psycopg2
import pandas as pd
import streamlit as st
import time
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from html import escape
from typing import Optional
from urllib.parse import quote

from src.components.auth import get_avatar
from src.database.connection import DatabaseUnavailableError, execute_query
from src.utils.membership import (
    get_membership_status_for_db,
    sanitize_member_status_records,
)
from src.utils.schema_compat import column_exists
from src.utils.balances import (
    INACTIVE_ARREARS_THRESHOLD,
    get_admin_dashboard_balances,
    get_effective_member_balance,
    get_effective_pool_balance,
    get_effective_pool_welfare_balance,
    get_loan_portfolio,
    get_member_balance_breakdown,
    get_member_activity_summary,
    get_member_loan_accounts,
    get_member_loan_outstanding_total,
    get_member_subscription_arrears,
    get_subscription_arrears,
    get_subscription_history,
    get_subscription_totals,
    get_loan_records,
    get_member_welfare_reserve_balance,
)
from src.utils.timezone import now_in_uganda

logger = logging.getLogger(__name__)

GLOBAL_FINANCIAL_UPDATE_ROLES = frozenset(
    {"Chairperson", "Vice Chairperson", "Secretary", "Treasurer", "Welfare"}
)

MOCK_FINANCIAL_METRICS = {
    "total_paid": 820000.0,
    "loan_balance": 260000.0,
    "arrears": 42000.0,
}

MOCK_ADMIN_METRICS = {
    "total_pool_savings": 7420000.0,
    "total_cash_loaned": 1840000.0,
    "total_unpaid_interest": 0.0,
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
    except DatabaseUnavailableError as exc:
        logger.warning("Database unavailable during query; using fallback data: %s", exc)
        return fallback
    except psycopg2.Error as exc:
        if _is_table_missing_error(exc):
            logger.warning("Missing table detected in query, using fallback data: %s", query)
            return fallback
        logger.exception("Unexpected database error during query: %s", query)
        return fallback


def _members_key_expression(alias: str) -> str:
    """Return the member join key used by the active database schema."""
    if column_exists("members", "member_id"):
        return f"{alias}.member_id::text"
    return f"{alias}.id::text"


@st.cache_data(ttl=300)
def get_announcements_cached():
    """Cached announcements with 5-minute TTL."""
    rows = safe_execute_query(ANNOUNCEMENTS_QUERY, params=None, fetch=True, fallback=MOCK_ANNOUNCEMENTS)
    return [row for row in (rows or []) if isinstance(row, dict)]


ANNOUNCEMENTS_QUERY = "SELECT title, content, posted_by, created_at FROM announcements ORDER BY created_at DESC;"


def post_announcement(title: str, content: str, posted_by: str) -> None:
    insert_sql = (
        "INSERT INTO announcements (title, content, posted_by, created_at) VALUES (%s, %s, %s, %s);"
    )
    execute_query(insert_sql, params=(title, content, posted_by, datetime.utcnow()), fetch=False)
    get_announcements_cached.clear()  # type: ignore[attr-defined]


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

    from src.views.loans import fetch_latest_member_loan, get_loan_interest_schedule

    latest_loan = fetch_latest_member_loan(user_id)
    if not latest_loan or latest_loan.get("status") not in ("Active", "Approved"):
        return None

    next_due, _ = get_loan_interest_schedule(
        latest_loan.get("approved_date") or latest_loan.get("applied_date"),
        latest_loan.get("last_interest_applied_at"),
        latest_loan.get("last_payment_applied_at"),
    )
    return next_due


def get_member_actual_loan_balance(user_id: Optional[str]) -> Optional[float]:
    if not user_id:
        return None
    total = get_member_loan_outstanding_total(user_id)
    if total <= 0:
        return None
    return total


def get_member_activity_timeline(user_id: Optional[str], limit: int = 6) -> list[dict]:
    if not user_id:
        return []

    subscription_rows = get_subscription_history(member_id=user_id)
    loan_rows = get_loan_records(member_id=user_id)

    events: list[dict] = []
    for row in subscription_rows:
        timestamp = parse_db_datetime(row.get("approved_at") or row.get("billing_month"))
        if timestamp is None:
            continue
        amount = float(row.get("amount_paid") or 0.0)
        payer_name = str(row.get("full_name") or "Member account")
        transaction_title = (
            "Subscription payment reversed"
            if row.get("category") == "REVERSAL"
            else "Subscription payment • Approved"
        )
        events.append(
            {
                "kind": "subscription",
                "title": transaction_title,
                "description": f"Paid by: {payer_name} | Amount: {format_currency(amount)} | Billing month: {timestamp.strftime('%B %Y')} | Reference: {row.get('reference') or 'Not available'}",
                "follow_up": "No action required.",
                "timestamp": timestamp,
            }
        )

    for row in loan_rows:
        timestamp = parse_db_datetime(row.get("approved_date") or row.get("applied_date"))
        if timestamp is None:
            continue
        amount = float(row.get("amount_requested") or 0.0)
        outstanding_balance = float(row.get("outstanding_balance") or 0.0) if row.get("ledger_backed") else 0.0
        status = str(row.get("status") or "Submitted").strip().title()
        reference = row.get("loan_id") or "Not available"
        applicant_name = str(row.get("applicant_name") or "Member account")
        approver_name = str(row.get("approved_by") or "Awaiting approval")
        if status.lower() in {"submitted", "pending", "applied"}:
            follow_up = "Review application and confirm approval status."
        elif outstanding_balance > 0:
            follow_up = f"Follow up on repayment balance: {format_currency(outstanding_balance)} outstanding."
        else:
            follow_up = "Loan appears settled; confirm closure records."
        events.append(
            {
                "kind": "loan",
                "title": f"Loan application • {status}",
                "description": f"Applied by: {applicant_name} | Requested: {format_currency(amount)} | Outstanding: {format_currency(outstanding_balance)} | Approved by: {approver_name} | Reference: {reference}",
                "follow_up": follow_up,
                "timestamp": timestamp,
            }
        )

    events.sort(key=lambda item: item["timestamp"], reverse=True)
    return events[:limit]


def get_financial_metrics(user_id: str) -> dict:
    """Fetch financial metrics with 60-second cache TTL."""
    if not user_id:
        return MOCK_FINANCIAL_METRICS.copy()
    return get_financial_metrics_cached(user_id)


def get_member_profile_details(user_id: Optional[str]) -> dict:
    if not user_id:
        return {}

    rows = safe_execute_query(
        "SELECT full_name, role, status, join_date FROM members WHERE member_id = %s LIMIT 1;",
        params=(user_id,),
        fetch=True,
        fallback=[],
    ) or []
    return rows[0] if rows else {}


@st.cache_data(ttl=60)
def get_admin_dashboard_metrics() -> dict:
    balances = get_admin_dashboard_balances()
    loan_portfolio = get_loan_portfolio()
    today = today_in_uganda()
    arrears = get_subscription_arrears(today)
    borrower_rows = [
        {
            "member_name": loan["member_name"],
            "loan_status": (
                "Needs ledger reconciliation"
                if not loan["ledger_backed"]
                else loan["status"]
            ),
            "loan_balance": loan["outstanding"],
            "ledger_backed": loan["ledger_backed"],
        }
        for loan in loan_portfolio["loans"]
    ]

    return {
        "total_pool_savings": balances["savings_pool"],
        "total_welfare": balances["welfare_pool"],
        "total_cash_loaned": balances["total_disbursed"],
        "total_interest_collected": balances["interest_collected"],
        "total_unpaid_interest": balances["outstanding_interest"],
        "total_unrepaid_interest": balances["outstanding_interest"],
        "total_unrepaid_principal": loan_portfolio["outstanding_principal"],
        "total_outstanding_loan_balance": loan_portfolio["outstanding_total"],
        "total_repaid": loan_portfolio["outstanding_total"],
        "loans_requiring_reconciliation": loan_portfolio.get("loans_requiring_reconciliation", 0),
        "total_arrears": arrears["total_arrears"],
        "borrowers": borrower_rows,
    }


def render_loan_updates_table(user_role: str, admin_metrics: dict) -> None:
    if user_role not in GLOBAL_FINANCIAL_UPDATE_ROLES:
        return

    borrower_table = []
    for row in admin_metrics.get("borrowers") or []:
        member_name = row.get("member_name") or row.get("Member") or "Unknown"
        loan_balance = row.get("loan_balance", row.get("Loan Balance"))
        loan_balance_value = (
            f"UGX {float(loan_balance):,.0f}"
            if loan_balance is not None
            else "Balance unavailable — reconcile ledger"
        )
        borrower_table.append(
            {
                "Member": member_name,
                "Loan Balance": loan_balance_value,
                "Loan Status": row.get("loan_status") or row.get("Loan Status") or "Unknown",
            }
        )

    st.markdown("### Loan Updates")
    if borrower_table:
        borrower_df = pd.DataFrame(borrower_table)
        st.dataframe(
            borrower_df,
            width="stretch",
            hide_index=True,
            column_config={column: {"width": "small"} for column in borrower_df.columns},
        )
    else:
        st.info("No approved or active loan accounts found.")


@st.cache_data(ttl=60)
def get_financial_metrics_cached(user_id: str) -> dict:
    """Cached version of get_financial_metrics with 1-minute TTL."""
    total_paid = get_subscription_totals(user_id)["total_paid"]
    loan_balance = get_member_loan_outstanding_total(user_id)
    today = today_in_uganda()
    arrears = get_member_subscription_arrears(user_id, today)
    return {
        "total_paid": total_paid,
        "loan_balance": loan_balance,
        "arrears": arrears,
    }



def calculate_member_status(join_date, saving_balance, arrears_balance):
    db_status = get_membership_status_for_db(join_date, saving_balance=saving_balance, arrears_balance=arrears_balance)

    label_map = {
        "Pending": ("Pending", "#F59E0B"),
        "Probationary": ("Probationary", "#D97706"),
        "Active": ("Active", "#2563EB"),
        "Partial Member": ("Partial Member", "#2563EB"),
        "Full Member": ("Full Member", "#059669"),
    }
    membership_label, membership_color = label_map.get(db_status, ("Pending", "#F59E0B"))

    arrears_balance = float(arrears_balance or 0)
    activity_label = "Inactive" if arrears_balance >= INACTIVE_ARREARS_THRESHOLD else "Active"
    activity_color = "#DC2626" if activity_label == "Inactive" else "#059669"

    return membership_label, membership_color, activity_label, activity_color


def format_currency(value) -> str:
    return f"UGX {float(value or 0):,.0f}"


@st.cache_data(ttl=60)
def get_member_summary_stats() -> dict:
    stats = get_member_activity_summary(today_in_uganda())
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
        "active_member_names": stats.get("active_member_names") or [],
        "inactive_member_names": stats.get("inactive_member_names") or [],
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
    first_row = rows[0] if rows else {}
    return first_row.get("join_date")


def get_featured_announcement(announcements):
    if "announcement_index" not in st.session_state:
        st.session_state.announcement_index = 0

    if not announcements:
        return None

    index = st.session_state.announcement_index % len(announcements)
    ann = announcements[index]
    st.session_state.announcement_index = (index + 1) % len(announcements)
    return ann


def render_announcements_carousel(announcements):
    """Render the current announcement without triggering background page reloads."""
    if not announcements:
        st.info("No announcements at this time.")
        return

    # Initialize carousel state
    if "carousel_index" not in st.session_state:
        st.session_state.carousel_index = 0

    total_announcements = len(announcements)
    current_index = st.session_state.carousel_index % total_announcements
    ann = announcements[current_index]

    title_text = escape(str(ann.get("title") or "No announcements yet"))
    content_text = escape(str(ann.get("content") or "New updates will appear here."))
    author_text = escape(str(ann.get("posted_by") or "System"))
    meta_text = escape(str(ann.get("created_at") or ""))

    map_svg = """
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 500">
      <defs>
        <clipPath id="globe-clip">
          <circle cx="870" cy="250" r="225"/>
        </clipPath>
        <radialGradient id="globe-shade" cx="35%" cy="30%" r="75%">
          <stop offset="0" stop-color="#0f766e"/>
          <stop offset="1" stop-color="#022c22"/>
        </radialGradient>
      </defs>
      <circle cx="870" cy="250" r="225" fill="url(#globe-shade)"
              stroke="#ffffff" stroke-opacity=".72" stroke-width="4"/>
      <g clip-path="url(#globe-clip)" fill="none" stroke="#ffffff"
         stroke-opacity=".58" stroke-width="2.5">
        <ellipse cx="870" cy="250" rx="78" ry="225"/>
        <ellipse cx="870" cy="250" rx="158" ry="225"/>
        <path d="M645 250h450"/>
        <ellipse cx="870" cy="250" rx="225" ry="70"/>
        <ellipse cx="870" cy="250" rx="225" ry="145"/>
        <path d="M870 25v450"/>
      </g>
      <g clip-path="url(#globe-clip)" fill="#ffffff" fill-opacity=".24"
         stroke="#ffffff" stroke-opacity=".42" stroke-width="2"
         stroke-linejoin="round">
        <path d="M678 129l25-23 35 5 17 20 29 2 18 23-8 22-27 8-8 28-22 17-8 31-20 9-14-25-5-31-20-20-4-31-18-15z"/>
        <path d="M746 267l27-11 22 18 7 34-14 30-12 45-19 22-14-25-3-40-16-27 7-32z"/>
        <path d="M827 101l18-12 23 6 7 14-13 12-22-4z"/>
        <path d="M854 136l29-17 39 6 20-12 43 13 22 24-11 20-31 4-14 22-27-2-11 25-25 8-19-18-24-4-17-23-22-3-10-18z"/>
        <path d="M913 238l29-12 32 14 18 31-13 34-22 21-12 38-18 13-13-28-4-36-17-25 5-34z"/>
        <path d="M1001 313l23-10 27 8 15 20-10 18-31 4-21-14z"/>
      </g>
    </svg>
    """
    map_data_uri = f"data:image/svg+xml,{quote(map_svg)}"
    background_css = (
        "background-image: linear-gradient(90deg, #064e3b 0%, rgba(6,78,59,.96) 42%, "
        f"rgba(6,78,59,.2) 100%), url('{map_data_uri}'); "
        "background-size: 100% 100%, auto 120%; "
        "background-position: center, right center; background-repeat: no-repeat;"
    )

    # Carousel container - clean HTML with slide animation
    announcement_html = f"""
    <div style="margin-top: 10px; animation: slideIn 0.4s ease-out;">
        <div class="hero-shell" style="{background_css}">
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
    </div>
    """
    
    st.markdown(announcement_html, unsafe_allow_html=True)

def render_member_activity_timeline(events: list[dict]) -> None:
    if not events:
        st.info("No recent account activity yet.")
        return

    st.markdown(
        "<div style='font-size: 1.05rem; font-weight: 700; color: #064E3B; margin: 14px 0 8px;'>Member Activity Timeline</div>",
        unsafe_allow_html=True,
    )
    for event in events:
        timestamp_text = event["timestamp"].strftime("%d %b %Y") if isinstance(event["timestamp"], datetime) else str(event["timestamp"])
        st.markdown(
            f"""
            <div class="timeline-card">
              <span class="timeline-time">{escape(timestamp_text)}</span>
              <div class="timeline-title">{escape(str(event.get('title') or 'Activity'))}</div>
              <div class="timeline-desc">{escape(str(event.get('description') or ''))}</div>
                            <div class="timeline-follow-up"><strong>Follow-up:</strong> {escape(str(event.get('follow_up') or 'No follow-up recorded.'))}</div>
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


def _should_use_mock_data(user_id: Optional[str] = None) -> bool:
    if user_id:
        return False
    return (
        not getattr(st, "_is_running_with_streamlit", False)
        or "pytest" in sys.modules
        or os.getenv("PYTEST_CURRENT_TEST") is not None
        or os.getenv("STREAMLIT_TEST_MODE") == "1"
    )


def render_admin_announcement_manager() -> None:
    if _should_use_mock_data(st.session_state.get("user_id")):
        return

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
            with st.form("announcement_form"):
                title = st.text_input("Title", key="admin_announcement_title")
                content = st.text_area("Content", key="admin_announcement_content")
                posted_by = st.text_input("Posted by", key="admin_announcement_author")
                submitted = st.form_submit_button("Post announcement")

            if submitted:
                if not title.strip() or not content.strip():
                    st.warning("Title and content are required.")
                else:
                    try:
                        execute_query(
                            "INSERT INTO announcements (title, content, posted_by, created_at) VALUES (%s, %s, %s, %s);",
                            params=(title.strip(), content.strip(), posted_by.strip() or "Admin", now_in_uganda()),
                            fetch=False,
                        )
                        get_announcements_cached.clear()  # type: ignore[attr-defined]
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

            with st.form("announcement_form"):
                title = st.text_input("Title", value=str(selected_row.get("title") or ""), key="admin_update_title")
                content = st.text_area("Content", value=str(selected_row.get("content") or ""), key="admin_update_content")
                posted_by = st.text_input("Posted by", value=str(selected_row.get("posted_by") or ""), key="admin_update_author")
                submitted = st.form_submit_button("Update announcement")

            if submitted:
                if not title.strip() or not content.strip():
                    st.warning("Title and content are required.")
                else:
                    try:
                        announcement_id = selected_row.get("id") if selected_row else None
                        if announcement_id is None:
                            st.error("Unable to update announcement because the selected record is invalid.")
                        else:
                            execute_query(
                                "UPDATE announcements SET title = %s, content = %s, posted_by = %s, created_at = %s WHERE id = %s;",
                                params=(title.strip(), content.strip(), posted_by.strip() or "Admin", now_in_uganda(), announcement_id),
                                fetch=False,
                            )
                            get_announcements_cached.clear()  # type: ignore[attr-defined]
                            st.success("Announcement updated successfully.")
                    except psycopg2.Error as exc:
                        st.error(f"Failed to update announcement: {exc}")


def home_view():
    try:
        from src.database.connection import execute_query

        if not getattr(st, "_is_running_with_streamlit", False):
            st.session_state.setdefault("user_role", "Member")
            st.session_state.setdefault("user_name", "Guest")
            st.session_state.setdefault("user_id", None)
            st.session_state.setdefault("join_date", None)
    except Exception:
        pass

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
        .timeline-follow-up {
            margin-top: 8px;
            padding-top: 7px;
            border-top: 1px solid #E2E8F0;
            font-size: 0.82rem;
            color: #92400E;
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

    profile_details = get_member_profile_details(user_id) if user_id else {}
    if profile_details:
        if not user_name or user_name == "Guest":
            user_name = profile_details.get("full_name") or user_name
        if not user_role or user_role == "Member":
            user_role = profile_details.get("role") or user_role
        if join_date is None:
            join_date = profile_details.get("join_date")
            if join_date is not None:
                st.session_state["join_date"] = join_date

    if user_id and not join_date:
        refreshed_join_date = get_member_join_date(user_id)
        if refreshed_join_date is not None:
            st.session_state["join_date"] = refreshed_join_date
            join_date = refreshed_join_date

    if user_id:
        try:
            sanitize_member_status_records()
        except Exception:
            pass

    metrics = {"total_paid": 0, "loan_balance": 0, "arrears": 0}
    announcements = []

    if _should_use_mock_data(user_id):
        metrics = MOCK_FINANCIAL_METRICS.copy()
        announcements = MOCK_ANNOUNCEMENTS
    elif user_id:
        try:
            with st.spinner("Loading data..."):
                refreshed_join_date = get_member_join_date(user_id)
                if refreshed_join_date is not None:
                    st.session_state["join_date"] = refreshed_join_date
                    join_date = refreshed_join_date

                metrics = get_financial_metrics(user_id)
                announcements = get_announcements()
        except Exception:
            metrics = {"total_paid": 0, "loan_balance": 0, "arrears": 0}
            announcements = []
    
    saving_balance = metrics.get("total_paid", 0)
    arrears_balance = metrics.get("arrears", 0)

    allowed_roles = GLOBAL_FINANCIAL_UPDATE_ROLES
    admin_metrics = get_admin_dashboard_metrics() if user_role in allowed_roles else {}
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
                          <div style="font-weight: 700; color: #064E3B; margin-bottom: 4px;">{escape(str(ann.get('title') or 'Untitled'))}</div>
                          <div style="color: #334155; font-size: 0.95rem;">{escape(str(ann.get('content') or ''))}</div>
                          <div style="margin-top: 8px; font-size: 0.76rem; color: #64748B;">Posted by {escape(str(ann.get('posted_by') or 'System'))} • {escape(str(ann.get('created_at') or ''))}</div>
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
        balance_breakdown = get_member_balance_breakdown(user_id) if user_id else {"welfare_balance": 0.0, "savings_balance": 0.0}
        actual_loan_balance = get_member_actual_loan_balance(user_id) if user_id else None
        loan_balance = float(actual_loan_balance if actual_loan_balance is not None else 0)
        member_loan_accounts = get_member_loan_accounts(user_id) if user_id else []
        has_unreconciled_active_loan = any(
            not loan.get("ledger_backed")
            and str(loan.get("status") or "").strip().lower() in {"active", "approved"}
            for loan in member_loan_accounts
        )

        try:
            next_due_date = (
                get_next_loan_due_date(user_id)
                if actual_loan_balance is not None or has_unreconciled_active_loan
                else None
            )
        except Exception:
            logger.exception("Unable to load next loan due date")
            next_due_date = None
        if next_due_date:
            next_due_display = next_due_date.strftime("%d %b %Y")
        elif has_unreconciled_active_loan:
            next_due_display = "Ledger reconciliation required"
        elif loan_balance > 0:
            next_due_display = "Active loan pending due date"
        else:
            next_due_display = "No active loan"
        loan_balance_display = (
            "Needs reconciliation"
            if has_unreconciled_active_loan and actual_loan_balance is None
            else format_currency(loan_balance)
        )
        alert_class = "action-card--alert" if arrears_balance > 0 else ""
        summary_stats = get_member_summary_stats()
        summary_html = ""
        if summary_stats:
            summary_html = (
                "<div class='summary-grid'>"
                "<div class='summary-card'>"
                "<div class='summary-card-title'>Total members</div>"
                f"<div class='summary-card-value'>{summary_stats.get('total_members', 0)}</div>"
                "</div>"
                "<div class='summary-card'>"
                "<div class='summary-card-title'>Active members</div>"
                f"<div class='summary-card-value'>{summary_stats.get('active_members', 0)}</div>"
                "<details class='summary-members-dropdown'>"
                "<summary>View members</summary>"
                "<ul>"
                + "".join(f"<li>{escape(str(name))}</li>" for name in summary_stats.get("active_member_names", []))
                + ("" if summary_stats.get("active_member_names") else "<li>No active members</li>")
                + "</ul></details>"
                "</div>"
                "<div class='summary-card'>"
                "<div class='summary-card-title'>Inactive members</div>"
                f"<div class='summary-card-value'>{summary_stats.get('inactive_members', 0)}</div>"
                "<details class='summary-members-dropdown'>"
                "<summary>View members</summary>"
                "<ul>"
                + "".join(f"<li>{escape(str(name))}</li>" for name in summary_stats.get("inactive_member_names", []))
                + ("" if summary_stats.get("inactive_member_names") else "<li>No inactive members</li>")
                + "</ul></details>"
                "</div>"
                "<div class='summary-card'>"
                "<div class='summary-card-title'>Required action</div>"
                f"<div class='summary-card-action'>{escape(summary_stats.get('required_action', 'No immediate membership actions pending.'))}</div>"
                "</div>"
                "</div>"
            )

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
            .summary-members-dropdown {{
                margin-top: 8px;
                color: #334155;
                font-size: 0.82rem;
            }}
            .summary-members-dropdown summary {{
                cursor: pointer;
                font-weight: 600;
            }}
            .summary-members-dropdown ul {{
                max-height: 180px;
                overflow-y: auto;
                margin: 6px 0 0;
                padding-left: 20px;
            }}
            .summary-members-dropdown li {{
                padding: 2px 0;
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
                  <div class="action-stat"><span class="action-stat-label">Welfare Reserve</span><span class="action-stat-value">{format_currency(balance_breakdown.get('welfare_balance', 0.0))}</span></div>
                  <div class="action-stat"><span class="action-stat-label">Savings Balance</span><span class="action-stat-value">{format_currency(balance_breakdown.get('savings_balance', 0.0))}</span></div>
                  <div class="action-stat"><span class="action-stat-label">Pending Arrears</span><span class="action-stat-value">{format_currency(arrears_balance)}</span></div>
                </div>
              </div>
              <div class="action-card action-card--loans">
                <div class="action-icon">🏦</div>
                <div class="action-title">Loans &amp; Credit</div>
                <div class="action-stats">
                  <div class="action-stat"><span class="action-stat-label">Outstanding Balance</span><span class="action-stat-value">{loan_balance_display}</span></div>
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
            </div>
            {summary_html}
            """,
            unsafe_allow_html=True,
        )

        render_loan_updates_table(user_role, admin_metrics)

    with right_col:
        if user_role in allowed_roles:
            st.markdown(
                "<div style='font-size: 1.05rem; font-weight: 700; color: #064E3B; margin-bottom: 10px;'>Global Financial Updates</div>",
                unsafe_allow_html=True,
            )

            total_pool_savings = float(admin_metrics.get("total_pool_savings") or 0)
            total_welfare = float(admin_metrics.get("total_welfare") or 0)
            total_cash_loaned = float(admin_metrics.get("total_cash_loaned") or 0)
            total_interest_collected = float(admin_metrics.get("total_interest_collected") or 0)
            total_unrepaid_principal = float(admin_metrics.get("total_unrepaid_principal") or 0)
            total_unrepaid_interest = float(
                admin_metrics.get("total_unrepaid_interest")
                or admin_metrics.get("total_unpaid_interest")
                or 0
            )
            total_outstanding_loan_balance = float(
                admin_metrics.get("total_outstanding_loan_balance")
                or admin_metrics.get("total_repaid")
                or 0
            )
            total_arrears = float(admin_metrics.get("total_arrears") or 0)
            loans_requiring_reconciliation = int(admin_metrics.get("loans_requiring_reconciliation") or 0)
            st.markdown(
                f"""
                <div style="display: grid; grid-template-columns: repeat(1, minmax(0, 1fr)); gap: 12px;">
                  <div class="kpi-card"><div class="kpi-label">Total Savings Pool</div><div class="kpi-value">{format_currency(total_pool_savings)}</div></div>
                  <div class="kpi-card"><div class="kpi-label">Total Welfare</div><div class="kpi-value">{format_currency(total_welfare)}</div></div>
                  <div class="kpi-card"><div class="kpi-label">Total Principal Disbursed (Net of Reversals)</div><div class="kpi-value">{format_currency(total_cash_loaned)}</div></div>
                  <div class="kpi-card"><div class="kpi-label">Total Interest Collected So Far</div><div class="kpi-value">{format_currency(total_interest_collected)}</div><div class="kpi-label">Recorded from repayments since tracking was enabled</div></div>
                  <div class="kpi-card"><div class="kpi-label">Total Unrepaid Principal</div><div class="kpi-value">{format_currency(total_unrepaid_principal)}</div></div>
                  <div class="kpi-card"><div class="kpi-label">Total Unrepaid Interest</div><div class="kpi-value">{format_currency(total_unrepaid_interest)}</div></div>
                  <div class="kpi-card"><div class="kpi-label">Total Outstanding Loan Balance</div><div class="kpi-value">{format_currency(total_outstanding_loan_balance)}</div></div>
                  <div class="kpi-card"><div class="kpi-label">Total Outstanding Arrears</div><div class="kpi-value">{format_currency(total_arrears)}</div></div>
                  <div class="kpi-card"><div class="kpi-label">Loans Requiring Ledger Reconciliation</div><div class="kpi-value">{loans_requiring_reconciliation}</div></div>
                </div>
                """,
                unsafe_allow_html=True,
            )



if __name__ == "__main__":
    home_view()
