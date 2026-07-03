import streamlit as st
import pandas as pd
from datetime import datetime
from typing import List, Tuple

from src.database.connection import execute_query
from src.utils.balances import get_effective_member_balance, get_effective_pool_balance


def fetch_portfolio_metrics() -> dict:
    total_paid = get_effective_pool_balance()
    rows = execute_query(
        "SELECT COUNT(DISTINCT member_id) AS member_count FROM subscriptions;",
        params=None,
        fetch=True,
    )
    member_count = int(rows[0].get("member_count") or 0) if rows else 0
    return {"total_paid": total_paid, "member_count": member_count}


def fetch_member_dropdown_options() -> List[Tuple[str, str]]:
    rows = execute_query(
        "SELECT member_id, full_name FROM members ORDER BY full_name;",
        params=None,
        fetch=True,
    )
    if not rows:
        return []
    return [(row["member_id"], row["full_name"]) for row in rows]


def fetch_subscription_ledger(limit: int = 20, expected_per_month: int = 20000, months_elapsed: int | None = None) -> pd.DataFrame:
    if months_elapsed is None:
        months_elapsed = datetime.today().month

    rows = execute_query(
        "SELECT m.member_id, m.full_name, COUNT(DISTINCT s.billing_month) AS paid_months "
        "FROM members m "
        "LEFT JOIN subscriptions s ON s.member_id = m.member_id "
        "AND EXTRACT(YEAR FROM s.billing_month) = EXTRACT(YEAR FROM CURRENT_DATE) "
        "GROUP BY m.member_id, m.full_name "
        "ORDER BY m.full_name "
        "LIMIT %s;",
        params=(limit,),
        fetch=True,
    )
    if not rows:
        return pd.DataFrame(
            [
                {
                    "Member Account": "No records available",
                    "Total Paid": "-",
                    "Paid Months": "-",
                    "Total Arrears": "-",
                    "Status": "-",
                }
            ]
        )

    ledger = []
    for row in rows:
        member_id = row.get("member_id")
        paid = get_effective_member_balance(member_id) if member_id else 0.0
        arrears = max(0.0, expected_per_month * months_elapsed - paid)
        status = (
            "Current" if arrears <= 0 else f"UGX {int(round(arrears)):,} overdue"
        )
        ledger.append(
            {
                "Member Account": f"{row.get('member_id')} — {row.get('full_name')}",
                "Total Paid": f"UGX {int(round(paid)):,}",
                "Paid Months": int(row.get("paid_months") or 0),
                "Total Arrears": f"UGX {int(round(arrears)):,}",
                "Status": status,
            }
        )
    return pd.DataFrame(ledger)


