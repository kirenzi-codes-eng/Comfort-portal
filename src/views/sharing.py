import io
from datetime import datetime, timedelta
from typing import List, Dict

import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

from src.database.connection import execute_query


@st.cache_data(show_spinner=False, ttl=30)
def fetch_total_interest() -> float:
    rows = execute_query("SELECT COALESCE(SUM(interest_accumulated),0) AS total_interest FROM loans;", params=None, fetch=True)
    return float(rows[0]["total_interest"] or 0) if rows else 0.0


def fetch_member_count() -> int:
    """Fetch member count with 1-minute caching."""
    return fetch_member_count_cached()


@st.cache_data(show_spinner=False, ttl=60)
def fetch_member_count_cached() -> int:
    rows = execute_query("SELECT COUNT(*) AS cnt FROM members;", params=None, fetch=True)
    return int(rows[0]["cnt"]) if rows else 0


@st.cache_data(show_spinner=False, ttl=30)
def fetch_member_interest(member_id: str) -> float:
    rows = execute_query(
        "SELECT COALESCE(SUM(interest_accumulated),0) AS member_interest FROM loans WHERE member_id = %s;",
        params=(member_id,),
        fetch=True,
    )
    return float(rows[0]["member_interest"] or 0) if rows else 0.0


@st.cache_data(show_spinner=False, ttl=30)
def fetch_total_savings(member_id: str) -> float:
    ensure_sharing_tables()
    rows = execute_query(
        "SELECT COALESCE(SUM(amount_paid),0) AS total FROM subscriptions WHERE member_id = %s;",
        params=(member_id,),
        fetch=True,
    )
    contributions = float(rows[0]["total"] or 0) if rows else 0.0

    reduction_rows = execute_query(
        "SELECT COALESCE(SUM(amount),0) AS total_withdrawn FROM member_balance_adjustments WHERE member_id = %s AND adjustment_type = 'withdrawal';",
        params=(member_id,),
        fetch=True,
    )
    withdrawals = float(reduction_rows[0]["total_withdrawn"] or 0) if reduction_rows else 0.0
    return max(contributions - withdrawals, 0.0)


@st.cache_data(show_spinner=False, ttl=30)
def calculate_dividends() -> Dict[str, float]:
    total_interest = fetch_total_interest()
    member_rebate_pool = total_interest * 0.25
    admin_pool = total_interest * 0.15
    global_pool = total_interest * 0.60
    member_count = fetch_member_count() or 1
    global_per_member = global_pool / member_count
    return {
        "total_interest": total_interest,
        "member_rebate_pool": member_rebate_pool,
        "admin_pool": admin_pool,
        "global_pool": global_pool,
        "global_per_member": global_per_member,
        "member_count": member_count,
    }


SHARING_ANNOUNCEMENT_TITLE = "Sharing System Active"


