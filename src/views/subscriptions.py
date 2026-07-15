import os
import re
import io
import base64
import streamlit as st
import pandas as pd
from datetime import datetime, date, timedelta
from html import escape
from pathlib import Path
from typing import List, Tuple

import cloudinary
import cloudinary.uploader

from app import coerce_date_input_value
from src.database.connection import cached_read_query, execute_query
from src.utils.membership import get_membership_status_for_db
from src.utils.balances import get_effective_member_balance
from src.utils.timezone import today_in_uganda


ALLOWED_PROOF_EXTENSIONS = {"jpg", "jpeg", "png", "pdf"}
MAX_PROOF_SIZE_BYTES = 5 * 1024 * 1024
PROOF_STATUS_PENDING = "Pending Verification"
PROOF_STATUS_VERIFIED = "Verified"
PROOF_STATUS_REJECTED = "Rejected"
PROOF_STATUS_CLARIFICATION = "Clarification Requested"
MAX_SUBSCRIPTION_AMOUNT = 20000.0


def get_subscription_proof_access_role(user_role: str | None) -> str:
    """Return the access mode for subscription proof features based on role."""
    normalized_role = (user_role or "").strip()
    if normalized_role == "Treasurer":
        return "treasurer"
    if normalized_role == "Chairperson":
        return "chairperson"
    if normalized_role == "Member":
        return "member"
    return "restricted"


def should_show_member_proof_section(user_role: str | None) -> bool:
    """Show the member payment-proof submission section only for members."""
    return get_subscription_proof_access_role(user_role) == "member"


def validate_subscription_proof_upload(uploaded_file, max_bytes: int = MAX_PROOF_SIZE_BYTES) -> tuple[bool, str]:
    """Validate uploaded proof files before Cloudinary upload."""
    if uploaded_file is None:
        return False, "Please choose a payment proof file to upload."

    file_name = getattr(uploaded_file, "name", "") or ""
    extension = os.path.splitext(file_name)[1].lower().lstrip(".")
    if extension not in ALLOWED_PROOF_EXTENSIONS:
        return False, "Unsupported file type. Please upload JPG, JPEG, PNG, or PDF."

    file_size = 0
    try:
        file_size = getattr(uploaded_file, "size", 0) or 0
    except Exception:
        file_size = 0

    if not file_size:
        try:
            file_size = len(uploaded_file.getbuffer())
        except Exception:
            file_size = 0

    if file_size > max_bytes:
        return False, f"File is larger than the allowed limit of {max_bytes // (1024 * 1024)} MB."

    if file_size <= 0:
        return False, "The uploaded file appears to be empty."

    return True, "Validation passed."


def _ensure_subscription_proof_table() -> None:
    """Create the payment proof table if it does not exist."""
    try:
        execute_query(
            """
            CREATE TABLE IF NOT EXISTS subscription_payment_proofs (
                proof_id SERIAL PRIMARY KEY,
                member_id TEXT NOT NULL,
                member_name TEXT NOT NULL,
                subscription_month INTEGER NOT NULL,
                subscription_year INTEGER NOT NULL,
                amount_paid NUMERIC(12, 2) NOT NULL,
                payment_method TEXT NOT NULL,
                transaction_reference TEXT,
                comment TEXT,
                cloudinary_file_url TEXT NOT NULL,
                cloudinary_public_id TEXT NOT NULL,
                upload_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                verification_status TEXT NOT NULL DEFAULT 'Pending Verification',
                verified_by TEXT,
                verification_date TIMESTAMP,
                verification_comment TEXT
            );
            """,
            params=None,
            fetch=False,
        )
    except Exception:
        pass


def _load_cloudinary_config() -> bool:
    """Reuse the app's Cloudinary configuration if available."""
    try:
        cloud_name = None
        api_key = None
        api_secret = None

        try:
            cloud_name = st.secrets.get("CLOUDINARY_CLOUD_NAME")
            api_key = st.secrets.get("CLOUDINARY_API_KEY")
            api_secret = st.secrets.get("CLOUDINARY_API_SECRET")
        except Exception:
            pass

        cloud_name = cloud_name or os.environ.get("CLOUDINARY_CLOUD_NAME")
        api_key = api_key or os.environ.get("CLOUDINARY_API_KEY")
        api_secret = api_secret or os.environ.get("CLOUDINARY_API_SECRET")

        if not cloud_name or not api_key or not api_secret:
            return False

        cloudinary.config(cloud_name=cloud_name, api_key=api_key, api_secret=api_secret)
        return True
    except Exception:
        return False


