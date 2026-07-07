import time
import streamlit as st
from datetime import datetime, date
from typing import Optional, Tuple

import pandas as pd

from src.database.connection import execute_query
from src.utils.membership import normalize_membership_status
from src.views.home import get_financial_metrics, calculate_member_status

LEADERSHIP_ROLES = ("Treasurer", "Secretary", "Chairperson")


def months_between(start_date: datetime, end_date: datetime) -> int:
    return max(0, (end_date.year - start_date.year) * 12 + end_date.month - start_date.month)


def normalize_loan_status(status: Optional[str]) -> str:
    if status is None:
        return "Pending"
    normalized = str(status).strip()
    if not normalized:
        return "Pending"
    return normalized


def render_loan_status_badge(status: Optional[str]) -> str:
    normalized = normalize_loan_status(status)
    if normalized == "Approved":
        return "<span class='loan-badge loan-badge-approved'>Approved</span>"
    if normalized == "Rejected":
        return "<span class='loan-badge loan-badge-rejected'>Rejected</span>"
    if normalized in {"Submitted", "Pending"}:
        return "<span class='loan-badge loan-badge-pending'>Pending</span>"
    return f"<span class='loan-badge loan-badge-default'>{normalized}</span>"


def fetch_latest_member_loan(member_id: Optional[str]) -> Optional[dict]:
    if not member_id:
        return None
    rows = execute_query(
        "SELECT loan_id, amount_requested, status, approved_by, approved_date, applied_date "
        "FROM loans WHERE member_id = %s ORDER BY applied_date DESC, loan_id DESC LIMIT 1;",
        params=(member_id,),
        fetch=True,
    )
    return rows[0] if rows else None


def parse_join_date(join_date) -> Optional[datetime]:
    if join_date is None:
        return None
    if isinstance(join_date, datetime):
        return join_date
    if isinstance(join_date, date):
        return datetime(join_date.year, join_date.month, join_date.day)
    if isinstance(join_date, str):
        cleaned = join_date.strip()
        try:
            return datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
        except ValueError:
            try:
                return datetime.fromisoformat(cleaned)
            except ValueError:
                try:
                    parsed_date = date.fromisoformat(cleaned)
                    return datetime(parsed_date.year, parsed_date.month, parsed_date.day)
                except ValueError:
                    return None
    return None


def pathway_analytics_navigate() -> None:
    st.session_state["navigate_to_pathway_analytics"] = "📝 Subscriptions & Savings"