def ensure_sharing_tables() -> None:
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS sharing_workflow_state (
            id INTEGER PRIMARY KEY DEFAULT 1,
            active BOOLEAN NOT NULL DEFAULT FALSE,
            activated_on DATE,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        params=None,
        fetch=False,
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS sharing_withdrawal_requests (
            id SERIAL PRIMARY KEY,
            member_id TEXT NOT NULL,
            amount NUMERIC(12,2) NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            requested_on DATE NOT NULL,
            approved_by TEXT,
            approved_on DATE,
            cycle_on DATE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        params=None,
        fetch=False,
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_sharing_requests_member_cycle
        ON sharing_withdrawal_requests (member_id, cycle_on);
        """,
        params=None,
        fetch=False,
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS announcements (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            posted_by TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        params=None,
        fetch=False,
    )
    execute_query(
        """
        CREATE TABLE IF NOT EXISTS member_balance_adjustments (
            id SERIAL PRIMARY KEY,
            member_id TEXT NOT NULL,
            adjustment_type TEXT NOT NULL DEFAULT 'withdrawal',
            amount NUMERIC(12,2) NOT NULL DEFAULT 0,
            reference TEXT,
            reference_id INTEGER,
            created_on DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """,
        params=None,
        fetch=False,
    )
    execute_query(
        """
        CREATE INDEX IF NOT EXISTS idx_member_balance_adjustments_member
        ON member_balance_adjustments (member_id, adjustment_type, created_on);
        """,
        params=None,
        fetch=False,
    )


def sync_sharing_announcement(active: bool, activated_on: str | None) -> None:
    ensure_sharing_tables()
    title = SHARING_ANNOUNCEMENT_TITLE
    if active and activated_on:
        content = (
            f"Sharing has been activated by the Chairperson on {activated_on}. "
            "Members can now view their take-home balance and request withdrawal within 15 days."
        )
        existing = execute_query(
            "SELECT id FROM announcements WHERE title = %s LIMIT 1;",
            params=(title,),
            fetch=True,
        )
        if existing:
            execute_query(
                "UPDATE announcements SET content = %s, posted_by = %s, created_at = %s WHERE id = %s;",
                params=(content, "Chairperson", datetime.utcnow(), existing[0]["id"]),
                fetch=False,
            )
        else:
            execute_query(
                "INSERT INTO announcements (title, content, posted_by, created_at) VALUES (%s, %s, %s, %s);",
                params=(title, content, "Chairperson", datetime.utcnow()),
                fetch=False,
            )
    else:
        execute_query("DELETE FROM announcements WHERE title = %s;", params=(title,), fetch=False)


def ensure_sharing_workflow_state() -> None:
    if "sharing_workflow" not in st.session_state:
        st.session_state.sharing_workflow = get_sharing_workflow()


def invalidate_sharing_caches() -> None:
    try:
        st.cache_data.clear()
    except Exception:
        pass


def load_sharing_workflow_from_db() -> Dict[str, object]:
    ensure_sharing_tables()
    rows = execute_query(
        "SELECT active, activated_on FROM sharing_workflow_state WHERE id = 1;",
        params=None,
        fetch=True,
    )
    if rows:
        row = rows[0]
        activated_on = row["activated_on"].isoformat() if row["activated_on"] else None
        workflow = {"active": bool(row["active"]), "activated_on": activated_on, "requests": {}}
        sync_sharing_announcement(workflow["active"], workflow["activated_on"])
        return workflow
    workflow = {"active": False, "activated_on": None, "requests": {}}
    sync_sharing_announcement(False, None)
    return workflow


def load_sharing_requests_from_db(cycle_on: str | None) -> Dict[str, Dict[str, object]]:
    ensure_sharing_tables()
    if not cycle_on:
        return {}
    rows = execute_query(
        """
        SELECT member_id, amount, status, requested_on, approved_by, approved_on, cycle_on
        FROM sharing_withdrawal_requests
        WHERE cycle_on = %s
        ORDER BY created_at DESC;
        """,
        params=(cycle_on,),
        fetch=True,
    )
    requests: Dict[str, Dict[str, object]] = {}
    for row in rows:
        member_id = row["member_id"]
        requests[member_id] = {
            "member_id": member_id,
            "amount": float(row["amount"] or 0),
            "status": row["status"],
            "requested_on": row["requested_on"].isoformat() if row["requested_on"] else None,
            "approved_by": row["approved_by"],
            "approved_on": row["approved_on"].isoformat() if row["approved_on"] else None,
            "cycle_on": row["cycle_on"].isoformat() if row["cycle_on"] else None,
        }
    return requests


def save_sharing_workflow_to_db(workflow: Dict[str, object]) -> None:
    ensure_sharing_tables()
    active = bool(workflow.get("active", False))
    activated_on = workflow.get("activated_on")
    execute_query(
        """
        INSERT INTO sharing_workflow_state (id, active, activated_on, updated_at)
        VALUES (1, %s, %s, CURRENT_TIMESTAMP)
        ON CONFLICT (id) DO UPDATE
        SET active = EXCLUDED.active,
            activated_on = EXCLUDED.activated_on,
            updated_at = CURRENT_TIMESTAMP;
        """,
        params=(active, activated_on),
        fetch=False,
    )
    sync_sharing_announcement(active, activated_on if isinstance(activated_on, str) else None)
    invalidate_sharing_caches()


def save_withdrawal_request_to_db(member_id: str, amount: float, cycle_on: str | None) -> bool:
    ensure_sharing_tables()
    if not cycle_on:
        return False
    existing = execute_query(
        """
        SELECT status
        FROM sharing_withdrawal_requests
        WHERE member_id = %s AND cycle_on = %s
        ORDER BY created_at DESC
        LIMIT 1;
        """,
        params=(member_id, cycle_on),
        fetch=True,
    )
    if existing and existing[0]["status"] in ("pending", "approved"):
        return False
    execute_query(
        """
        INSERT INTO sharing_withdrawal_requests (member_id, amount, status, requested_on, cycle_on)
        VALUES (%s, %s, %s, %s, %s);
        """,
        params=(member_id, amount, "pending", datetime.utcnow().date().isoformat(), cycle_on),
        fetch=False,
    )
    return True


def approve_withdrawal_request_to_db(member_id: str, approved_by: str, cycle_on: str | None) -> int | None:
    ensure_sharing_tables()
    if not cycle_on:
        return None

    rows = execute_query(
        """
        UPDATE sharing_withdrawal_requests
        SET status = %s,
            approved_by = %s,
            approved_on = %s
        WHERE member_id = %s AND cycle_on = %s AND status = 'pending'
        RETURNING id, amount;
        """,
        params=("approved", approved_by, datetime.utcnow().date().isoformat(), member_id, cycle_on),
        fetch=True,
    )
    if not rows:
        return None

    request_id = int(rows[0]["id"])
    approved_amount = float(rows[0]["amount"] or 0)
    if approved_amount > 0:
        execute_query(
            """
            INSERT INTO member_balance_adjustments (member_id, adjustment_type, amount, reference, reference_id, created_on)
            VALUES (%s, %s, %s, %s, %s, %s);
            """,
            params=(member_id, "withdrawal", approved_amount, "sharing_withdrawal", request_id, datetime.utcnow().date().isoformat()),
            fetch=False,
        )

    invalidate_sharing_caches()
    return request_id


def get_sharing_workflow() -> Dict[str, object]:
    cached_workflow = st.session_state.get("sharing_workflow")
    if isinstance(cached_workflow, dict):
        return cached_workflow

    workflow = load_sharing_workflow_from_db()
    activated_on = workflow.get("activated_on")
    if isinstance(activated_on, str):
        workflow["requests"] = load_sharing_requests_from_db(activated_on)
    else:
        workflow["requests"] = {}
    st.session_state.sharing_workflow = workflow
    return workflow


def fetch_approved_withdrawals() -> List[Dict[str, object]]:
    ensure_sharing_tables()
    rows = execute_query(
        """
        SELECT member_id, amount, approved_by, approved_on, cycle_on
        FROM sharing_withdrawal_requests
        WHERE status = 'approved'
        ORDER BY approved_on DESC, created_at DESC;
        """,
        params=None,
        fetch=True,
    )
    approved = []
    for row in rows or []:
        approved.append(
            {
                "member_id": row["member_id"],
                "amount": float(row["amount"] or 0),
                "approved_by": row["approved_by"],
                "approved_on": row["approved_on"].isoformat() if row["approved_on"] else None,
                "cycle_on": row["cycle_on"].isoformat() if row["cycle_on"] else None,
            }
        )
    return approved


def get_member_take_home_amount(member_id: str) -> float:
    total_savings = fetch_total_savings(member_id)
    engine = calculate_dividends()
    total_interest = engine["total_interest"]
    member_interest = fetch_member_interest(member_id)
    member_rebate_pool = engine["member_rebate_pool"]
    member_rebate_share = 0.0
    if total_interest > 0:
        member_rebate_share = (member_interest / total_interest) * member_rebate_pool
    reserve = 100000.0
    withdrawable_cash = max(total_savings - reserve, 0.0)
    return withdrawable_cash + member_rebate_share


def render_sharing_header() -> None:
    current_hour = datetime.now().hour
    user_name = st.session_state.get("user_name", "Member")
    greeting = f"Good evening {user_name}"
    if current_hour < 12:
        greeting = f"Good morning {user_name}"
    elif current_hour < 18:
        greeting = f"Good afternoon {user_name}"

    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        .sh-header-card { font-family: 'Inter', sans-serif; border-radius: 24px; padding: 30px 28px; background: linear-gradient(90deg, #1E56A0 0%, #2A74D4 100%); color: #FFFFFF; margin-bottom: 26px; }
        .sh-header-text { font-size: 2.8rem; font-weight: 800; line-height: 1.02; margin: 0; }
        .sh-header-copy { font-size: 1rem; color: rgba(255,255,255,0.92); margin-top: 12px; max-width: 760px; line-height: 1.75; }
        .sh-section-title { font-family: 'Inter', sans-serif; color: #0F172A; font-size: 1.5rem; font-weight: 700; margin: 0 0 20px; }
        .sh-modules-row { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 18px; margin-bottom: 24px; }
        .sh-module-card { border-radius: 16px; min-height: 220px; padding: 24px; display: flex; flex-direction: column; justify-content: space-between; box-shadow: 0 16px 28px rgba(15, 23, 42, 0.08); border: 1px solid rgba(148, 163, 184, 0.22); }
        .sh-module-card.soft-blue { background: linear-gradient(135deg, #eef8ff 0%, #dbeafe 100%); color: #1e3a8a; }
        .sh-module-card.slate { background: linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%); color: #334155; }
        .sh-module-icon { width: 44px; height: 44px; border-radius: 14px; background: rgba(255,255,255,0.18); display: inline-flex; align-items: center; justify-content: center; font-size: 1.1rem; margin-bottom: 18px; }
        .sh-module-title { font-family: 'Inter', sans-serif; font-size: 1.15rem; font-weight: 700; line-height: 1.2; margin: 0 0 14px; }
        .sh-module-copy { font-family: 'Inter', sans-serif; color: #111827; font-size: 0.94rem; line-height: 1.65; margin-bottom: 20px; }
        .sh-module-footer { background: rgba(255,255,255,0.78); border-radius: 16px; padding: 14px 16px; display: flex; justify-content: space-between; align-items: center; border: 1px solid rgba(148, 163, 184, 0.16); }
        .sh-module-footer strong { font-family: 'Inter', sans-serif; font-size: 1rem; color: #0f172a; }
        .sh-module-footer span { font-family: 'Inter', sans-serif; font-size: 0.9rem; color: #64748b; }
        .sh-notice { background: #fef3c7; border: 1px solid #f59e0b; border-left: 5px solid #f59e0b; border-radius: 22px; padding: 22px; color: #92400E; box-shadow: 0 18px 40px rgba(217, 119, 14, 0.14); margin-bottom: 28px; }
        .sh-ledger { display: grid; gap: 16px; margin-bottom: 24px; }
        .sh-ledger-row { display: grid; grid-template-columns: 1.2fr 0.8fr; gap: 14px; align-items: center; padding: 20px 24px; border-radius: 22px; background: #ffffff; box-shadow: 0 16px 34px rgba(15, 23, 42, 0.06); }
        .sh-ledger-label { font-family: 'Inter', sans-serif; color: #475569; font-size: 0.95rem; font-weight: 600; }
        .sh-ledger-value { font-family: 'Inter', sans-serif; color: #0F172A; font-size: 1.1rem; font-weight: 700; text-align: right; }
        .sh-ledger-highlight { border: 2px dashed #059669; background: linear-gradient(135deg, rgba(5,150,105,0.12), rgba(236,253,245,0.88)); padding: 26px; border-radius: 24px; display: grid; gap: 10px; }
        .sh-ledger-highlight-title { font-family: 'Inter', sans-serif; font-size: 0.95rem; font-weight: 800; color: #064E3B; text-transform: uppercase; letter-spacing: 0.12em; margin: 0; }
        .sh-ledger-highlight-amount { font-family: 'Inter', sans-serif; font-size: 2.05rem; font-weight: 800; color: #064E3B; margin: 0; }
        .sh-summary-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 18px; margin-top: 24px; }
        .sh-summary-card { border-radius: 18px; padding: 22px; background: #ffffff; box-shadow: 0 18px 30px rgba(15, 23, 42, 0.08); border: 1px solid rgba(148, 163, 184, 0.16); }
        .sh-summary-card.primary { background: linear-gradient(135deg, #dbeafe 0%, #bfdbfe 100%); color: #1e3a8a; }
        .sh-summary-card.secondary { background: linear-gradient(135deg, #ecfeff 0%, #cffafe 100%); color: #115e59; }
        .sh-summary-card-label { font-family: 'Inter', sans-serif; font-size: 0.95rem; font-weight: 700; margin: 0 0 16px; line-height: 1.4; }
        .sh-summary-card-value { font-family: 'Inter', sans-serif; font-size: 1.9rem; font-weight: 800; margin: 0; }
        .sh-summary-card-note { font-family: 'Inter', sans-serif; font-size: 0.9rem; color: rgba(30, 41, 59, 0.74); margin-top: 12px; }
        .sh-exec-panel { background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%); border: 1px solid #e2e8f0; border-radius: 24px; padding: 24px; margin-top: 28px; box-shadow: 0 18px 36px rgba(15, 23, 42, 0.06); }
        .sh-exec-title { font-family: 'Inter', sans-serif; font-size: 1.35rem; font-weight: 800; color: #0f172a; margin: 0 0 8px; }
        .sh-exec-subtitle { font-family: 'Inter', sans-serif; font-size: 0.95rem; color: #475569; line-height: 1.7; margin-bottom: 18px; }
        .sh-exec-metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; margin-bottom: 18px; }
        .sh-exec-metric { background: #ffffff; border-radius: 16px; padding: 16px 18px; border: 1px solid #e2e8f0; }
        .sh-exec-metric-label { font-size: 0.86rem; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.1em; margin-bottom: 8px; }
        .sh-exec-metric-value { font-size: 1.35rem; font-weight: 800; color: #0f172a; }
        .sh-exec-table { width: 100%; border-collapse: collapse; background: #ffffff; border-radius: 16px; overflow: hidden; }
        .sh-exec-table th, .sh-exec-table td { padding: 12px 14px; border-bottom: 1px solid #e2e8f0; text-align: left; font-size: 0.92rem; }
        .sh-exec-table th { background: #f8fafc; color: #0f172a; font-weight: 700; }
        .sh-exec-placeholder { background: #f8fafc; border: 1px dashed #cbd5e1; border-radius: 16px; padding: 18px; color: #475569; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class='sh-header-card'>
          <div class='sh-header-text'>{greeting}</div>
          <div class='sh-header-copy'>This dashboard gives you a clean view of allocation performance, available cash, and savings health in one consistent workflow.</div>
        </div>
        <div class='sh-notice' style='margin-top: 8px;'>
          <strong>Withdrawal Policy:</strong> After the Chairperson activates sharing, members can view their take-home balance and request withdrawal within 15 days. Each member may withdraw once per cycle, and the savings reserve remains at UGX 100,000 until the next month.
        </div>
        <div class='sh-section-title'>My Allocation Profiles</div>
        """,
        unsafe_allow_html=True,
    )


def render_allocation_profile_blocks(total_savings: float, withdrawable_cash: float, reserve_shortfall: float) -> None:
    profiles = [
        {
            "variant": "soft-blue",
            "title": "Savings Balance",
            "copy": "Your total savings in the fund.",
            "value": f"UGX {total_savings:,.0f}",
            "status": "Good" if total_savings >= 100000 else "Needs more",
        },
    ]

    cols = st.columns(1, gap="large")
    for col, profile in zip(cols, profiles):
        with col:
            st.markdown(
                f"""
                <div class='sh-module-card {profile['variant']}'>
                  <div>
                    <div class='sh-module-icon'>📂</div>
                    <div class='sh-module-title'>{profile['title']}</div>
                    <div class='sh-module-copy'>{profile['copy']}</div>
                  </div>
                  <div class='sh-module-footer'>
                    <strong>{profile['value']}</strong>
                    <span>{profile['status']}</span>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_sharing_workflow_controls(user_role: str, user_id: str) -> None:
    workflow = get_sharing_workflow()
    active = bool(workflow.get("active", False))
    activated_on = workflow.get("activated_on")
    requests = workflow.get("requests", {})
    if not isinstance(requests, dict):
        requests = {}
        workflow["requests"] = requests

    if user_role == "Chairperson":
        st.markdown("### Sharing Control")
        if active:
            st.success("Sharing system is active.")
            if isinstance(activated_on, str):
                activated_date = datetime.strptime(activated_on, "%Y-%m-%d").date()
                deadline = activated_date + timedelta(days=15)
                days_left = max((deadline - datetime.utcnow().date()).days, 0)
                st.caption(f"Withdrawal window is open for {days_left} more day(s) from the activation date.")
        else:
            st.info("Sharing system is not active yet. Activate it to open the workflow for members.")

        if st.button("Deactivate Sharing System" if active else "Activate Sharing System", key="toggle_sharing_system"):
            workflow["active"] = not active
            if workflow["active"]:
                workflow["activated_on"] = datetime.utcnow().date().isoformat()
            else:
                workflow["activated_on"] = None
            save_sharing_workflow_to_db(workflow)
            st.session_state.sharing_workflow = workflow
            st.rerun()

    if active and user_role in ("Treasurer", "Chairperson"):
        pending_requests = [
            (member_id, request)
            for member_id, request in requests.items()
            if request.get("status") == "pending"
        ]
        if pending_requests:
            st.markdown("#### Pending Withdrawal Requests")
            for member_id, request in pending_requests:
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.write(f"{member_id}: UGX {request.get('amount', 0):,.0f} pending")
                with col2:
                    if st.button("Approve", key=f"approve_{member_id}"):
                        request["status"] = "approved"
                        request["approved_by"] = user_role
                        request["approved_on"] = datetime.utcnow().date().isoformat()
                        approve_withdrawal_request_to_db(member_id, user_role, workflow.get("activated_on"))
                        st.session_state.sharing_workflow = workflow
                        st.rerun()

        approved_withdrawals = fetch_approved_withdrawals()
        if approved_withdrawals:
            st.markdown("#### Approved Withdrawal Tracker")
            tracker_df = pd.DataFrame(approved_withdrawals)
            tracker_df = tracker_df[["member_id", "amount", "approved_by", "approved_on", "cycle_on"]].copy()
            tracker_df = tracker_df.rename(
                columns={
                    "member_id": "Member ID",
                    "amount": "Amount",
                    "approved_by": "Approved By",
                    "approved_on": "Approval Date",
                    "cycle_on": "Cycle",
                }
            )
            tracker_df["Amount"] = tracker_df["Amount"].map(lambda v: f"UGX {v:,.0f}")
            st.dataframe(tracker_df, use_container_width=True, hide_index=True)
        else:
            st.info("No approved withdrawals yet.")


def member_view(member_id: str):
    total_savings = fetch_total_savings(member_id)
    engine = calculate_dividends()
    total_interest = engine["total_interest"]

    member_interest = fetch_member_interest(member_id)
    member_rebate_pool = engine["member_rebate_pool"]
    member_rebate_share = 0.0
    if total_interest > 0:
        member_rebate_share = (member_interest / total_interest) * member_rebate_pool

    reserve = 100000.0
    withdrawable_cash = max(total_savings - reserve, 0.0)
    reserve_shortfall = max(reserve - total_savings, 0.0)
    take_home_amount = withdrawable_cash + member_rebate_share

    workflow = get_sharing_workflow()
    active = bool(workflow.get("active", False))
    activated_on = workflow.get("activated_on")
    requests = workflow.get("requests", {})
    if not isinstance(requests, dict):
        requests = {}
        workflow["requests"] = requests
    request_status = None
    if isinstance(requests, dict):
        request_details = requests.get(member_id, {})
        if isinstance(request_details, dict):
            request_status = request_details.get("status")
    window_open = False
    if active and isinstance(activated_on, str):
        activated_date = datetime.strptime(activated_on, "%Y-%m-%d").date()
        deadline = activated_date + timedelta(days=15)
        window_open = (datetime.utcnow().date() <= deadline)

    if reserve_shortfall > 0:
        st.markdown(
            f"""
            <div class='sh-notice'>
              <strong>Reserve shortfall warning:</strong> Your registered savings are below the required reserve buffer of 100,000 UGX by <strong>{reserve_shortfall:,.0f} UGX</strong>. This reserve is mandatory before withdrawable cash becomes available.
            </div>
            """,
            unsafe_allow_html=True,
        )

    render_allocation_profile_blocks(total_savings, withdrawable_cash, reserve_shortfall)

    st.markdown(
        f"""
        <div class='sh-summary-grid'>
          <div class='sh-summary-card primary'>
            <div class='sh-summary-card-label'>Rebate Share</div>
            <div class='sh-summary-card-value'>UGX {member_rebate_share:,.0f}</div>
            <div class='sh-summary-card-note'>Your share from loan interest.</div>
          </div>
          <div class='sh-summary-card secondary'>
            <div class='sh-summary-card-label'>Take Home Amount</div>
            <div class='sh-summary-card-value'>UGX {take_home_amount:,.0f}</div>
            <div class='sh-summary-card-note'>Amount available for withdrawal.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if active:
        if request_status == "approved":
            st.success("Withdrawal accepted. Your take-home balance has been processed.")
        elif request_status == "pending":
            st.info("Withdrawal request sent. Waiting for Treasurer approval.")
        elif window_open and take_home_amount > 0:
            if st.button(f"Request Withdrawal of UGX {take_home_amount:,.0f}", key=f"withdraw_{member_id}"):
                cycle_on = workflow.get("activated_on") if isinstance(workflow.get("activated_on"), str) else None
                if save_withdrawal_request_to_db(member_id, take_home_amount, cycle_on):
                    requests[member_id] = {
                        "member_id": member_id,
                        "amount": take_home_amount,
                        "status": "pending",
                        "requested_on": datetime.utcnow().date().isoformat(),
                    }
                    workflow["requests"] = requests
                    st.session_state.sharing_workflow = workflow
                    st.success("Withdrawal request sent to the Treasurer.")
                    st.rerun()
                else:
                    st.warning("A withdrawal request already exists for this member in this cycle.")
        elif not window_open:
            st.warning("The 15-day withdrawal window has closed for this cycle.")
        else:
            st.info("No take-home amount is available for withdrawal right now.")
    else:
        st.info("Sharing is not active yet. The Chairperson must activate it first.")


def fetch_members_overview(limit: int = 50) -> List[Dict]:
    rows = execute_query(
        "SELECT member_id, full_name FROM members ORDER BY full_name LIMIT %s;",
        params=(limit,),
        fetch=True,
    )
    members = []
    if not rows:
        return members
    engine = calculate_dividends()
    total_interest = engine["total_interest"]
    member_rebate_pool = engine["member_rebate_pool"]
    global_per_member = engine["global_per_member"]

    for r in rows:
        mid = r["member_id"]
        name = r["full_name"]
        total_savings = fetch_total_savings(mid)
        member_interest = fetch_member_interest(mid)
        rebate_share = 0.0
        if total_interest > 0:
            rebate_share = (member_interest / total_interest) * member_rebate_pool
        dividend_share = rebate_share + global_per_member
        withdrawable = max(total_savings - 100000.0, 0.0)
        net_payout = withdrawable + dividend_share
        members.append(
            {
                "member_id": mid,
                "full_name": name,
                "total_savings": total_savings,
                "dividend_share": dividend_share,
                "net_payout": net_payout,
            }
        )
    return members


def generate_pdf_report(members: List[Dict]) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("End-of-Year Dividend Report", styles["Title"]))
    elements.append(Paragraph(f"Generated: {datetime.utcnow().isoformat()}", styles["Normal"]))
    elements.append(Spacer(1, 12))

    data = [["Member ID", "Name", "Total Savings", "Dividend Share", "Net Payout"]]
    for m in members:
        data.append([
            m["member_id"],
            m["full_name"],
            f"{m['total_savings']:,.0f}",
            f"{m['dividend_share']:,.0f}",
            f"{m['net_payout']:,.0f}",
        ])

    table = Table(data, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d3d3d3")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
                ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ]
        )
    )
    elements.append(table)
    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()
    return pdf