def upload_subscription_proof_to_cloudinary(uploaded_file, member_id: str) -> tuple[bool, str | None, str | None]:
    """Upload a payment proof file to Cloudinary and return the URL and public ID."""
    if uploaded_file is None:
        return False, None, None

    if not _load_cloudinary_config():
        return False, None, None

    try:
        safe_name = re.sub(r"[^0-9A-Za-z._-]", "_", (getattr(uploaded_file, "name", "") or "receipt") or "receipt")
        upload_result = cloudinary.uploader.upload(
            uploaded_file,
            resource_type="auto",
            public_id=f"comfort_portal/subscriptions/{member_id}/{safe_name}",
            overwrite=False,
            folder=f"comfort_portal/subscriptions/{member_id}",
        )
        secure_url = upload_result.get("secure_url")
        public_id = upload_result.get("public_id")
        if secure_url and public_id:
            return True, secure_url, public_id
        return False, None, None
    except Exception:
        return False, None, None


def save_subscription_proof_record(
    member_id: str,
    member_name: str,
    subscription_month: int,
    subscription_year: int,
    amount_paid: float,
    payment_method: str,
    transaction_reference: str | None,
    comment: str | None,
    cloudinary_file_url: str,
    cloudinary_public_id: str,
    verification_status: str = PROOF_STATUS_PENDING,
) -> dict | None:
    """Persist only proof metadata in PostgreSQL."""
    _ensure_subscription_proof_table()
    try:
        result = execute_query(
            """
            INSERT INTO subscription_payment_proofs (
                member_id,
                member_name,
                subscription_month,
                subscription_year,
                amount_paid,
                payment_method,
                transaction_reference,
                comment,
                cloudinary_file_url,
                cloudinary_public_id,
                verification_status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING proof_id, member_id, member_name, subscription_month, subscription_year, amount_paid, payment_method, transaction_reference, comment, cloudinary_file_url, cloudinary_public_id, upload_timestamp, verification_status;
            """,
            params=(
                member_id,
                member_name,
                subscription_month,
                subscription_year,
                amount_paid,
                payment_method,
                transaction_reference,
                comment,
                cloudinary_file_url,
                cloudinary_public_id,
                verification_status,
            ),
            fetch=True,
        )
        return result[0] if result else None
    except Exception:
        return None


def fetch_member_subscription_proofs(member_id: str) -> list[dict]:
    """Fetch proofs belonging to a specific member."""
    _ensure_subscription_proof_table()
    rows = execute_query(
        """
        SELECT proof_id, member_id, member_name, subscription_month, subscription_year, amount_paid, payment_method,
               transaction_reference, comment, cloudinary_file_url, cloudinary_public_id, upload_timestamp, verification_status,
               verified_by, verification_date, verification_comment
        FROM subscription_payment_proofs
        WHERE member_id = %s
        ORDER BY upload_timestamp DESC;
        """,
        params=(member_id,),
        fetch=True,
    )
    return rows or []


def fetch_all_subscription_proofs() -> list[dict]:
    """Fetch all proof records for treasurer and chairperson views."""
    _ensure_subscription_proof_table()
    rows = execute_query(
        """
        SELECT proof_id, member_id, member_name, subscription_month, subscription_year, amount_paid, payment_method,
               transaction_reference, comment, cloudinary_file_url, cloudinary_public_id, upload_timestamp, verification_status,
               verified_by, verification_date, verification_comment
        FROM subscription_payment_proofs
        ORDER BY upload_timestamp DESC;
        """,
        params=None,
        fetch=True,
    )
    return rows or []


