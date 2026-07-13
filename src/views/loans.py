import time
import streamlit as st
from datetime import datetime, date
from html import escape
from typing import Any, Optional, Tuple

import pandas as pd

from src.database.connection import execute_query
from src.utils.membership import normalize_membership_status
from src.views.home import get_financial_metrics, calculate_member_status, format_currency

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


def format_money(value: Any | None) -> str:
    try:
        amount = float(value or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return format_currency(amount)


def format_loan_date(value: object | None) -> str:
    if value is None:
        return "Unknown"
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y")
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return "Unknown"
        try:
            parsed = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
            return parsed.strftime("%d %b %Y")
        except ValueError:
            return cleaned
    return str(value)


def fetch_latest_member_loan(member_id: Optional[str]) -> Optional[dict]:
    if not member_id:
        return None
    rows = execute_query(
        "SELECT loan_id, amount_requested, outstanding_balance, COALESCE(interest_accumulated, 0) AS interest_accumulated, status, approved_by, approved_date, applied_date "
        "FROM loans WHERE member_id = %s ORDER BY applied_date DESC, loan_id DESC LIMIT 1;",
        params=(member_id,),
        fetch=True,
    )
    return rows[0] if rows else None


@st.cache_data(ttl=300, show_spinner=False)
def loans_table_has_purpose() -> bool:
    try:
        rows = execute_query(
            "SELECT 1 FROM information_schema.columns WHERE table_name = 'loans' AND column_name = 'purpose' LIMIT 1;",
            fetch=True,
        )
        return bool(rows)
    except Exception:
        return False


def ensure_loans_purpose_column() -> bool:
    """Ensure the loans table has the purpose column for loan request details."""
    try:
        execute_query(
            "ALTER TABLE loans ADD COLUMN IF NOT EXISTS purpose TEXT;",
            params=None,
            fetch=False,
        )
        return loans_table_has_purpose()
    except Exception as exc:
        st.warning(f"Unable to ensure loan purpose column exists: {exc}")
        return loans_table_has_purpose()


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
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        :root {
            --text: #0f172a;
            --surface: #ffffff;
            --page-bg: #f8fafc;
            --border: rgba(15, 23, 42, 0.08);
            --muted: #64748b;
            --accent: #4f46e5;
            --accent-soft: rgba(79, 70, 229, 0.08);
            --success: #0d9488;
            --danger: #dc2626;
            --warning: #f59e0b;
        }

        html, body, .streamlit-expanderHeader, .css-1v3fvcr {
            font-family: 'Inter', 'Plus Jakarta Sans', ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
        }

        .stApp {
            background: var(--page-bg);
            color: var(--text);
        }

        .block-container {
            padding-top: 1.6rem;
            padding-bottom: 2.4rem;
            padding-left: 1.6rem;
            padding-right: 1.6rem;
            max-width: 1700px;
        }

        .loans-page__hero {
            padding: 1.25rem 0 0.75rem;
            margin-bottom: 1.5rem;
        }

        .loans-page__hero-title {
            font-size: clamp(2.2rem, 1.8vw, 3rem);
            line-height: 1.03;
            letter-spacing: -0.02em;
            margin: 0 0 0.35rem;
            font-weight: 800;
            color: var(--text);
        }

        .loans-page__hero-copy {
            color: var(--muted);
            font-size: 1rem;
            max-width: 76ch;
            margin: 0;
            line-height: 1.8;
        }

        .loans-page__divider {
            margin: 1.75rem 0 2rem;
            border-top: 1px solid rgba(15, 23, 42, 0.08);
        }

        .warning-banner {
            display: grid;
            grid-template-columns: auto 1fr;
            gap: 1rem;
            align-items: center;
            padding: 1.2rem 1.25rem;
            border-radius: 22px;
            background: #fffbeb;
            border: 1px solid #f5d7a6;
            color: #92400e;
            margin-bottom: 1.5rem;
        }

        .warning-banner__icon {
            width: 44px;
            height: 44px;
            display: grid;
            place-items: center;
            border-radius: 16px;
            background: rgba(245, 158, 11, 0.12);
            color: #b45309;
            font-size: 1.25rem;
        }

        .warning-banner__body {
            display: grid;
            gap: 0.35rem;
        }

        .warning-banner__title {
            margin: 0;
            font-size: 1rem;
            font-weight: 700;
            color: #92400e;
        }

        .warning-banner__text {
            margin: 0;
            color: #7c2d12;
            font-size: 0.95rem;
            line-height: 1.7;
        }

        .hero-card {
            background: var(--surface);
            border: 1px solid rgba(79, 70, 229, 0.14);
            border-radius: 22px;
            padding: 1.6rem 1.75rem;
            box-shadow: 0 18px 40px rgba(15, 23, 42, 0.06);
            margin-bottom: 1.75rem;
        }

        .hero-card__row {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 1rem;
            align-items: center;
        }

        .hero-card__title {
            margin: 0;
            font-size: clamp(1.85rem, 2vw, 2.5rem);
            line-height: 1.05;
            font-weight: 800;
            color: var(--text);
        }

        .hero-card__subtitle {
            margin: 0.65rem 0 0;
            color: var(--muted);
            font-size: 1rem;
            max-width: 62ch;
            line-height: 1.75;
        }

        .hero-pill {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0.55rem 0.95rem;
            border-radius: 999px;
            font-size: 0.82rem;
            font-weight: 700;
            color: var(--text);
            background: rgba(13, 148, 136, 0.12);
            border: 1px solid rgba(13, 148, 136, 0.16);
            margin-left: 0.5rem;
            white-space: nowrap;
        }

        .hero-pill--secondary {
            background: rgba(59, 130, 246, 0.08);
            border-color: rgba(59, 130, 246, 0.14);
            color: #1e40af;
        }

        .loan-application-card,
        .repayment-preview-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 20px;
            padding: 1.5rem;
            box-shadow: 0 18px 36px rgba(15, 23, 42, 0.06);
        }

        .loan-application-card h3,
        .repayment-preview-card h3 {
            margin: 0 0 1rem;
            font-size: 1.1rem;
            font-weight: 700;
            color: var(--text);
        }

        .loan-application-card .field-row,
        .repayment-preview-card .metric-grid {
            display: grid;
            gap: 1rem;
        }

        .loan-application-card .field-label {
            margin: 0 0 0.4rem;
            font-size: 0.92rem;
            color: var(--muted);
            font-weight: 600;
        }

        .loan-application-card textarea,
        .loan-application-card input[type="number"],
        .loan-application-card input[type="text"] {
            width: 100%;
            border: 1px solid rgba(15, 23, 42, 0.12);
            border-radius: 14px;
            padding: 1rem 1rem;
            background: #ffffff;
            transition: all 0.2s ease;
            font-family: inherit;
            color: var(--text);
            font-size: 0.95rem;
            box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.04);
        }

        .loan-application-card textarea:focus,
        .loan-application-card input[type="number"]:focus,
        .loan-application-card input[type="text"]:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 4px rgba(79, 70, 229, 0.12);
        }

        .loan-application-card textarea {
            min-height: 158px;
            resize: vertical;
        }

        .loan-application-card .submit-row {
            margin-top: 1.5rem;
            display: flex;
            justify-content: flex-start;
        }

        .repayment-preview-card .metric-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 1rem;
            margin-bottom: 1.4rem;
        }

        .repayment-preview-card .metric-block {
            padding: 1rem;
            border-radius: 18px;
            background: #f8fafc;
            border: 1px solid rgba(15, 23, 42, 0.06);
        }

        .metric-block__label {
            margin: 0 0 0.55rem;
            font-size: 0.82rem;
            color: var(--muted);
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }

        .metric-block__value {
            margin: 0;
            font-size: 1.4rem;
            font-weight: 800;
            color: var(--text);
            line-height: 1.1;
        }

        .repayment-preview-card .micro-caption,
        .repayment-preview-card .footnote {
            margin: 0;
            color: #64748b;
            font-size: 0.88rem;
            line-height: 1.7;
        }

        .repayment-preview-card .note-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            gap: 1rem;
            margin-top: 0.5rem;
            flex-wrap: wrap;
        }

        .repayment-preview-card .est-label {
            font-size: 0.82rem;
            color: #64748b;
        }

        .repayment-preview-card .footnote {
            margin-top: 1.35rem;
            color: rgba(100, 116, 139, 0.95);
        }

        input::-webkit-outer-spin-button,
        input::-webkit-inner-spin-button {
            -webkit-appearance: none;
            margin: 0;
        }

        input[type="number"] {
            -moz-appearance: textfield;
        }

        @media only screen and (max-width: 900px) {
            .hero-card__row,
            .metric-grid {
                grid-template-columns: 1fr;
            }
        }

        .metric-grid {
            display: grid;
            grid-template-columns: repeat(3, minmax(0, 1fr));
            gap: 1rem;
            margin-bottom: 1.75rem;
        }

        .metric-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 24px;
            padding: 1.4rem 1.5rem;
            box-shadow: 0 18px 36px rgba(15, 23, 42, 0.06);
        }

        .metric-card__label {
            margin: 0 0 0.75rem;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.14em;
            font-size: 0.78rem;
            font-weight: 700;
        }

        .metric-card__value {
            margin: 0;
            font-size: 2.75rem;
            line-height: 1;
            font-weight: 800;
            color: var(--text);
        }

        .metric-card__note {
            margin: 0.85rem 0 0;
            color: var(--muted);
            font-size: 0.95rem;
            line-height: 1.7;
        }

        .metric-card--accent {
            border-color: rgba(79, 70, 229, 0.16);
        }

        .metric-card--success {
            border-color: rgba(13, 148, 136, 0.18);
        }

        .metric-card--danger {
            border-color: rgba(220, 38, 38, 0.16);
        }

        .list-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 24px;
            padding: 1.5rem;
            box-shadow: 0 18px 36px rgba(15, 23, 42, 0.06);
        }

        .list-card__title {
            margin: 0 0 1rem;
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--text);
        }

        .review-row {
            display: grid;
            grid-template-columns: minmax(0, 1fr) auto;
            gap: 1rem;
            padding: 1rem 0;
            border-top: 1px solid rgba(15, 23, 42, 0.06);
        }

        .review-row:first-child {
            border-top: 0;
        }

        .review-row__details {
            display: grid;
            gap: 0.35rem;
        }

        .review-row__label {
            margin: 0;
            font-size: 0.92rem;
            color: var(--muted);
        }

        .review-row__value {
            margin: 0;
            font-size: 1rem;
            color: var(--text);
            font-weight: 600;
        }

        .review-row__status {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            padding: 0.45rem 0.75rem;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }

        .review-row__status--submitted { background: rgba(79, 70, 229, 0.08); color: #4338ca; }
        .review-row__status--approved { background: rgba(5, 150, 105, 0.12); color: #064e3b; }
        .review-row__status--rejected { background: rgba(220, 38, 38, 0.12); color: #991b1b; }

        .review-row__actions {
            display: grid;
            gap: 0.75rem;
            align-content: center;
        }

        .table-wrapper {
            margin-top: 1rem;
        }

        @media only screen and (max-width: 900px) {
            .metric-grid {
                grid-template-columns: 1fr;
            }
            .review-row {
                grid-template-columns: 1fr;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def update_interest_accumulation(reference_date: Optional[datetime] = None) -> None:
    """Update outstanding balances for older active/approved loans using 10% monthly compounding interest.

    Assumptions:
    - `interest_accumulated` stores previously accumulated interest.
    - `outstanding_balance` is principal + interest_accumulated.
    - Principal is computed as `outstanding_balance - COALESCE(interest_accumulated, 0)`.
    - Older loans without an approved date are backfilled from their applied date.
    """
    ref = reference_date or datetime.utcnow()
    rows = execute_query(
        "SELECT loan_id, outstanding_balance, COALESCE(interest_accumulated, 0) AS interest_accumulated, approved_date, applied_date "
        "FROM loans WHERE status IN ('Approved', 'Active');",
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
            start_date = loan.get("approved_date") or loan.get("applied_date")
            if not start_date:
                continue
            if isinstance(start_date, str):
                start_date = datetime.fromisoformat(start_date)

            months = months_between(start_date, ref)
            if interest_acc == 0 and months >= 0:
                months = max(1, months)
            elif months <= 0:
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
        "SELECT loan_id FROM loans WHERE member_id = %s AND status IN ('Submitted','Active','Approved') ORDER BY applied_date DESC LIMIT 1;",
        params=(user_id,),
        fetch=True,
    )
    if existing:
        return False, "You already have a submitted, active, or approved loan record on file."

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

    with st.container():
        st.markdown(
            f"""
            <div class='hero-card'>
              <div class='hero-card__row'>
                <div>
                  <h2 class='hero-card__title'>Personal Credit Desk</h2>
                  <p class='hero-card__subtitle'>Submit a new loan request, preview repayments, and manage your current credit profile with confidence.</p>
                </div>
                <div style='display:flex; flex-wrap:wrap; justify-content:flex-end; gap:0.75rem;'>
                  <div class='hero-pill'>Membership: {membership_label}</div>
                  <div class='hero-pill hero-pill--secondary'>Activity: {activity_label}</div>
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    col1, col2 = st.columns([3, 2], gap="large")
    requested_amount = 5000.0
    purpose = ""
    application_submitted = False
    eligibility_reason = None

    with col1:
        with st.container():
            st.markdown(
                """
                <div class='loan-application-card'>
                  <h3>Loan Application</h3>
                  <p style='margin: 0 0 1.5rem; color: #64748b; font-size: 0.95rem; line-height: 1.7;'>Fill in your requested amount, share a brief purpose, and submit your loan request for leadership review.</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
            with st.form("personal_loan_form"):
                st.markdown("<div class='loan-application-card'>", unsafe_allow_html=True)
                st.markdown("<label class='field-label' for='requested_amount'>Requested Amount (UGX)</label>", unsafe_allow_html=True)
                requested_amount = st.number_input(
                    "Requested Loan Amount",
                    min_value=1000.0,
                    max_value=300000.0,
                    value=5000.0,
                    step=100.0,
                    format="%f",
                    key="requested_amount",
                    label_visibility="collapsed",
                )
                st.markdown("<label class='field-label' for='purpose'>Purpose (optional)</label>", unsafe_allow_html=True)
                purpose = st.text_area(
                    "Purpose of Loan",
                    placeholder="e.g. farm inputs, school fees, emergency repairs",
                    height=170,
                    key="loan_purpose",
                    label_visibility="collapsed",
                )
                st.markdown(
                    """
                    <div style='margin-top: 1rem; padding: 1rem; border-radius: 16px; background: #f8fafc; border: 1px solid rgba(15, 23, 42, 0.06);'>
                      <div style='font-size: 0.9rem; color: #334155;'>Application rules</div>
                      <p style='margin: 0.55rem 0 0; color: #64748b; font-size: 0.92rem; line-height: 1.7;'>Membership and account age are validated when you submit. Existing submitted or active loans will pause new requests.</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                st.markdown("<div class='submit-row'>", unsafe_allow_html=True)
                application_submitted = st.form_submit_button("Submit Request")
                st.markdown("</div>", unsafe_allow_html=True)
                st.markdown("</div>", unsafe_allow_html=True)

        if application_submitted:
            eligible, eligibility_reason = validate_personal_loan_eligibility(user_id, user_status)
            if not eligible:
                render_denied_loan_pathway(eligibility_reason or "Your application cannot be processed at this time.")
            else:
                try:
                    purpose_supported = ensure_loans_purpose_column()
                    if purpose_supported:
                        execute_query(
                            "INSERT INTO loans (member_id, amount_requested, outstanding_balance, purpose, status, applied_date) VALUES (%s, %s, %s, %s, %s, %s);",
                            params=(user_id, requested_amount, requested_amount, purpose, "Submitted", datetime.utcnow()),
                            fetch=False,
                        )
                    else:
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
            outstanding_balance = format_money(latest_loan.get('outstanding_balance'))
            interest_accumulated = format_money(latest_loan.get('interest_accumulated'))
            requested_amount_display = format_money(latest_loan.get('amount_requested'))
            applied_date = format_loan_date(latest_loan.get('applied_date'))
            approved_date = format_loan_date(latest_loan.get('approved_date'))
            approved_by = latest_loan.get('approved_by') or 'Awaiting review by leadership'
            st.markdown(
                f"""
                <div class='loan-application-card' style='margin-top: 1.5rem;'>
                  <h3>Latest loan snapshot</h3>
                  <div style='display:grid; gap:0.85rem;'>
                    <div style='color:#0f172a; font-weight:700;'>Loan ID: {latest_loan.get('loan_id')}</div>
                    <div style='color:#0f172a;'>Requested: {requested_amount_display}</div>
                    <div style='color:#0f172a;'>Outstanding: {outstanding_balance}</div>
                    <div style='color:#64748b;'>Interest accumulated: {interest_accumulated}</div>
                    <div style='color:#64748b;'>Applied: {applied_date}</div>
                    <div style='color:#64748b;'>Approved: {approved_date}</div>
                    <div style='color:#64748b;'>Review: {approved_by}</div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with col2:
        interest_amount = requested_amount * 0.10
        total_payback = requested_amount + interest_amount
        st.markdown(
            f"""
            <div class='repayment-preview-card'>
              <h3>Repayment Preview</h3>
              <div class='note-row'>
                <p class='est-label'>10% estimated repayment model</p>
                <p class='micro-caption'>Prices are indicative and reviewed at approval.</p>
              </div>
              <div class='metric-grid'>
                <div class='metric-block'>
                  <p class='metric-block__label'>Principal</p>
                  <p class='metric-block__value'>UGX {requested_amount:,.0f}</p>
                </div>
                <div class='metric-block'>
                  <p class='metric-block__label'>Estimated Interest</p>
                  <p class='metric-block__value'>UGX {interest_amount:,.0f}</p>
                </div>
                <div class='metric-block'>
                  <p class='metric-block__label'>Total Payback</p>
                  <p class='metric-block__value'>UGX {total_payback:,.0f}</p>
                </div>
              </div>
              <p class='footnote'>This preview uses a simple 10% interest model for planning purposes only. Final terms are confirmed at loan approval.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    loan_rows = execute_query(
        "SELECT loan_id, amount_requested, outstanding_balance, COALESCE(interest_accumulated,0) AS interest_accumulated, status, approved_by, approved_date, applied_date "
        "FROM loans WHERE member_id = %s ORDER BY applied_date DESC, loan_id DESC;",
        params=(user_id,),
        fetch=True,
    ) or []

    if loan_rows:
        history_data = [
            {
                "Loan ID": row.get("loan_id"),
                "Status": normalize_loan_status(row.get("status")),
                "Requested": format_money(row.get("amount_requested")),
                "Outstanding": format_money(row.get("outstanding_balance")),
                "Interest": format_money(row.get("interest_accumulated")),
                "Applied Date": format_loan_date(row.get("applied_date")),
                "Approved Date": format_loan_date(row.get("approved_date")),
                "Approved By": row.get("approved_by") or "-",
            }
            for row in loan_rows
        ]
        st.markdown("<div class='repayment-preview-card' style='margin-top: 1.5rem;'>", unsafe_allow_html=True)
        st.markdown("<h3 style='margin-top:0;'>Loan History</h3>", unsafe_allow_html=True)
        st.dataframe(
            history_data,
            width="stretch",
            hide_index=True,
            column_config={
                "Loan ID": {"width": "small"},
                "Status": {"width": "small"},
                "Requested": {"width": "medium"},
                "Outstanding": {"width": "medium"},
                "Interest": {"width": "medium"},
                "Applied Date": {"width": "medium"},
                "Approved Date": {"width": "medium"},
                "Approved By": {"width": "medium"},
            },
        )
        st.markdown("</div>", unsafe_allow_html=True)


def render_executive_credit_control(user_role: str) -> None:
    if user_role not in LEADERSHIP_ROLES:
        st.markdown(
            """
            <div class='warning-banner'>
              <div class='warning-banner__icon'>🔒</div>
              <div class='warning-banner__body'>
                <p class='warning-banner__title'>Executive access required</p>
                <p class='warning-banner__text'>Leadership review is restricted to approved roles. Loan portfolio controls are only available to authorized executives.</p>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    metrics = execute_query(
        "SELECT status, COUNT(*) AS count FROM loans WHERE status IN ('Submitted','Approved','Rejected') GROUP BY status;",
        params=None,
        fetch=True,
    )
    totals = {row["status"]: int(row["count"] or 0) for row in metrics} if metrics else {}
    submitted_count = totals.get("Submitted", 0)
    approved_count = totals.get("Approved", 0)
    rejected_count = totals.get("Rejected", 0)

    st.markdown(
        """
        <div class='warning-banner'>
          <div class='warning-banner__icon'>🔒</div>
          <div class='warning-banner__body'>
            <p class='warning-banner__title'>Access guard</p>
            <p class='warning-banner__text'>Leadership review remains protected. Only approved actions change loan status, and every update is logged for audit visibility.</p>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        f"""
        <div class='metric-grid'>
          <div class='metric-card metric-card--accent'>
            <div class='metric-card__label'>In review</div>
            <div class='metric-card__value'>{submitted_count}</div>
            <div class='metric-card__note'>Loans awaiting executive approval or rejection.</div>
          </div>
          <div class='metric-card metric-card--success'>
            <div class='metric-card__label'>Approved</div>
            <div class='metric-card__value'>{approved_count}</div>
            <div class='metric-card__note'>Loans currently active in the portfolio.</div>
          </div>
          <div class='metric-card metric-card--danger'>
            <div class='metric-card__label'>Rejected</div>
            <div class='metric-card__value'>{rejected_count}</div>
            <div class='metric-card__note'>Requests that were declined after executive review.</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    status_tabs = st.tabs(["Review Queue", "Approved Loans", "Rejected Requests"])

    purpose_supported = ensure_loans_purpose_column()
    purpose_column = ", l.purpose" if purpose_supported else ""
    submitted_rows = execute_query(
        f"SELECT l.loan_id, l.member_id, COALESCE(m.full_name, '') AS applicant_name{purpose_column}, l.amount_requested, l.outstanding_balance, COALESCE(l.interest_accumulated, 0) AS interest_accumulated, l.status, l.applied_date, l.approved_date, l.approved_by "
        "FROM loans l LEFT JOIN members m ON m.member_id = l.member_id "
        "WHERE l.status = 'Submitted' ORDER BY l.applied_date ASC;",
        params=None,
        fetch=True,
    ) or []
    approved_rows = execute_query(
        "SELECT loan_id, member_id, amount_requested, outstanding_balance, COALESCE(interest_accumulated, 0) AS interest_accumulated, status, applied_date, approved_date, approved_by "
        "FROM loans WHERE status = 'Approved' ORDER BY approved_date DESC;",
        params=None,
        fetch=True,
    ) or []
    rejected_rows = execute_query(
        "SELECT loan_id, member_id, amount_requested, outstanding_balance, COALESCE(interest_accumulated, 0) AS interest_accumulated, status, applied_date, approved_date, approved_by "
        "FROM loans WHERE status = 'Rejected' ORDER BY approved_date DESC;",
        params=None,
        fetch=True,
    ) or []

    with status_tabs[0]:
        st.markdown("<div class='list-card'><div class='list-card__title'>Executive review queue</div></div>", unsafe_allow_html=True)
        if not submitted_rows:
            st.info("No pending loan submissions are waiting for review.")
        else:
            for loan in submitted_rows:
                with st.container():
                    st.markdown(
                        f"""
                        <div class='list-card'>
                          <div class='review-row'>
                            <div class='review-row__details'>
                              <p class='review-row__label'>Loan ID</p>
                              <p class='review-row__value'>{loan['loan_id']}</p>
                              <p class='review-row__label'>Applicant Name</p>
                              <p class='review-row__value'>{loan.get('applicant_name') or loan['member_id']}</p>
                              <p class='review-row__label'>Member ID</p>
                              <p class='review-row__value'>{loan['member_id']}</p>
                              <p class='review-row__label'>Requested</p>
                              <p class='review-row__value'>{format_money(loan.get('amount_requested'))}</p>
                              <p class='review-row__label'>Purpose</p>
                              <p class='review-row__value'>{escape(str(loan.get('purpose') or 'General loan request'))}</p>
                              <p class='review-row__label'>Applied</p>
                              <p class='review-row__value'>{format_loan_date(loan.get('applied_date'))}</p>
                            </div>
                            <div class='review-row__actions'>
                              <div class='review-row__status review-row__status--submitted'>Pending</div>
                            </div>
                          </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    action_cols = st.columns([1, 1, 2], gap="small")
                    if action_cols[0].button("Approve", key=f"exec_approve_{loan['loan_id']}"):
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
                    if action_cols[1].button("Reject", key=f"exec_reject_{loan['loan_id']}"):
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
                    action_cols[2].markdown(
                        f"<div style='font-size:0.92rem; color:#475569; line-height:1.6;'>Review requested by <strong>{escape(str(loan.get('applicant_name') or loan.get('member_id')))}</strong> for <strong>{escape(str(loan.get('purpose') or 'general credit'))}</strong>. Estimated outstanding is <strong>{format_money(loan.get('outstanding_balance'))}</strong>.</div>",
                        unsafe_allow_html=True,
                    )

    def render_loan_table(rows: list[dict], title: str, empty_message: str) -> None:
        st.markdown(f"<div class='list-card'><div class='list-card__title'>{title}</div></div>", unsafe_allow_html=True)
        if not rows:
            st.info(empty_message)
            return
        table = [
            {
                "Loan ID": row["loan_id"],
                "Member": row["member_id"],
                "Requested": format_money(row.get("amount_requested")),
                "Outstanding": format_money(row.get("outstanding_balance")),
                "Interest": format_money(row.get("interest_accumulated")),
                "Approved Date": format_loan_date(row.get("approved_date")),
                "Reviewed By": row.get("approved_by") or "—",
            }
            for row in rows
        ]
        st.dataframe(
            pd.DataFrame(table),
            width="stretch",
            hide_index=True,
            column_config={
                "Loan ID": {"width": "small"},
                "Member": {"width": "medium"},
                "Requested": {"width": "medium"},
                "Outstanding": {"width": "medium"},
                "Interest": {"width": "medium"},
                "Approved Date": {"width": "small"},
                "Reviewed By": {"width": "small"},
            },
        )

    with status_tabs[1]:
        render_loan_table(
            approved_rows,
            "Approved Loan Portfolio",
            "No approved loans are available to display.",
        )

    with status_tabs[2]:
        render_loan_table(
            rejected_rows,
            "Rejected Loan Requests",
            "No rejected loan requests have been recorded.",
        )


def loans_view() -> None:
    inject_loans_theme()
    st.markdown(
        """
        <section class='loans-page__hero'>
          <h1 class='loans-page__hero-title'>Loans Management</h1>
          <p class='loans-page__hero-copy'>Manage consumer credit onboarding, leadership approvals, and portfolio review workflows from a unified executive dashboard.</p>
        </section>
        <div class='loans-page__divider'></div>
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