def savings_view() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        html, body, [class*="css"] {
          font-family: 'Inter', sans-serif;
        }

        .main-header-title {
          color: #0F172A;
          font-size: 2.2rem;
          font-weight: 800;
          margin-bottom: 10px;
        }

        .main-header-sub {
          color: #64748B;
          font-size: 1rem;
          line-height: 1.75;
          max-width: 760px;
          margin-bottom: 30px;
        }

        .workspace-panel {
          background: #FFFFFF;
          border: 1px solid #E2E8F0;
          border-radius: 16px;
          padding: 24px;
          box-shadow: 0 20px 40px rgba(15, 23, 42, 0.06);
          margin-bottom: 24px;
        }

        .workspace-panel h3 {
          margin: 0 0 14px 0;
          color: #0F172A;
          font-size: 1.15rem;
          font-weight: 700;
        }

        .workspace-panel .panel-subtitle {
          color: #64748B;
          font-size: 0.95rem;
          margin-bottom: 18px;
          line-height: 1.7;
        }

        .hero-banner {
          background: linear-gradient(135deg, #1E3A8A 0%, #0284C7 100%);
          border-radius: 20px;
          padding: 28px 24px;
          color: #ffffff;
          margin-bottom: 36px;
        }

        .hero-banner .hero-title {
          font-size: 1rem;
          font-weight: 600;
          color: rgba(255, 255, 255, 0.92);
          margin-bottom: 12px;
        }

        .hero-banner .hero-metric {
          background: rgba(56, 189, 248, 0.16);
          border: 1px solid rgba(56, 189, 248, 0.32);
          border-radius: 16px;
          padding: 18px 20px;
          min-width: 210px;
        }

        .hero-banner .hero-metric strong {
          display: block;
          font-size: 0.95rem;
          font-weight: 700;
          color: #EFF6FF;
          margin-bottom: 8px;
        }

        .hero-banner .hero-metric span {
          display: block;
          color: #ffffff;
          font-size: 1.1rem;
          font-weight: 700;
        }

        .alert-card {
          background: #F8FAFC;
          border: 1px solid #E2E8F0;
          border-radius: 18px;
          padding: 22px;
        }

        .alert-card h3 {
          margin-top: 0;
          margin-bottom: 18px;
          color: #0F172A;
          font-size: 1.05rem;
          font-weight: 700;
        }

        .alert-item {
          border-left: 4px solid;
          border-radius: 12px;
          padding: 16px 18px;
          margin-bottom: 16px;
          background: #ffffff;
        }

        .alert-item.blue {
          background: #EFF6FF;
          border-color: #1E3A8A;
        }

        .alert-item.green {
          background: #F0FDF4;
          border-color: #16A34A;
        }

        .alert-item span {
          display: block;
          color: #0F172A;
          font-size: 0.95rem;
          line-height: 1.6;
        }

        .form-grid {
          display: grid;
          grid-template-columns: repeat(2, minmax(0, 1fr));
          gap: 18px;
        }

        div[data-testid="stDataFrame"],
        div.stDataFrame {
          border: 1px solid #E2E8F0 !important;
          border-radius: 12px !important;
          overflow: hidden !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.markdown(
        """
        <div style="display:flex; flex-wrap:wrap; align-items:flex-start; justify-content:space-between; gap:24px; margin-bottom: 30px;">
          <div style="max-width:720px; background: #ffffff; border: 1px solid #e2e8f0; border-radius: 28px; padding: 28px 30px; box-shadow: 0 16px 40px rgba(15, 23, 42, 0.06);">
            <div style="font-size:2.75rem; font-weight:800; color:#0f172a; line-height:1.02; letter-spacing:-0.035em;">Subscriptions Ledger</div>
            <div style="margin-top:14px; color: #475569; font-size:1rem; line-height:1.85; max-width:680px;">
              See each member’s total subscription payments and current arrears in one clear view.
            </div>
          </div>
          <div style="background:#eff6ff; border:1px solid #dbeafe; border-radius:22px; padding:20px 24px; min-width:220px;">
            <div style="font-size:0.75rem; font-weight:700; color:#0f172a; text-transform:uppercase; letter-spacing:0.16em;">Dashboard focus</div>
            <div style="margin-top:10px; font-size:1rem; font-weight:700; color:#1d4ed8;">Member totals + arrears</div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    metrics = fetch_portfolio_metrics()
    total_paid = metrics["total_paid"]
    member_count = metrics["member_count"]
    cycle_percent = min(100, int((member_count / max(member_count, 8)) * 100)) if member_count else 0
    months_elapsed = datetime.today().month
    ledger_df = fetch_subscription_ledger(limit=20, months_elapsed=months_elapsed)

    st.markdown(
        f"""
        <div class="hero-banner">
          <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:20px; flex-wrap:wrap;">
            <div style="min-width:220px;">
              <div class="hero-title">Portfolio Overview Balance</div>
              <div style="font-size:2.4rem; font-weight:800; letter-spacing:0.01em;">UGX {total_paid:,.0f}</div>
            </div>
            <div style="display:flex; gap:16px; flex-wrap:wrap; width:min(100%, 520px);">
              <div class="hero-metric">
                <strong>Total Capital Pool</strong>
                <span>UGX {total_paid:,.0f}</span>
              </div>
              <div class="hero-metric">
                <strong>Cycle Collections</strong>
                <span>{cycle_percent}% Complete</span>
              </div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    left_col, right_col = st.columns([7, 3], gap="large")

    with left_col:
        st.markdown(
            """
            <div class="workspace-panel">
              <h3>📊 Member Subscription Summary</h3>
              <div class="panel-subtitle">A consolidated member-level view of total subscriptions paid and current arrears for the active cycle.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.dataframe(ledger_df, use_container_width=True, hide_index=True)

        st.markdown(
            """
            <div class="workspace-panel">
              <h3>🔎 Summary Notes</h3>
              <div class="panel-subtitle">This table aggregates per-member totals rather than showing month-by-month payments. Arrears are calculated against the active collection cycle.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with right_col:
        st.markdown(
            """
            <div class="alert-card">
              <h3>📅 Account Alerts & Deadlines</h3>
              <div class="alert-item blue">
                <span style="font-weight:700;">July Cycle Open</span>
                <span>Subscription submissions and reconciliation are available through month-end.</span>
              </div>
              <div class="alert-item green">
                <span style="font-weight:700;">Audit Compliance</span>
                <span>All recorded entries are subject to audit validation and governance review.</span>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