def has_existing_subscription_proof(member_id: str, subscription_month: int, subscription_year: int) -> bool:
    """Prevent duplicate submissions for the same member, month and year unless previously rejected."""
    _ensure_subscription_proof_table()
    rows = execute_query(
        """
        SELECT proof_id FROM subscription_payment_proofs
        WHERE member_id = %s AND subscription_month = %s AND subscription_year = %s
          AND verification_status <> %s;
        """,
        params=(member_id, subscription_month, subscription_year, PROOF_STATUS_REJECTED),
        fetch=True,
    )
    return bool(rows)


def get_member_monthly_subscription_total(member_id: str, subscription_month: int, subscription_year: int) -> float:
    """Return the current total amount paid or pending for the member in a given month/year."""
    _ensure_subscription_proof_table()
    billing_month = date(subscription_year, subscription_month, 1)

    subscription_rows = execute_query(
        """
        SELECT COALESCE(SUM(amount_paid), 0) AS total_paid
        FROM subscriptions
        WHERE member_id = %s AND billing_month = %s;
        """,
        params=(member_id, billing_month),
        fetch=True,
    ) or []
    existing_total = float(subscription_rows[0].get("total_paid", 0) if subscription_rows else 0)

    proof_rows = execute_query(
        """
        SELECT COALESCE(SUM(amount_paid), 0) AS total_pending
        FROM subscription_payment_proofs
        WHERE member_id = %s AND subscription_month = %s AND subscription_year = %s
          AND verification_status <> %s;
        """,
        params=(member_id, subscription_month, subscription_year, PROOF_STATUS_REJECTED),
        fetch=True,
    ) or []
    pending_total = float(proof_rows[0].get("total_pending", 0) if proof_rows else 0)

    return existing_total + pending_total


