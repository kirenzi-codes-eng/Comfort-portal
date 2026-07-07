import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
from html import escape
from typing import List, Tuple

from src.database.connection import execute_query
from src.utils.membership import get_membership_status_for_db
from src.utils.balances import get_effective_member_balance
from src.utils.timezone import today_in_uganda


def render_subscriptions_styles() -> None:
    st.markdown(
        """
        <style>
        .subscriptions-page-header {
          background: #1A365D;
          border-radius: 28px;
          padding: 28px 32px;
          color: #ffffff;
          margin-bottom: 28px;
          box-shadow: 0 24px 40px rgba(26, 54, 93, 0.14);
        }

        .subscriptions-page-header .heading {
          margin: 0;
          font-size: 2.8rem;
          font-weight: 800;
          letter-spacing: -0.04em;
          color: #ffffff;
        }

        .subscriptions-page-header .subtitle {
          margin-top: 14px;
          color: rgba(255, 255, 255, 0.88);
          font-size: 1rem;
          line-height: 1.75;
          max-width: 720px;
        }

        .section-path,
        .section-heading {
          color: #7F1D1D;
        }

        .section-path {
          font-size: 0.85rem;
          font-weight: 700;
          letter-spacing: 0.1em;
          text-transform: uppercase;
          margin-bottom: 8px;
        }

        .section-heading {
          font-size: 2rem;
          font-weight: 800;
          margin-bottom: 12px;
        }

        .status-pill.success {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 8px 16px;
          border-radius: 999px;
          background: #DCFCE7;
          color: #166534;
          font-weight: 700;
        }

        .status-pill.due {
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 8px 16px;
          border-radius: 999px;
          background: #FEE2E2;
          color: #991B1B;
          font-weight: 700;
        }

        .info-card.pink {
          background: linear-gradient(135deg, #EFF6FF 0%, #FFFFFF 100%);
          border: 1px solid #0EA5E9;
          box-shadow: 0 16px 40px rgba(14, 165, 233, 0.18);
          border-radius: 20px;
          padding: 24px;
          color: #0F172A;
          margin-bottom: 24px;
        }

        .summary-card {
          border-radius: 24px;
          padding: 28px;
          background: linear-gradient(135deg, #1A365D 0%, #7F1D1D 100%);
          color: #ffffff;
          margin-bottom: 24px;
        }

        .summary-card .metric-row {
          display: flex;
          flex-wrap: wrap;
          gap: 24px;
          justify-content: space-between;
        }

        .summary-card .metric-block {
          min-width: 220px;
        }

        .summary-card .metric-label {
          font-size: 0.78rem;
          letter-spacing: 0.14em;
          text-transform: uppercase;
          color: rgba(255,255,255,0.72);
          font-weight: 700;
        }

        .summary-card .metric-value {
          margin-top: 14px;
          font-size: 2.2rem;
          font-weight: 800;
          line-height: 1.05;
        }

        .summary-card .metric-note {
          margin-top: 10px;
          color: rgba(255,255,255,0.88);
          font-size: 0.95rem;
          line-height: 1.7;
        }

        .page-panel {
          background: #ffffff;
          border: 1px solid rgba(15, 23, 42, 0.08);
          border-radius: 24px;
          padding: 24px;
          margin-bottom: 24px;
          box-shadow: 0 18px 40px rgba(15, 23, 42, 0.06);
        }

        .form-panel {
          background: #ffffff;
          border: 1px solid rgba(15, 23, 42, 0.08);
          border-radius: 24px;
          padding: 22px;
          margin-bottom: 24px;
        }

        .form-panel.green {
          background: #ECFDF5;
          border-color: #16A34A;
        }

        .form-panel.green .form-panel-title {
          color: #166534;
        }

        .form-panel.brown {
          background: #F5F1EB;
          border-color: #6B4226;
        }

        .form-panel.brown .form-panel-title {
          color: #4B2E2B;
        }

        .form-panel .form-panel-title {
          display: block;
          margin-top: 0;
          margin-bottom: 16px;
          padding-top: 0;
        }

        .compact-table table {
          width: 100%;
          border-collapse: collapse;
        }

        .compact-table th,
        .compact-table td {
          padding: 14px 16px;
          text-align: left;
          border-bottom: 1px solid rgba(15, 23, 42, 0.08);
        }

        .compact-table th {
          font-weight: 700;
          color: #0f172a;
          background: #f8fafc;
        }

        .compact-table tr:last-child td {
          border-bottom: none;
        }

        .hero-block {
          border-radius: 28px;
          padding: 28px;
          background: #1A365D;
          color: #ffffff;
          margin-bottom: 24px;
          box-shadow: 0 24px 40px rgba(26, 54, 93, 0.14);
        }

        .hero-block .hero-title {
          font-size: 2.75rem;
          font-weight: 800;
          margin: 0 0 14px;
          letter-spacing: -0.04em;
          line-height: 1.05;
        }

        .hero-block .hero-copy {
          font-size: 1rem;
          line-height: 1.8;
          color: rgba(255,255,255,0.92);
          max-width: 780px;
        }

        .form-panel-title {
          font-size: 1.05rem;
          font-weight: 700;
          margin-bottom: 12px;
          color: #0f172a;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def check_and_update_member_status(member_id: str) -> None:
    member_rows = execute_query(
        "SELECT join_date FROM members WHERE member_id = %s LIMIT 1;",
        params=(member_id,),
        fetch=True,
    )
    join_date = member_rows[0].get("join_date") if member_rows else None

    metrics_rows = execute_query(
        "SELECT COALESCE(SUM(amount_paid),0) AS total_paid, COALESCE(SUM(CASE WHEN status = 'Pending' THEN amount_paid ELSE 0 END),0) AS pending_paid FROM subscriptions WHERE member_id = %s;",
        params=(member_id,),
        fetch=True,
    )
    metrics = metrics_rows[0] if metrics_rows else {}
    saving_balance = float(metrics.get("total_paid") or 0)
    arrears_balance = float(metrics.get("pending_paid") or 0)

    new_status = get_membership_status_for_db(join_date, saving_balance=saving_balance, arrears_balance=arrears_balance)
    try:
        execute_query(
            "UPDATE members SET status = %s WHERE member_id = %s;",
            params=(new_status, member_id),
            fetch=False,
        )
    except Exception:
        st.error("Failed to update member status.")


def normalize_status_value(value: object) -> str:
    if value is None:
        return "Pending"

    clean_value = str(value).strip().lower().replace("_", " ").replace("-", " ")
    mapping = {
        "paid": "Paid",
        "p": "Paid",
        "fully paid": "Paid",
        "full paid": "Paid",
        "complete": "Paid",
        "completed": "Paid",
        "approved": "Paid",
        "pending": "Pending",
        "due": "Pending",
        "open": "Pending",
        "incomplete": "Pending",
        "arrears": "Arrears",
        "ar": "Arrears",
        "a": "Arrears",
        "overdue": "Arrears",
        "missed": "Arrears",
        "late": "Arrears",
    }
    return mapping.get(clean_value, str(value).strip())


def render_status_badge(status_value: object, arrears_amount: float = 0.0) -> str:
    label = normalize_status_value(status_value)
    if label in {"Paid", "Fully Paid"}:
        return "<span class='badge badge-success'>Fully Paid</span>"
    if label in {"Arrears", "Overdue", "Missed", "Late"} or arrears_amount > 0:
        if arrears_amount > 0:
            return f"<span class='badge badge-danger'>Arrears UGX {int(round(arrears_amount)):,}</span>"
        return "<span class='badge badge-danger'>Arrears</span>"
    return "<span class='badge badge-warning'>Pending</span>"


def highlight_arrears_cells(row: pd.Series) -> list[tuple[int, str]]:
    status_text = str(row.get("Status", ""))
    if "Arrears" in status_text or "overdue" in status_text.lower():
        return [
            (0, "background-color: #fee2e2; color: #7f1d1d; font-weight: 700;"),
            (1, "background-color: #fee2e2; color: #7f1d1d; font-weight: 700;"),
            (2, "background-color: #fee2e2; color: #7f1d1d; font-weight: 700;"),
            (3, "background-color: #fee2e2; color: #7f1d1d; font-weight: 700;"),
        ]
    return []


def member_view(member_id: str) -> None:
    render_subscriptions_styles()
    st.markdown("<div class='section-path'>Subscriptions • Member Ledger</div>", unsafe_allow_html=True)
    today = today_in_uganda()
    current_year = today.year
    current_month = today.month
    monthly_expected = 20000

    rows = execute_query(
        "SELECT billing_month, amount_paid, status FROM subscriptions WHERE member_id = %s AND EXTRACT(YEAR FROM billing_month) = %s;",
        params=(member_id, current_year),
        fetch=True,
    )
    effective_balance = get_effective_member_balance(member_id)

    payments_by_month = {}
    status_by_month = {}
    if rows:
        for r in rows:
            bm = r.get("billing_month")
            if isinstance(bm, (datetime, date)):
                key = bm.month
            else:
                try:
                    parsed = datetime.fromisoformat(str(bm))
                    key = parsed.month
                except Exception:
                    continue
            payments_by_month[key] = payments_by_month.get(key, 0.0) + float(r.get("amount_paid") or 0.0)
            status_by_month[key] = r.get("status")

    ledger = []
    total_contributed = 0.0
    total_arrears = 0.0
    for month_num in range(1, current_month + 1):
        month_label = datetime(current_year, month_num, 1).strftime("%b")
        contributed = payments_by_month.get(month_num, 0.0)
        expected = float(monthly_expected)
        arrears = max(0.0, expected - contributed)
        total_contributed += contributed
        total_arrears += arrears
        if arrears <= 0:
            status = render_status_badge("Paid", 0.0)
        else:
            status = render_status_badge(status_by_month.get(month_num, "Arrears"), arrears)
        ledger.append(
            {
                "Month": month_label,
                "Expected": f"UGX {int(round(expected)):,}",
                "Contributed": f"UGX {int(round(contributed)):,}",
                "Status": status,
            }
        )

    st.markdown(
        f"""
        <div style="display:flex; gap:12px; flex-wrap:wrap; margin-bottom:16px;">
            <div style="flex:1; min-width:220px; background:#ffffff; border:1px solid #E9ECEF; border-radius:16px; padding:12px 14px; box-shadow:0 2px 8px rgba(0,0,0,0.05);">
                <div style="font-size:0.72rem; text-transform:uppercase; letter-spacing:0.08em; color:#6C757D; font-weight:600;">My Subscriptions</div>
                <div style="font-size:1.35rem; font-weight:700; color:#0066FF; margin-top:4px;">UGX {int(round(effective_balance)):,}</div>
            </div>
            <div style="flex:1; min-width:220px; background:#ffffff; border:1px solid #E9ECEF; border-radius:16px; padding:12px 14px; box-shadow:0 2px 8px rgba(0,0,0,0.05);">
                <div style="font-size:0.72rem; text-transform:uppercase; letter-spacing:0.08em; color:#6C757D; font-weight:600;">Arrears</div>
                <div style="font-size:1.35rem; font-weight:700; color:#FF3B30; margin-top:4px;">UGX {int(round(total_arrears)):,}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if rows:
        history_rows = []
        for r in rows:
            bm = r.get("billing_month")
            if isinstance(bm, (datetime, date)):
                billing_month_label = bm.strftime("%b %Y")
            else:
                billing_month_label = str(bm or "Unknown")

            history_rows.append(
                {
                    "Billing Month": billing_month_label,
                    "Amount Paid": f"UGX {int(round(float(r.get('amount_paid') or 0))):,}",
                    "Status": normalize_status_value(r.get("status")),
                }
            )

        st.subheader("Payment History")
        st.dataframe(pd.DataFrame(history_rows), width="stretch")

    st.markdown("---")
    st.subheader("Monthly Ledger")
    df = pd.DataFrame(ledger)
    df["Status"] = [
        value if isinstance(value, str) and value.strip().startswith("<span") else render_status_badge(value)
        for value in df["Status"]
    ]

    styled_html = df.to_html(index=False, escape=False, classes='compact-table', border=0)
    if not df.empty:
        rows_html = []
        for _, row in df.iterrows():
            cells = []
            highlight_cells = highlight_arrears_cells(row)
            for idx, value in enumerate(row.tolist()):
                style = next((style for cell_idx, style in highlight_cells if cell_idx == idx), "")
                if style:
                    cells.append(f"<td style='{style}'>{value}</td>")
                else:
                    cells.append(f"<td>{value}</td>")
            rows_html.append(f"<tr>{''.join(cells)}</tr>")
        styled_html = f"<table class='dataframe compact-table'>{''.join(rows_html)}</table>"

    st.markdown(
        f"<div class='card' style='padding: 0.5rem; overflow-x: auto;'>{styled_html}</div>",
        unsafe_allow_html=True,
    )


def fetch_all_members() -> List[Tuple[str, str]]:
    """Fetch all members with 5-minute cache TTL."""
    return fetch_all_members_cached()


@st.cache_data(ttl=300)
def fetch_all_members_cached() -> List[Tuple[str, str]]:
    rows = execute_query("SELECT member_id, full_name FROM members ORDER BY full_name;", params=None, fetch=True)
    if not rows:
        return []
    return [(r["member_id"], r["full_name"]) for r in rows]


def treasurer_view(user_role: str):
    render_subscriptions_styles()
    title = "Treasurer Portal" if user_role == "Treasurer" else "Executive Subscription Review"
    subtitle = (
        "Record member subscription payments and apply loan repayments with clarity and accuracy."
        if user_role == "Treasurer"
        else "Review posted member subscription payments and contribution history without editing entries."
    )

    st.markdown(
        f"""
        <div class='hero-block'>
          <div class='hero-title'>{title}</div>
          <div class='hero-copy'>{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        """
        <div class='info-card pink'>
          Use this workspace to review subscription receipts, member activity, and posted payments.
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.spinner("Loading data..."):
        members = fetch_all_members()
        recent = fetch_recent_subscriptions(30)

    if not members:
        st.info("No members found.")
        return

    member_options = {f"{m[1]} ({m[0]})": m[0] for m in members}

    if user_role == "Treasurer":
        col1, col2 = st.columns(2, gap="large")
        with col1:
            with st.container():
                st.markdown("<div class='form-panel green'>", unsafe_allow_html=True)
                st.markdown("<div class='form-panel-title'>Post Subscription Payment</div>", unsafe_allow_html=True)
                with st.form("post_payment_form"):
                    selected = st.selectbox("Member", options=list(member_options.keys()))
                    billing_month = st.date_input("Billing Month", value=today_in_uganda())
                    amount = st.number_input("Amount Paid (UGX)", min_value=0.0, value=20000.0, step=100.0)
                    submit_payment = st.form_submit_button("Post Payment")

                if submit_payment:
                    member_id = member_options[selected]
                    bm = billing_month.replace(day=1)
                    try:
                        execute_query(
                            "INSERT INTO subscriptions (member_id, billing_month, amount_paid, status) VALUES (%s, %s, %s, %s);",
                            params=(member_id, bm, amount, "Paid"),
                            fetch=False,
                        )
                        st.toast("Payment recorded.", icon="✅")
                        check_and_update_member_status(member_id)
                    except Exception as e:
                        st.error(f"Failed to record payment: {e}")
                st.markdown("</div>", unsafe_allow_html=True)

        with col2:
            with st.container():
                st.markdown("<div class='form-panel brown'>", unsafe_allow_html=True)
                st.markdown("<div class='form-panel-title'>Loan Repayment</div>", unsafe_allow_html=True)
                with st.form("loan_repayment_form"):
                    loan_member = st.selectbox("Member for Loan Repayment", options=list(member_options.keys()), key="loan_member")
                    repay_amount = st.number_input("Repayment Amount (UGX)", min_value=0.0, value=0.0, step=100.0)
                    submit_repay = st.form_submit_button("Apply Repayment")

                if submit_repay:
                    member_id = member_options[loan_member]
                    if repay_amount <= 0:
                        st.toast("Enter a positive repayment amount.", icon="⚠️")
                    else:
                        try:
                            rows = execute_query(
                                "UPDATE loans SET outstanding_balance = GREATEST(outstanding_balance - %s, 0) "
                                "WHERE member_id = %s AND status = 'Approved' RETURNING loan_id, outstanding_balance;",
                                params=(repay_amount, member_id),
                                fetch=True,
                            )
                            if rows:
                                st.toast("Repayment applied to active loan.", icon="✅")
                            else:
                                st.info("No active approved loan found for this member.")
                        except Exception as e:
                            st.error(f"Failed to apply repayment: {e}")
                st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("---")
    else:
        st.markdown(
            """
            <div class='info-card'>
              Chairperson can review all posted subscription payments and member-ledger details here.
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.markdown("---")

    st.markdown("### Recently Posted Subscription Payments")
    if recent:
        recent_df = pd.DataFrame(
            [
                {
                    "Member": row.get("full_name") or row.get("member_id"),
                    "Member ID": row.get("member_id"),
                    "Billing Month": (
                        (row.get("billing_month") or datetime.now()).strftime("%b %Y")
                        if isinstance(row.get("billing_month"), (datetime, date))
                        else str(row.get("billing_month") or "Unknown")
                    ),
                    "Amount Paid": f"UGX {int(round(row.get('amount_paid') or 0)):,}",
                    "Status": normalize_status_value(row.get("status")),
                }
                for row in recent
            ]
        )
        st.dataframe(recent_df, width="stretch")
    else:
        st.info("No posted subscription payments in the last 30 days.")

    st.markdown("---")
    selected = st.selectbox("Select member to inspect", options=list(member_options.keys()))
    selected_member_id = member_options[selected]

    st.markdown(f"### Detailed member subscription ledger for {escape(selected)}")

    # If Secretary, allow exporting the selected member's payment history as CSV
    if user_role == "Secretary":
        try:
            history_rows = []
            rows = execute_query(
                "SELECT billing_month, amount_paid, status FROM subscriptions WHERE member_id = %s ORDER BY billing_month;",
                params=(selected_member_id,),
                fetch=True,
            ) or []

            for r in rows:
                bm = r.get("billing_month")
                if bm is not None and hasattr(bm, "strftime"):
                    billing_month_label = bm.strftime("%Y-%m-%d")
                else:
                    billing_month_label = str(bm or "")
                history_rows.append({
                    "billing_month": billing_month_label,
                    "amount_paid": float(r.get("amount_paid") or 0.0),
                    "status": str(r.get("status") or ""),
                })

            if history_rows:
                df_export = pd.DataFrame(history_rows)
                csv_bytes = df_export.to_csv(index=False).encode("utf-8")
                st.download_button(
                    label="Download member ledger CSV",
                    data=csv_bytes,
                    file_name=f"{selected_member_id}_ledger.csv",
                    mime="text/csv",
                )
            else:
                st.info("No subscription history available for export.")
        except Exception as e:
            st.error(f"Failed to prepare ledger export: {e}")

    member_view(selected_member_id)


def fetch_recent_subscriptions(days: int = 7) -> list[dict]:
    """Fetch recent subscriptions with 30-second cache TTL."""
    return fetch_recent_subscriptions_cached(days)


@st.cache_data(ttl=30)
def fetch_recent_subscriptions_cached(days: int = 7) -> list[dict]:
    cutoff_date = today_in_uganda() - timedelta(days=days)
    rows = execute_query(
        "SELECT s.member_id, m.full_name, s.billing_month, s.amount_paid, s.status "
        "FROM subscriptions s "
        "JOIN members m ON s.member_id = m.member_id "
        "WHERE s.billing_month >= %s "
        "ORDER BY s.billing_month DESC;",
        params=(cutoff_date,),
        fetch=True,
    )
    return rows or []


def fetch_subscription_summary(year: int) -> dict[str, float]:
    """Fetch subscription summary with 60-second cache TTL."""
    return fetch_subscription_summary_cached(year)


@st.cache_data(ttl=60)
def fetch_subscription_summary_cached(year: int) -> dict[str, float]:
    rows = execute_query(
        "SELECT COUNT(DISTINCT member_id) AS members_with_payments, COALESCE(SUM(amount_paid), 0) AS total_paid "
        "FROM subscriptions WHERE EXTRACT(YEAR FROM billing_month) = %s;",
        params=(year,),
        fetch=True,
    )
    if not rows:
        return {"members_with_payments": 0.0, "total_paid": 0.0}
    return {
        "members_with_payments": float(rows[0].get("members_with_payments", 0) or 0),
        "total_paid": float(rows[0].get("total_paid", 0) or 0),
    }


def chairperson_monitor_view():
    render_subscriptions_styles()
    st.markdown(
        """
        <div class='hero-block'>
          <div class='hero-title'>Chairperson Monitor</div>
          <div class='hero-copy'>View yearly subscription progress and recent payment activity for transparent oversight.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    user_role = st.session_state.get("user_role")
    if user_role != "Chairperson":
        st.info("Only Chairperson can access the subscription monitor.")
        return

    today = today_in_uganda()
    with st.spinner("Loading data..."):
        summary = fetch_subscription_summary(today.year)
        recent = fetch_recent_subscriptions(7)

    st.markdown("<div class='page-panel'>", unsafe_allow_html=True)
    col1, col2 = st.columns(2, gap="large")
    col1.metric("Members with payments this year", int(summary["members_with_payments"]))
    col2.metric("Total paid this year", f"UGX {int(round(summary['total_paid'])):,}")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='page-panel'>", unsafe_allow_html=True)
    st.markdown("<div class='form-panel-title'>Recent subscription activity</div>", unsafe_allow_html=True)
    if recent:
        for row in recent[:10]:
            billing_month = row.get("billing_month")
            if billing_month is not None and hasattr(billing_month, "strftime"):
                slot = billing_month.strftime("%b %Y")
            else:
                slot = str(billing_month or "Unknown")
            st.markdown(
                f"- **{row.get('full_name')}** ({row.get('member_id')}) — UGX {int(round(row.get('amount_paid') or 0)):,} for {slot} — {row.get('status')}"
            )
    else:
        st.info("No subscription activity recorded in the last 7 days.")
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("---")
    members = fetch_all_members()
    if not members:
        st.info("No members found.")
        return

    member_options = {f"{m[1]} ({m[0]})": m[0] for m in members}
    selected = st.selectbox("Select member to inspect", options=list(member_options.keys()))
    selected_member_id = member_options[selected]

    st.markdown(f"### Detailed member subscription ledger for {escape(selected)}")
    member_view(selected_member_id)


def subscriptions_view():
    render_subscriptions_styles()
    st.markdown(
        """
        <div class='hero-block'>
          <div class='hero-title'>Subscriptions & Savings</div>
          <div class='hero-copy'>A polished dashboard for member contributions, subscription records, and arrears review.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    user_role = st.session_state.get("user_role")
    user_id = st.session_state.get("user_id")

    # Run membership status engine for logged-in user
    if user_id:
        try:
            check_and_update_member_status(user_id)
        except Exception:
            pass

    if user_role in ("Treasurer", "Secretary"):
        # Treasurer retains posting capabilities; Secretary may review other members' ledgers without posting.
        treasurer_view(user_role)
        return

    if user_role == "Member":
        st.info("Global financial updates are restricted to executive roles.")

    # Default: member view
    if not user_id:
        st.info("Log in to view subscriptions.")
        return

    member_view(user_id)


if __name__ == "__main__":
    subscriptions_view()