def render_membership_pathway_roadmap() -> None:
    st.markdown(
        """
        <div class='pathway-cards'>
          <div class='pathway-card pathway-card-accent'>
            <h2 style='margin: 0; font-size: 2rem; color: #92400e;'>Unlock Your Community Credit Portfolio</h2>
            <p style='margin: 12px 0 20px; color: #7c2d12; font-size: 1rem;'>You’re on a positive growth path toward credit confidence. Keep building momentum with these community-ready milestones.</p>
            <ul style='margin: 0; padding-left: 18px; color: #4b3123; font-size: 0.95rem; line-height: 1.8;'>
              <li>Achieve Full Member status through consistent participation.</li>
              <li>Stay active for 60+ days to qualify for enhanced credit access.</li>
              <li>Build a strong savings and repayment history.</li>
              <li>Keep your membership contributions current and visible.</li>
            </ul>
          </div>
          <div class='pathway-card pathway-card-light'>
            <div style='font-size: 0.9rem; font-weight: 700; color: #92400e; margin-bottom: 12px;'>Your Membership Pathway</div>
            <p style='margin: 0 0 18px; color: #475569; font-size: 0.92rem;'>Track progress, see your next benchmarks, and stay motivated toward stronger credit eligibility.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.button(
        "View My Savings Pathway",
        key="view_pathway_analytics",
        on_click=pathway_analytics_navigate,
        help="Go to the subscription and savings pathway page",
    )


def render_denied_loan_pathway(reason: str) -> None:
    st.markdown(
        f"""
        <div style='background: linear-gradient(135deg, #eef2ff 0%, #dbeafe 45%, #bfdbfe 100%); padding: 24px; border-radius: 22px; box-shadow: 0 18px 40px rgba(59, 130, 246, 0.16); margin-bottom: 18px;'>
          <div style='display: flex; flex-direction: column; gap: 18px;'>
            <div>
              <h2 style='margin: 0; font-size: 1.9rem; color: #1e3a8a;'>Loan Application Update</h2>
              <p style='margin: 12px 0 0; color: #334155; font-size: 1rem;'>We are unable to approve your loan request right now for this specific reason:</p>
              <div style='margin-top: 14px; padding: 18px; border-radius: 18px; background: #ffffff; border: 1px solid #c7d2fe;'>
                <p style='margin: 0; color: #1e3a8a; font-size: 0.98rem;'><strong>{reason}</strong></p>
              </div>
            </div>
            <div style='background: #ffffff; border-radius: 22px; padding: 18px; box-shadow: 0 12px 30px rgba(15, 23, 42, 0.08);'>
              <div style='font-size: 0.95rem; font-weight: 700; color: #1e3a8a; margin-bottom: 10px;'>What you can do next</div>
              <ul style='margin: 0; padding-left: 18px; color: #475569; font-size: 0.92rem; line-height: 1.7;'>
                <li>Check your membership status and keep contributing to reach Full Member eligibility.</li>
                <li>Maintain contributions and savings to stay in good standing for future credit access.</li>
                <li>Resolve any existing submitted or active loans before submitting a new request.</li>
                <li>Visit your savings pathway to review progress, contributions, and upcoming benchmarks.</li>
              </ul>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    render_membership_pathway_roadmap()


def inject_loans_theme() -> None:
    st.markdown(
        """
        <style>
        .stApp {
            background: #f8f9fa;
        }
        .form-card {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 12px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
            margin-bottom: 10px;
        }
        .audit-terminal {
            background: #0f172a;
            border: 1px solid #334155;
            border-radius: 10px;
            padding: 10px 12px;
            color: #d1fae5;
            font-family: 'Courier New', Courier, monospace;
            font-size: 0.8rem;
            line-height: 1.5;
            white-space: pre-wrap;
        }
        .lock-container {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 10px 12px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
            margin-bottom: 10px;
        }
        .vitals-panel {
            background: #ffffff;
            border: 1px solid #e5e7eb;
            border-radius: 12px;
            padding: 12px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
        }
        .status-choice {
            display: inline-block;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            background: #f8f9fa;
            color: #334155;
            font-size: 0.72rem;
            font-weight: 700;
            letter-spacing: 0.04em;
            text-transform: uppercase;
            margin-right: 6px;
            margin-bottom: 6px;
        }
        .status-choice.active {
            background: #2563eb;
            color: #ffffff;
        }
        .pathway-cards {
            display: grid;
            grid-template-columns: repeat(2, minmax(0, 1fr));
            gap: 10px;
            align-items: stretch;
            margin-top: 6px;
            margin-bottom: 10px;
        }
        .pathway-card {
            border-radius: 12px;
            padding: 12px;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
        }
        .pathway-card-accent {
            background: #fff8e1;
        }
        .pathway-card-light {
            background: #ffffff;
        }
        .loan-badge {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0.2rem 0.55rem;
            border-radius: 999px;
            font-weight: 700;
            font-size: 0.72rem;
            letter-spacing: 0.03em;
        }
        .loan-badge-pending {
            background: #fef3c7;
            color: #92400e;
        }
        .loan-badge-approved {
            background: #dcfce7;
            color: #166534;
        }
        .loan-badge-rejected {
            background: #fee2e2;
            color: #991b1b;
        }
        .loan-badge-default {
            background: #f8fafc;
            color: #334155;
        }
        @media only screen and (max-width: 768px) {
            .pathway-cards {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def update_interest_accumulation(reference_date: Optional[datetime] = None) -> None:
    """Update outstanding balances for all Approved loans using 10% monthly compounding interest.

    Assumptions:
    - `interest_accumulated` column stores previously accumulated interest.
    - `outstanding_balance` is principal + interest_accumulated.
    - Principal is computed as `outstanding_balance - COALESCE(interest_accumulated, 0)`.
    """
    ref = reference_date or datetime.utcnow()
    rows = execute_query(
        "SELECT loan_id, outstanding_balance, COALESCE(interest_accumulated, 0) AS interest_accumulated, approved_date "
        "FROM loans WHERE status = 'Approved';",
        params=None,
        fetch=True,
    )
    if not rows:
        return

    for loan in rows:
        try:
            loan_id = loan["loan_id"]
            outstanding = float(loan["outstanding_balance"] or 0)
            interest_acc = float(loan["interest_accumulated"] or 0)
            approved_date = loan.get("approved_date")
            if not approved_date:
                continue
            if isinstance(approved_date, str):
                approved_date = datetime.fromisoformat(approved_date)

            months = months_between(approved_date, ref)
            if months <= 0:
                continue

            principal = max(0.0, outstanding - interest_acc)
            compounded = principal * ((1.10) ** months)
            new_interest = compounded - principal
            new_outstanding = compounded

            execute_query(
                "UPDATE loans SET interest_accumulated = %s, outstanding_balance = %s WHERE loan_id = %s;",
                params=(new_interest, new_outstanding, loan_id),
                fetch=False,
            )
        except Exception as e:
            st.error(f"Failed to update interest for loan {loan.get('loan_id')}: {e}")


def validate_personal_loan_eligibility(user_id: Optional[str], user_status: Optional[str]) -> Tuple[bool, Optional[str]]:
    if not user_id:
        return False, "User context is missing. Please log in again."

    normalized_status = normalize_membership_status(user_status)
    if normalized_status != "Full Member":
        return False, (
            f"Your current membership status is '{normalized_status or 'Unknown'}'. "
            "Loan applications are only available to Full Members."
        )

    join_date = st.session_state.get("join_date")
    join_datetime = parse_join_date(join_date)
    if not join_datetime:
        return False, "Your account join date could not be verified from your profile."

    days_since_join = (datetime.utcnow() - join_datetime).days
    if days_since_join < 60:
        return False, (
            f"Your account is only {days_since_join} days old. "
            "It must be at least 60 days old to qualify for a loan."
        )

    existing = execute_query(
        "SELECT loan_id FROM loans WHERE member_id = %s AND status IN ('Submitted','Active') ORDER BY applied_date DESC LIMIT 1;",
        params=(user_id,),
        fetch=True,
    )
    if existing:
        return False, "You already have a submitted or active loan record on file."

    return True, None


def derive_member_credit_status(user_id: Optional[str]) -> tuple[str, str, str, str]:
    if not user_id:
        return "Unknown", "#94a3b8", "Unknown", "#94a3b8"

    join_date = st.session_state.get("join_date")
    metrics = get_financial_metrics(user_id)
    saving_balance = float(metrics.get("total_paid", 0) or 0)
    arrears_balance = float(metrics.get("arrears", 0) or 0)
    membership_label, membership_color, activity_label, activity_color = calculate_member_status(
        join_date, saving_balance, arrears_balance
    )
    return membership_label, membership_color, activity_label, activity_color


def render_personal_credit_desk(user_id: Optional[str], user_status: Optional[str]) -> None:
    if not user_id or not user_status:
        st.warning("Unable to load your personal credit desk because user information is incomplete.")
        return

    membership_label, membership_color, activity_label, activity_color = derive_member_credit_status(user_id)

    st.markdown(
        f"""
        <div style='background: linear-gradient(135deg, #0066FF 0%, #1E40AF 100%); border: 1px solid #2563eb; border-radius: 16px; padding: 14px; box-shadow: 0 10px 24px rgba(0, 102, 255, 0.18); margin-bottom: 12px;'>
          <div style='display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap;'>
            <div style='min-width: 0;'>
              <h1 style='margin: 0; font-size: 1.25rem; color: #ffffff;'>Personal Credit Desk</h1>
              <p style='margin: 4px 0 0; color: #eff6ff; font-size: 0.8rem;'>Apply for credit, preview repayment, and see your personal loan calculations in real time.</p>
            </div>
            <div style='display: flex; gap: 6px; flex-wrap: wrap;'>
              <div style='display: inline-flex; align-items: center; justify-content: center; padding: 0.2rem 0.55rem; border-radius: 999px; background: {membership_color}; color: white; font-weight: 700; font-size: 0.72rem;'>Membership: {membership_label}</div>
              <div style='display: inline-flex; align-items: center; justify-content: center; padding: 0.2rem 0.55rem; border-radius: 999px; background: {activity_color}; color: white; font-weight: 700; font-size: 0.72rem;'>Activity: {activity_label}</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left_col, right_col = st.columns([5, 5], gap="small")
    requested_amount = 5000.0
    purpose = ""
    application_submitted = False
    eligibility_reason = None

    with left_col:
        st.markdown(
            """
            <div style='background: #ffffff; border: 1px solid #e5e7eb; border-radius: 16px; padding: 14px 14px 12px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06); margin-bottom: 10px;'>
              <h3 style='margin: 0 0 6px; font-size: 1rem; color: #0f172a;'>Loan Application</h3>
              <p style='margin: 0; color: #475569; font-size: 0.82rem; line-height: 1.5;'>Fill the request details below, then submit when ready. Your eligibility will be checked automatically.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        st.markdown("<div class='form-card'>", unsafe_allow_html=True)
        with st.form("personal_loan_form"):
            requested_amount = st.number_input(
                "Requested Amount (UGX)",
                min_value=1000.0,
                max_value=300000.0,
                value=5000.0,
                step=100.0,
                help="Enter the amount you want to borrow. Maximum 300,000 UGX.",
            )
            purpose = st.text_area(
                "Purpose (optional)",
                placeholder="e.g. farm inputs, school fees, emergency repairs",
                height=140,
            )
            st.markdown(
                """
                <div style='background: #f8f9fa; border-left: 4px solid #2563eb; border-radius: 10px; padding: 10px; margin: 10px 0;'>
                  <strong style='display: block; margin-bottom: 4px; font-size: 0.8rem; color: #1e40af;'>Application rules</strong>
                  <p style='margin: 0; color: #334155; font-size: 0.78rem;'>Membership and account age are validated when you submit. Existing submitted or active loans will pause new applications.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )

            application_submitted = st.form_submit_button("Submit Application")
        st.markdown("</div>", unsafe_allow_html=True)

        if application_submitted:
            eligible, eligibility_reason = validate_personal_loan_eligibility(user_id, user_status)
            if not eligible:
                render_denied_loan_pathway(eligibility_reason or "Your application cannot be processed at this time.")
            else:
                try:
                    execute_query(
                        "INSERT INTO loans (member_id, amount_requested, outstanding_balance, status, applied_date) VALUES (%s, %s, %s, %s, %s);",
                        params=(user_id, requested_amount, requested_amount, "Submitted", datetime.utcnow()),
                        fetch=False,
                    )
                    st.success("Loan application submitted successfully. A leadership review will follow.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Failed to submit application: {e}")

        latest_loan = fetch_latest_member_loan(user_id)
        if latest_loan:
            st.markdown(
                f"""
                <div class='form-card'>
                  <div style='display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap; margin-bottom:8px;'>
                    <div style='font-size:0.8rem; font-weight:800; letter-spacing:0.08em; text-transform:uppercase; color:#64748b;'>Latest Application</div>
                    {render_loan_status_badge(latest_loan.get('status'))}
                  </div>
                  <div style='color:#0f172a; font-size:0.95rem; font-weight:700;'>UGX {float(latest_loan.get('amount_requested') or 0):,.0f}</div>
                  <div style='margin-top:6px; color:#334155; font-size:0.8rem;'>Applied: {latest_loan.get('applied_date') or 'Unknown'}</div>
                  <div style='margin-top:4px; color:#334155; font-size:0.8rem;'>Review: {latest_loan.get('approved_by') or 'Awaiting review by leadership'}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with right_col:
        interest_amount = requested_amount * 0.10
        total_payback = requested_amount + interest_amount
        st.markdown(
            f"""
            <div style='background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);'>
              <div style='display: flex; justify-content: space-between; align-items: baseline; gap: 10px; flex-wrap: wrap;'>
                <div>
                  <div style='font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #64748b;'>Dynamic Calculator</div>
                  <h3 style='margin: 2px 0 0; font-size: 1rem; color: #0f172a;'>Repayment Preview</h3>
                </div>
                <div style='background: #f8f9fa; padding: 0.2rem 0.55rem; border-radius: 999px; color: #2563eb; font-weight: 700; font-size: 0.72rem;'>10% estimate</div>
              </div>

              <div style='margin-top: 10px; display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px;'>
                <div style='background: #f8f9fa; border: 1px solid #e5e7eb; border-radius: 10px; padding: 8px;'>
                  <div style='font-size: 0.7rem; color: #64748b; margin-bottom: 4px;'>Principal</div>
                  <div style='font-size: 0.95rem; font-weight: 700; color: #0f172a;'>UGX {requested_amount:,.0f}</div>
                </div>
                <div style='background: #f8f9fa; border: 1px solid #e5e7eb; border-radius: 10px; padding: 8px;'>
                  <div style='font-size: 0.7rem; color: #64748b; margin-bottom: 4px;'>Estimated Interest</div>
                  <div style='font-size: 0.95rem; font-weight: 700; color: #2563eb;'>UGX {interest_amount:,.0f}</div>
                </div>
                <div style='background: #f8f9fa; border: 1px solid #e5e7eb; border-radius: 10px; padding: 8px;'>
                  <div style='font-size: 0.7rem; color: #64748b; margin-bottom: 4px;'>Total Payback</div>
                  <div style='font-size: 1rem; font-weight: 800; color: #0f172a;'>UGX {total_payback:,.0f}</div>
                </div>
              </div>

              <div style='margin-top: 10px; color: #334155; font-size: 0.78rem; line-height: 1.45;'>Your repayment preview updates automatically when you change the loan amount. This is an estimated 10% interest model for planning purposes.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def render_executive_credit_control(user_role: str) -> None:
    st.markdown(
        """
        <div style='background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 12px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06); margin-bottom: 10px;'>
          <h2 style='margin: 0; font-size: 1.1rem; color: #0f172a;'>Executive Credit Control</h2>
          <p style='margin: 4px 0 0; color: #64748b; font-size: 0.8rem;'>Monitor portfolio health, protect lending standards, and guide approvals with confidence.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if user_role not in LEADERSHIP_ROLES:
        st.warning("You do not have access to Executive Credit Control. Leadership permissions are required.")
        return

    st.markdown(
        """
        <div class='lock-container'>
          <div style='font-size: 0.8rem; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; color: #92400e;'>Access guard</div>
          <div style='margin-top: 8px; color: #78350f;'>Leadership review remains protected. Only approved actions change loan status, and every update is logged for audit visibility.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    metrics = execute_query(
        "SELECT status, COUNT(*) AS count FROM loans WHERE status IN ('Submitted','Approved','Rejected') GROUP BY status;",
        params=None,
        fetch=True,
    )
    totals = {row["status"]: int(row["count"] or 0) for row in metrics} if metrics else {}
    pending_count = totals.get("Submitted", 0)
    approved_count = totals.get("Approved", 0)
    rejected_count = totals.get("Rejected", 0)

    status_filter = st.selectbox(
        "Executive vitals view",
        ["Overview", "Submitted", "Approved", "Rejected"],
        index=0,
        help="Switch the portfolio snapshot to a specific loan status.",
    )

    st.markdown(
        f"""
        <div class='vitals-panel'>
          <div style='display:flex; flex-wrap:wrap; gap:6px; margin-bottom: 10px;'>
            <span class='status-choice active'>Status focus: {status_filter}</span>
            <span class='status-choice'>Pending: {pending_count}</span>
            <span class='status-choice'>Approved: {approved_count}</span>
            <span class='status-choice'>Rejected: {rejected_count}</span>
          </div>
          <div style='display:grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 8px;'>
            <div style='padding: 8px; border-radius: 10px; background:#f8f9fa; border:1px solid #e5e7eb;'><div style='font-size:0.7rem; text-transform:uppercase; letter-spacing:0.08em; color:#64748b;'>Submitted</div><div style='margin-top:4px; font-size:1rem; font-weight:800; color:#0f172a;'>{pending_count}</div></div>
            <div style='padding: 8px; border-radius: 10px; background:#f8f9fa; border:1px solid #e5e7eb;'><div style='font-size:0.7rem; text-transform:uppercase; letter-spacing:0.08em; color:#64748b;'>Approved</div><div style='margin-top:4px; font-size:1rem; font-weight:800; color:#0f172a;'>{approved_count}</div></div>
            <div style='padding: 8px; border-radius: 10px; background:#f8f9fa; border:1px solid #e5e7eb;'><div style='font-size:0.7rem; text-transform:uppercase; letter-spacing:0.08em; color:#64748b;'>Rejected</div><div style='margin-top:4px; font-size:1rem; font-weight:800; color:#0f172a;'>{rejected_count}</div></div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("---")
    st.markdown("### Group Application Processing")
    active_loans_query = (
        "SELECT loan_id, member_id, amount_requested, outstanding_balance, status, applied_date, approved_by "
        "FROM loans WHERE status IN ('Submitted','Approved','Rejected')"
    )
    if status_filter != "Overview":
        active_loans_query += " AND status = %s"
        active_loans = execute_query(
            active_loans_query + " ORDER BY applied_date ASC;",
            params=(status_filter,),
            fetch=True,
        )
    else:
        active_loans = execute_query(
            active_loans_query + " ORDER BY applied_date ASC;",
            params=None,
            fetch=True,
        )

    if not active_loans:
        st.info("No group applications are currently in process.")
    else:
        for loan in active_loans:
            card_cols = st.columns([3, 1], gap="large")
            with card_cols[0]:
                st.markdown(
                    f"""
                    <div style='background: #ffffff; border: 1px solid #e5e7eb; border-radius: 12px; padding: 10px; box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);'>
                      <div style='display: flex; justify-content: space-between; gap: 10px; align-items: center;'>
                        <div>
                          <div style='font-size: 0.82rem; font-weight: 700; color: #2563eb;'>Loan {loan["loan_id"]} · {loan["status"]}</div>
                          <div style='margin-top: 4px; color: #475569; font-size: 0.78rem;'>Member: {loan["member_id"]} · Requested UGX {float(loan.get("amount_requested") or loan.get("outstanding_balance") or 0):,.0f}</div>
                        </div>
                        <div>{render_loan_status_badge(loan.get("status"))}</div>
                      </div>
                      <div style='margin-top: 8px; color: #334155; font-size: 0.76rem;'>Applied: {loan["applied_date"] or 'Unknown'} · Review: {loan.get("approved_by") or 'Awaiting review'}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            with card_cols[1]:
                if loan["status"] == "Submitted":
                    approve_col, reject_col = st.columns(2)
                    if approve_col.button("Approve", key=f"exec_approve_{loan['loan_id']}"):
                        try:
                            execute_query(
                                "UPDATE loans SET status = 'Approved', approved_by = %s, approved_date = %s WHERE loan_id = %s;",
                                params=(user_role, datetime.utcnow(), loan["loan_id"]),
                                fetch=False,
                            )
                            st.success("Loan approved.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to approve loan: {e}")
                    if reject_col.button("Reject", key=f"exec_reject_{loan['loan_id']}"):
                        try:
                            execute_query(
                                "UPDATE loans SET status = 'Rejected', approved_by = %s, approved_date = %s WHERE loan_id = %s;",
                                params=(user_role, datetime.utcnow(), loan["loan_id"]),
                                fetch=False,
                            )
                            st.success("Loan rejected.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Failed to reject loan: {e}")
                else:
                    st.caption(f"{loan['status']} by {loan.get('approved_by') or 'reviewer'}")

    st.markdown("---")
    st.markdown("### Institutional Audit Log")
    audit_rows = execute_query(
        "SELECT loan_id, member_id, approved_by, status, approved_date "
        "FROM loans WHERE approved_by IS NOT NULL ORDER BY approved_date DESC;",
        params=None,
        fetch=True,
    )
    if audit_rows:
        audit_df = pd.DataFrame(audit_rows)
        st.dataframe(
            audit_df,
            width="stretch",
            hide_index=True,
            column_config={column: {"width": "small"} for column in audit_df.columns},
        )
    else:
        st.info("No audit signatures have been recorded yet.")


def loans_view() -> None:
    inject_loans_theme()
    st.markdown(
        """
        <div style="display: inline-flex; align-items: center; justify-content: center; padding: 12px 18px; border-radius: 16px; background: linear-gradient(135deg, #38bdf8 0%, #0ea5e9 100%); box-shadow: 0 14px 30px rgba(14, 165, 233, 0.24); margin-bottom: 18px;">
          <span style="font-size: 1.6rem; font-weight: 800; color: #f8fafc; letter-spacing: 0.04em;">Loans Management</span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.spinner("Loading data..."):
        update_interest_accumulation()

    user_role = st.session_state.get("user_role")
    user_id = st.session_state.get("user_id")
    user_status = st.session_state.get("user_status")

    if not user_role:
        st.info("Log in to access loan functionality.")
        return

    tab_labels = ["Personal Credit Desk", "Executive Credit Control"]
    personal_tab, executive_tab = st.tabs(tab_labels)

    with personal_tab:
        render_personal_credit_desk(user_id, user_status)

    with executive_tab:
        render_executive_credit_control(user_role)


if __name__ == "__main__":
    loans_view()