def update_subscription_proof_verification(proof_id: int | str, verifier: str, new_status: str, verification_comment: str | None = None) -> bool:
    """Update verification outcome and audit metadata."""
    _ensure_subscription_proof_table()
    try:
        execute_query(
            """
            UPDATE subscription_payment_proofs
            SET verification_status = %s,
                verified_by = %s,
                verification_date = %s,
                verification_comment = %s
            WHERE proof_id = %s;
            """,
            params=(new_status, verifier, datetime.utcnow(), verification_comment, proof_id),
            fetch=False,
        )
        return True
    except Exception:
        return False


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

        .payment-card {
          background: linear-gradient(135deg, #f0fdf4 0%, #ffffff 100%);
          border: 1px solid #86efac;
          border-radius: 22px;
          padding: 24px;
          margin: 18px 0 24px;
          box-shadow: 0 16px 40px rgba(22, 163, 74, 0.12);
        }

        .payment-card .payment-title {
          margin: 0 0 8px;
          font-size: 1.2rem;
          font-weight: 800;
          color: #166534;
        }

        .payment-card .payment-copy {
          margin: 0 0 16px;
          color: #365a3a;
          line-height: 1.7;
          font-size: 0.95rem;
        }

        .payment-card .payment-button {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          gap: 8px;
          padding: 12px 18px;
          border-radius: 999px;
          background: linear-gradient(135deg, #16a34a 0%, #22c55e 100%);
          color: #ffffff;
          font-weight: 700;
          text-decoration: none;
          box-shadow: 0 10px 24px rgba(22, 163, 74, 0.22);
          transition: transform 180ms ease, box-shadow 180ms ease, filter 180ms ease;
        }

        .payment-card .payment-button:hover {
          transform: translateY(-2px) scale(1.01);
          box-shadow: 0 12px 28px rgba(22, 163, 74, 0.26);
          filter: brightness(1.03);
          color: #ffffff;
          text-decoration: none;
        }

        .payment-card .payment-icon {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          width: 34px;
          height: 34px;
          border-radius: 50%;
          background: rgba(255, 255, 255, 0.18);
          font-size: 1rem;
          flex-shrink: 0;
        }

        .payment-card .payment-image {
          display: block;
          width: 100%;
          max-width: 180px;
          height: auto;
          margin: 0 0 16px;
          border-radius: 14px;
          border: 1px solid rgba(22, 163, 74, 0.12);
        }

        .payment-card .payment-note {
          margin-top: 14px;
          padding: 12px 14px;
          border-radius: 14px;
          background: #f8fafc;
          border: 1px solid rgba(15, 23, 42, 0.06);
          color: #334155;
          font-size: 0.9rem;
          line-height: 1.6;
        }

        @media (max-width: 768px) {
          .payment-card {
            padding: 18px;
          }

          .payment-card .payment-button {
            width: 100%;
          }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_pay_subscription_card_html() -> str:
    """Return the HTML for the mobile-friendly payment shortcut card."""
    ussd_code = "*165*3*09390032%23"
    image_markup = ""
    asset_path = Path(__file__).resolve().parents[2] / "mtn.png"
    if asset_path.exists():
        try:
            encoded = base64.b64encode(asset_path.read_bytes()).decode("ascii")
            image_markup = f"<img class='payment-image' src='data:image/png;base64,{encoded}' alt='MTN Mobile Money payment illustration' />"
        except Exception:
            image_markup = ""

    return f"""
    <div class='payment-card'>
      <div class='payment-title'>Pay Monthly Subscription</div>
      <p class='payment-copy'>Members can pay their monthly subscription quickly using MTN Mobile Money. Tap below to open your phone dialer with the payment code already entered.</p>
      {image_markup}
      <a class='payment-button' href='tel:{ussd_code}' aria-label='Pay subscription using USSD'>
        <span>💳 Pay Subscription</span>
      </a>
      <div class='payment-note'>After tapping <strong>Pay Subscription</strong>, your phone's dialer will open with the payment code already entered. Simply press the Call button and follow the Mobile Money prompts to complete your payment.</div>
    </div>
    """


def render_payment_proof_form(member_id: str, member_name: str) -> None:
    """Render the member-facing payment proof submission card."""
    st.markdown("### Payment Proof Submission")
    st.markdown(
        """
        <div class='page-panel'>
          <div class='form-panel-title'>Upload your proof of payment</div>
          <div style='color:#475569; line-height:1.7;'>Share your receipt or screenshot securely. Your proof will be stored safely in Cloudinary and only the metadata will be kept in the portal database.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("subscription_proof_form"):
        uploaded_file = st.file_uploader(
            "Upload Payment Proof",
            type=["jpg", "jpeg", "png", "pdf"],
            help="Accepted files: JPG, JPEG, PNG, PDF",
        )
        col_a, col_b = st.columns(2)
        with col_a:
            subscription_month = st.selectbox("Subscription Month", options=list(range(1, 13)), index=today_in_uganda().month - 1)
            amount_paid = st.number_input(
                "Amount Paid (max UGX 20,000)",
                min_value=0.0,
                max_value=MAX_SUBSCRIPTION_AMOUNT,
                value=MAX_SUBSCRIPTION_AMOUNT,
                step=100.0,
                help="Enter a subscription payment amount up to UGX 20,000.",
            )
        with col_b:
            subscription_year = st.selectbox("Subscription Year", options=list(range(today_in_uganda().year - 1, today_in_uganda().year + 2)), index=1)
            payment_method = st.selectbox(
                "Payment Method",
                options=["MTN Mobile Money", "Airtel Money", "Bank", "Cash", "Other"],
            )
        transaction_reference = st.text_input("Transaction/Reference Number (optional)")
        comment = st.text_area("Comment (optional)")

        if uploaded_file is not None:
            st.caption("Uploaded preview")
            if getattr(uploaded_file, "type", "").startswith("image/"):
                st.image(uploaded_file, use_container_width=True)
            else:
                st.download_button(
                    label="Preview PDF receipt",
                    data=uploaded_file.getvalue(),
                    file_name=uploaded_file.name,
                    mime="application/pdf",
                )

        submitted = st.form_submit_button("Submit Proof", use_container_width=True)

    if submitted:
        if amount_paid > MAX_SUBSCRIPTION_AMOUNT:
            st.error(f"The maximum allowed subscription payment is UGX {int(MAX_SUBSCRIPTION_AMOUNT):,}.")
            return

        monthly_total = get_member_monthly_subscription_total(member_id, subscription_month, subscription_year)
        if monthly_total + amount_paid > MAX_SUBSCRIPTION_AMOUNT:
            allowed_amount = max(0.0, MAX_SUBSCRIPTION_AMOUNT - monthly_total)
            st.error(
                f"This member already has UGX {int(monthly_total):,} recorded or pending for "
                f"{date(subscription_year, subscription_month, 1).strftime('%B %Y')}. "
                f"Please submit up to UGX {int(allowed_amount):,} for this month."
            )
            return

        is_valid, message = validate_subscription_proof_upload(uploaded_file)
        if not is_valid:
            st.error(message)
            return

        if has_existing_subscription_proof(member_id, subscription_month, subscription_year):
            st.warning("A proof submission for this month and year already exists and is awaiting action. Please wait for verification or contact the Treasurer.")
            return

        with st.spinner("Uploading your payment proof securely..."):
            success, url, public_id = upload_subscription_proof_to_cloudinary(uploaded_file, member_id)
        if not success or not url or not public_id:
            st.error("We could not upload your payment proof right now. Please try again later or contact support.")
            return

        with st.spinner("Saving your payment proof details..."):
            saved = save_subscription_proof_record(
                member_id=member_id,
                member_name=member_name,
                subscription_month=subscription_month,
                subscription_year=subscription_year,
                amount_paid=float(amount_paid),
                payment_method=payment_method,
                transaction_reference=transaction_reference.strip() or None,
                comment=comment.strip() or None,
                cloudinary_file_url=url,
                cloudinary_public_id=public_id,
            )

        if saved is None:
            st.error("Your proof could not be saved to the portal database. Please try again.")
            return

        st.success("Your payment proof has been submitted successfully and is awaiting verification by the Treasurer.")


def render_member_payment_history(member_id: str, member_name: str) -> None:
    """Render a member's own payment-proof history and current status."""
    st.markdown("### Your Submitted Proofs")
    proofs = fetch_member_subscription_proofs(member_id)
    if not proofs:
        st.info("You have not submitted any payment proofs yet.")
        return

    for proof in proofs:
        with st.container():
            st.markdown(
                f"""
                <div class='page-panel'>
                  <div style='display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap;'>
                    <div>
                      <div style='font-weight:700; color:#0f172a;'>{escape(member_name)} • {proof.get('subscription_month')}/{proof.get('subscription_year')}</div>
                      <div style='color:#64748b; font-size:0.9rem; margin-top:4px;'>Uploaded {proof.get('upload_timestamp')}</div>
                    </div>
                    <div style='padding:6px 10px; border-radius:999px; background:#ecfdf5; color:#166534; font-weight:700;'>Status: {escape(str(proof.get('verification_status') or 'Pending Verification'))}</div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            proof_url = str(proof.get("cloudinary_file_url") or "").strip()
            if proof_url:
                if proof_url.lower().endswith(".pdf"):
                    st.link_button("View PDF", proof_url)
                else:
                    st.image(proof_url, use_container_width=True)
            st.caption(f"Amount: UGX {int(float(proof.get('amount_paid') or 0)):,} • Method: {proof.get('payment_method')}")
            if proof.get("transaction_reference"):
                st.caption(f"Reference: {proof.get('transaction_reference')}")
            if proof.get("comment"):
                st.caption(f"Comment: {proof.get('comment')}")


def render_treasurer_proof_management() -> None:
    """Render treasurer-only proof verification controls."""
    st.markdown("### Subscription Verification")
    proofs = fetch_all_subscription_proofs()
    if not proofs:
        st.info("No payment proofs have been submitted yet.")
        return

    search_term = st.text_input("Search by member or reference")
    filtered = []
    if search_term:
        needle = search_term.lower()
        filtered = [proof for proof in proofs if needle in str(proof.get("member_name") or "").lower() or needle in str(proof.get("transaction_reference") or "").lower()]
    else:
        filtered = proofs

    for proof in filtered:
        with st.container():
            st.markdown(
                f"""
                <div class='page-panel'>
                  <div style='display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap;'>
                    <div>
                      <div style='font-weight:700; color:#0f172a;'>{escape(str(proof.get('member_name') or 'Unknown'))} • {proof.get('subscription_month')}/{proof.get('subscription_year')}</div>
                      <div style='color:#64748b; font-size:0.9rem; margin-top:4px;'>Amount: UGX {int(float(proof.get('amount_paid') or 0)):,} • Method: {escape(str(proof.get('payment_method') or '-'))}</div>
                    </div>
                    <div style='padding:6px 10px; border-radius:999px; background:#eff6ff; color:#1d4ed8; font-weight:700;'>{escape(str(proof.get('verification_status') or PROOF_STATUS_PENDING))}</div>
                  </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            proof_url = str(proof.get("cloudinary_file_url") or "").strip()
            if proof_url:
                st.link_button("View Proof", proof_url)
            col1, col2, col3 = st.columns(3)
            proof_id = proof.get("proof_id")
            with col1:
                if st.button("✅ Verify Payment", key=f"verify_{proof_id}"):
                    if proof_id is not None:
                        update_subscription_proof_verification(proof_id, st.session_state.get("user_name") or "Treasurer", PROOF_STATUS_VERIFIED, "Verified by Treasurer")
                        st.success("Payment verified.")
                        st.rerun()
            with col2:
                if st.button("❌ Reject Payment", key=f"reject_{proof_id}"):
                    if proof_id is not None:
                        update_subscription_proof_verification(proof_id, st.session_state.get("user_name") or "Treasurer", PROOF_STATUS_REJECTED, "Rejected by Treasurer")
                        st.warning("Payment rejected.")
                        st.rerun()
            with col3:
                if st.button("💬 Request Clarification", key=f"clarify_{proof_id}"):
                    if proof_id is not None:
                        update_subscription_proof_verification(proof_id, st.session_state.get("user_name") or "Treasurer", PROOF_STATUS_CLARIFICATION, "Clarification requested by Treasurer")
                        st.info("Clarification requested.")
                        st.rerun()
            if proof.get("transaction_reference"):
                st.caption(f"Reference: {proof.get('transaction_reference')}")
            if proof.get("comment"):
                st.caption(f"Comment: {proof.get('comment')}")


def render_chairperson_proof_audit() -> None:
    """Render chairperson read-only audit view of all proof submissions."""
    st.markdown("### Subscription Audit")
    proofs = fetch_all_subscription_proofs()
    if not proofs:
        st.info("No payment proof history is available yet.")
        return

    search_term = st.text_input("Search audit history")
    filtered = []
    if search_term:
        needle = search_term.lower()
        filtered = [proof for proof in proofs if needle in str(proof.get("member_name") or "").lower() or needle in str(proof.get("transaction_reference") or "").lower()]
    else:
        filtered = proofs

    if filtered:
        audit_df = pd.DataFrame(
            [
                {
                    "Member": proof.get("member_name") or "Unknown",
                    "Month": proof.get("subscription_month"),
                    "Year": proof.get("subscription_year"),
                    "Amount": f"UGX {int(float(proof.get('amount_paid') or 0)):,}",
                    "Method": proof.get("payment_method"),
                    "Upload Date": proof.get("upload_timestamp"),
                    "Status": proof.get("verification_status"),
                    "Verified By": proof.get("verified_by") or "-",
                }
                for proof in filtered
            ]
        )
        st.dataframe(audit_df, width="stretch", hide_index=True)

        for proof in filtered:
            if proof.get("cloudinary_file_url"):
                with st.expander(f"{proof.get('member_name')} • {proof.get('subscription_month')}/{proof.get('subscription_year')}"):
                    st.caption(f"Upload Date: {proof.get('upload_timestamp')}")
                    st.caption(f"Status: {proof.get('verification_status')}")
                    proof_url = str(proof.get("cloudinary_file_url") or "").strip()
                    if proof_url:
                        st.link_button("Open receipt", proof_url)
                    if proof.get("verification_comment"):
                        st.caption(f"Verification comment: {proof.get('verification_comment')}")


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


def member_view(member_id: str, show_proof_section: bool = True, user_role: str | None = None) -> None:
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

    st.markdown(render_pay_subscription_card_html(), unsafe_allow_html=True)
    effective_show_proof_section = show_proof_section and should_show_member_proof_section(user_role)
    if effective_show_proof_section:
        render_payment_proof_form(member_id, st.session_state.get("user_name") or "Member")
        render_member_payment_history(member_id, st.session_state.get("user_name") or "Member")

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
        st.dataframe(pd.DataFrame(history_rows), width="stretch", hide_index=True)

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
    rows = cached_read_query("SELECT member_id, full_name FROM members ORDER BY full_name;", params=None)
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
                    billing_month = st.date_input(
                        "Billing Month",
                        value=coerce_date_input_value(today_in_uganda(), date(2000, 1, 1), date(date.today().year, 12, 31)),
                        min_value=date(2000, 1, 1),
                        max_value=date(date.today().year, 12, 31),
                    )
                    amount = st.number_input(
                        "Amount Paid (UGX, max 20,000)",
                        min_value=0.0,
                        max_value=MAX_SUBSCRIPTION_AMOUNT,
                        value=MAX_SUBSCRIPTION_AMOUNT,
                        step=100.0,
                        help="Post a subscription payment amount up to UGX 20,000.",
                    )
                    submit_payment = st.form_submit_button("Post Payment")

                if submit_payment:
                    if amount > MAX_SUBSCRIPTION_AMOUNT:
                        st.error(f"The maximum allowed subscription payment is UGX {int(MAX_SUBSCRIPTION_AMOUNT):,}.")
                    else:
                        member_id = member_options[selected]
                        bm = billing_month.replace(day=1)
                        existing_total = get_member_monthly_subscription_total(member_id, bm.month, bm.year)
                        if existing_total + amount > MAX_SUBSCRIPTION_AMOUNT:
                            allowed_amount = max(0.0, MAX_SUBSCRIPTION_AMOUNT - existing_total)
                            st.error(
                                f"This member already has UGX {int(existing_total):,} recorded or pending for {bm.strftime('%B %Y')}. "
                                f"You can only post up to UGX {int(allowed_amount):,} more for this month."
                            )
                        else:
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
                            loan_rows = execute_query(
                                "SELECT loan_id, outstanding_balance, COALESCE(interest_accumulated, 0) AS interest_accumulated "
                                "FROM loans "
                                "WHERE member_id = %s AND status IN ('Active','Approved') "
                                "ORDER BY approved_date DESC NULLS LAST, applied_date DESC, loan_id DESC LIMIT 1;",
                                params=(member_id,),
                                fetch=True,
                            )
                            if not loan_rows:
                                st.info("No active approved loan found for this member.")
                            else:
                                loan = loan_rows[0]
                                loan_id = loan["loan_id"]
                                outstanding = float(loan.get("outstanding_balance") or 0.0)
                                interest_accumulated = float(loan.get("interest_accumulated") or 0.0)
                                principal = max(0.0, outstanding - interest_accumulated)

                                payment_to_principal = min(repay_amount, principal)
                                overpayment = max(0.0, repay_amount - payment_to_principal)
                                new_principal = principal - payment_to_principal
                                new_interest = max(0.0, interest_accumulated - overpayment)
                                new_outstanding = new_principal + new_interest

                                execute_query(
                                    "UPDATE loans SET outstanding_balance = %s, interest_accumulated = %s, last_payment_applied_at = %s WHERE loan_id = %s;",
                                    params=(new_outstanding, new_interest, date.today(), loan_id),
                                    fetch=False,
                                )
                                st.toast("Repayment applied to active loan.", icon="✅")
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

    if user_role == "Treasurer":
        render_treasurer_proof_management()
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
        st.dataframe(recent_df, width="stretch", hide_index=True)
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

    member_view(selected_member_id, show_proof_section=False, user_role=user_role)


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

    render_chairperson_proof_audit()
    st.markdown("---")

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
    member_view(selected_member_id, show_proof_section=False, user_role="Chairperson")


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

    if user_role == "Treasurer":
        treasurer_view(user_role)
        return

    if user_role == "Chairperson":
        chairperson_monitor_view()
        return

    if user_role in ("Secretary",):
        # Secretary may review ledgers and subscription history without posting actions.
        treasurer_view(user_role)
        return

    if user_role == "Member":
        st.info("Global financial updates are restricted to executive roles.")

    # Default: member view
    if not user_id:
        st.info("Log in to view subscriptions.")
        return

    member_view(user_id, user_role=user_role)


if __name__ == "__main__":
    subscriptions_view()