def sharing_view():
    user_role = st.session_state.get("user_role") or ""
    user_id = st.session_state.get("user_id")

    if not user_id:
        st.info("Log in to view dividend allocations.")
        return

    render_sharing_header()
    render_sharing_workflow_controls(user_role, user_id)
    # Member interface
    member_view(user_id)

    # Executive controls
    if user_role in ("Treasurer", "Chairperson"):
        members = fetch_members_overview(limit=50)
        total_members = len(members)
        total_savings = sum(m["total_savings"] for m in members)
        total_dividend = sum(m["dividend_share"] for m in members)
        total_net = sum(m["net_payout"] for m in members)

        st.markdown(
            f"""
            <div class='sh-exec-panel'>
              <div class='sh-exec-title'>Executive Overview & PDF Export</div>
              <div class='sh-exec-subtitle'>A refined distribution summary for leadership review, showing membership coverage, aggregate savings exposure, and total payout projections.</div>
              <div class='sh-exec-metric-grid'>
                <div class='sh-exec-metric'>
                  <div class='sh-exec-metric-label'>Members Included</div>
                  <div class='sh-exec-metric-value'>{total_members}</div>
                </div>
                <div class='sh-exec-metric'>
                  <div class='sh-exec-metric-label'>Aggregate Withdrawable + Dividends</div>
                  <div class='sh-exec-metric-value'>UGX {total_net:,.0f}</div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if members:
            exec_df = pd.DataFrame(members)
            exec_df = exec_df[["member_id", "full_name", "total_savings", "dividend_share", "net_payout"]].copy()
            exec_df = exec_df.rename(
                columns={
                    "member_id": "Member ID",
                    "full_name": "Member Name",
                    "total_savings": "Total Savings",
                    "dividend_share": "Dividend Share",
                    "net_payout": "Net Payout",
                }
            )
            exec_df["Total Savings"] = exec_df["Total Savings"].map(lambda v: f"UGX {v:,.0f}")
            exec_df["Dividend Share"] = exec_df["Dividend Share"].map(lambda v: f"UGX {v:,.0f}")
            exec_df["Net Payout"] = exec_df["Net Payout"].map(lambda v: f"UGX {v:,.0f}")
            st.dataframe(exec_df, use_container_width=True, hide_index=True)

            if st.button("Generate PDF Report"):
                try:
                    pdf_bytes = generate_pdf_report(members)
                    st.download_button(
                        "Download Dividend Report (PDF)",
                        data=pdf_bytes,
                        file_name=f"dividend_report_{datetime.utcnow().date().isoformat()}.pdf",
                        mime="application/pdf",
                    )
                except Exception as e:
                    st.error(f"Failed to generate PDF: {e}")
        else:
            st.markdown("<div class='sh-exec-placeholder'>No members to report.</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    sharing_view()
