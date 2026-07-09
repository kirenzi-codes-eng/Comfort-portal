import streamlit as st
import zoneinfo
from html import escape
from datetime import date, datetime

from app import coerce_date_input_value
from src.components.auth import find_member_by_identifier, get_avatar, update_member_avatar, update_member_password
from src.views.admin_docs import ensure_member_profile_columns, update_member_profile


def _normalize_profile_date(value):
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return None
        try:
            return date.fromisoformat(cleaned)
        except ValueError:
            try:
                return datetime.fromisoformat(cleaned.replace("Z", "+00:00")).date()
            except ValueError:
                return None
    return None


def _calculate_age(date_of_birth):
    dob = _normalize_profile_date(date_of_birth)
    if dob is None:
        return None
    today = date.today()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    return age


def _format_profile_summary_value(value):
    if value is None or value == "":
        return "Not provided"
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y")
    return str(value)


def _render_profile_summary_table(profile_data: dict) -> None:
    """Render profile information as elegant content cards."""
    rows = [
        ("Full Name", profile_data.get("full_name")),
        ("Email", profile_data.get("email")),
        ("Phone", profile_data.get("phone")),
        ("Date of Birth", profile_data.get("date_of_birth")),
        ("Gender", profile_data.get("gender")),
        ("Nationality", profile_data.get("nationality")),
        ("Address", profile_data.get("address")),
        ("City", profile_data.get("city")),
        ("Country", profile_data.get("country")),
        ("Occupation", profile_data.get("occupation")),
        ("Employer", profile_data.get("employer")),
        ("National ID", profile_data.get("national_id")),
        ("Next of Kin Name", profile_data.get("next_of_kin_name")),
        ("Next of Kin Relationship", profile_data.get("next_of_kin_relationship")),
        ("Next of Kin Phone", profile_data.get("next_of_kin_phone")),
        ("Emergency Contact Name", profile_data.get("emergency_contact_name")),
        ("Emergency Contact Phone", profile_data.get("emergency_contact_phone")),
        ("Notes", profile_data.get("notes")),
    ]

    with st.container(border=True):
        st.markdown("<div class='section-title'>Saved Profile Information</div>", unsafe_allow_html=True)
        for label, value in rows:
            st.markdown(f"<div class='attribute-row'><span class='attribute-label'>{escape(str(label))}</span><div class='attribute-value'>{escape(_format_profile_summary_value(value))}</div></div>", unsafe_allow_html=True)


def profile_view() -> None:
    try:
        st.set_page_config(layout="wide", initial_sidebar_state="expanded")
    except Exception:
        pass

    user_role = st.session_state.get("user_role", "Member")

    st.markdown(
        """
        <style>
            .stApp { background: #f8fafc; }
            .block-container { padding-top: 1rem; padding-bottom: 2rem; max-width: 1400px; }
            .profile-shell { padding: 0.25rem 0 1rem; }
            .hero-card {
                border-radius: 24px;
                background: linear-gradient(135deg, #0f172a 0%, #111827 100%);
                color: #ffffff;
                padding: 1.1rem 1.2rem;
                margin-bottom: 0.95rem;
                box-shadow: 0 18px 40px rgba(15, 23, 42, 0.14);
            }
            .hero-grid { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
            .hero-avatar {
                width: 84px; height: 84px; border-radius: 999px; overflow: hidden; border: 3px solid rgba(255,255,255,0.16); flex-shrink: 0;
            }
            .hero-avatar img { width: 100%; height: 100%; object-fit: cover; }
            .hero-name { font-size: clamp(1.15rem, 1.7vw, 1.45rem); font-weight: 800; margin: 0; }
            .hero-subtext { color: rgba(255,255,255,0.8); font-size: 0.92rem; margin-top: 0.25rem; }
            .pill { display: inline-flex; align-items: center; border-radius: 999px; padding: 0.34rem 0.7rem; font-size: 0.76rem; font-weight: 700; margin-top: 0.4rem; }
            .pill-role { background: #ecfdf3; color: #047857; }
            .section-title { font-size: 1rem; font-weight: 800; color: #0f172a; margin-bottom: 0.65rem; }
            .attribute-row { margin-bottom: 0.6rem; }
            .attribute-label { display: block; font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.08em; color: #64748b; font-weight: 700; margin-bottom: 0.2rem; }
            .attribute-value { font-size: 0.95rem; font-weight: 700; color: #0f172a; line-height: 1.45; }
            .empty-state { text-align: center; padding: 1rem; border: 1px dashed #cbd5e1; border-radius: 16px; background: #f8fafc; color: #64748b; }
            .action-row { display: flex; gap: 0.7rem; flex-wrap: wrap; margin-top: 0.8rem; }
            .stButton > button { border-radius: 999px !important; padding: 0.58rem 0.95rem !important; font-weight: 700; }
            .stButton > button[kind="primary"] { background: #4f46e5 !important; color: white !important; border: none !important; }
            @media (max-width: 768px) {
                .hero-grid { flex-direction: column; align-items: flex-start; }
                .hero-avatar { width: 72px; height: 72px; }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )

    user_id = st.session_state.get("user_id")
    if not user_id:
        st.warning("Please sign in to manage your profile and security settings.")
        return

    ensure_member_profile_columns()
    member = find_member_by_identifier(user_id) or {}
    avatar_url = get_avatar(user_id, st.session_state.get("user_name"))
    date_of_birth = _normalize_profile_date(member.get("date_of_birth"))
    age = _calculate_age(date_of_birth)

    if "profile_last_submitted" not in st.session_state and member:
        st.session_state["profile_last_submitted"] = {
            "full_name": member.get("full_name"),
            "email": member.get("email"),
            "phone": member.get("phone"),
            "date_of_birth": member.get("date_of_birth"),
            "gender": member.get("gender"),
            "nationality": member.get("nationality"),
            "address": member.get("address"),
            "city": member.get("city"),
            "country": member.get("country"),
            "occupation": member.get("occupation"),
            "employer": member.get("employer"),
            "national_id": member.get("national_id"),
            "next_of_kin_name": member.get("next_of_kin_name"),
            "next_of_kin_relationship": member.get("next_of_kin_relationship"),
            "next_of_kin_phone": member.get("next_of_kin_phone"),
            "emergency_contact_name": member.get("emergency_contact_name"),
            "emergency_contact_phone": member.get("emergency_contact_phone"),
            "notes": member.get("notes"),
        }

    st.markdown("<div class='profile-shell'>", unsafe_allow_html=True)

    st.markdown(
        f"""
        <div class='hero-card'>
            <div class='hero-grid'>
                <div style='display:flex;align-items:center;gap:0.9rem;'>
                    <div class='hero-avatar'><img src="{avatar_url}" alt="avatar" /></div>
                    <div>
                        <div class='hero-name'>{escape(st.session_state.get('user_name', 'Member'))}</div>
                        <div class='hero-subtext'>Age: {age if age is not None else 'Not set'} • {escape(st.session_state.get('user_role', 'Member'))}</div>
                        <span class='pill pill-role'>Verified account</span>
                    </div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tabs = st.tabs(["👤 Profile Details", "📷 Photo Upload", "🔒 Security & Password"])

    with tabs[0]:
        with st.container(border=True):
            st.markdown("<div class='section-title'>Personal & Contact Information</div>", unsafe_allow_html=True)
            st.caption("Keep your core identity, contact, and operational details up to date.")

            is_regular_member = (user_role == "Member")
            edit_mode = st.session_state.get("profile_edit_mode", False)

            summary_source = st.session_state.get("profile_last_submitted") or member or {}
            if summary_source:
                _render_profile_summary_table(summary_source)
            else:
                st.markdown(
                    """
                    <div class='empty-state'>
                        <div>No profile information has been saved yet.</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

            if is_regular_member and not edit_mode:
                if st.button("Edit Profile Details", key="profile_edit_toggle", width="stretch"):
                    st.session_state["profile_edit_mode"] = True
                    st.rerun()
            else:
                with st.form("member_profile_form_full"):
                    col1, col2 = st.columns(2)
                    with col1:
                        full_name = st.text_input("Full Name", value=str(member.get("full_name") or ""), key="profile_full_name")
                        email = st.text_input("Email", value=str(member.get("email") or ""), key="profile_email")
                        phone = st.text_input("Phone", value=str(member.get("phone") or ""), key="profile_phone")
                        safe_date = coerce_date_input_value(date_of_birth, date(1962, 1, 1), date(date.today().year, 12, 31))
                        date_of_birth_value = st.date_input("Date of Birth", value=safe_date, min_value=date(1962, 1, 1), max_value=date(date.today().year, 12, 31), key="profile_date_of_birth")
                        gender = st.selectbox("Gender", ["Male", "Female", "Other", "Prefer not to say"], index=["Male", "Female", "Other", "Prefer not to say"].index(str(member.get("gender") or "Prefer not to say")) if str(member.get("gender") or "") in ["Male", "Female", "Other"] else 3, key="profile_gender")
                        nationality = st.text_input("Nationality", value=str(member.get("nationality") or ""), key="profile_nationality")
                        address = st.text_input("Address", value=str(member.get("address") or ""), key="profile_address")
                    with col2:
                        city = st.text_input("City", value=str(member.get("city") or ""), key="profile_city")
                        country = st.text_input("Country", value=str(member.get("country") or ""), key="profile_country")
                        occupation = st.text_input("Occupation", value=str(member.get("occupation") or ""), key="profile_occupation")
                        employer = st.text_input("Employer", value=str(member.get("employer") or ""), key="profile_employer")
                        national_id = st.text_input("National ID", value=str(member.get("national_id") or ""), key="profile_national_id")
                        next_of_kin_name = st.text_input("Next of Kin Name", value=str(member.get("next_of_kin_name") or ""), key="profile_next_of_kin_name")
                        next_of_kin_relationship = st.text_input("Next of Kin Relationship", value=str(member.get("next_of_kin_relationship") or ""), key="profile_next_of_kin_relationship")
                        next_of_kin_phone = st.text_input("Next of Kin Phone", value=str(member.get("next_of_kin_phone") or ""), key="profile_next_of_kin_phone")
                        emergency_contact_name = st.text_input("Emergency Contact Name", value=str(member.get("emergency_contact_name") or ""), key="profile_emergency_contact_name")
                        emergency_contact_phone = st.text_input("Emergency Contact Phone", value=str(member.get("emergency_contact_phone") or ""), key="profile_emergency_contact_phone")
                    notes = st.text_area("Notes", value=str(member.get("notes") or ""), key="profile_notes")

                    buttons = st.columns([1, 1])
                    with buttons[0]:
                        submit_full = st.form_submit_button("Save Changes")
                    with buttons[1]:
                        cancel_full = st.form_submit_button("Cancel")

                if cancel_full:
                    st.session_state["profile_edit_mode"] = False
                    st.rerun()
                if submit_full:
                    update_member_profile(
                        user_id,
                        full_name.strip() or member.get("full_name") or "",
                        email.strip() or member.get("email") or "",
                        phone.strip() or member.get("phone") or "",
                        member.get("role") or "Member",
                        member.get("status") or "Active",
                        member.get("join_date"),
                        notes.strip() or member.get("notes") or None,
                        date_of_birth_value,
                        gender.strip() or member.get("gender") or None,
                        address.strip() or member.get("address") or None,
                        city.strip() or member.get("city") or None,
                        country.strip() or member.get("country") or None,
                        nationality.strip() or member.get("nationality") or None,
                        occupation.strip() or member.get("occupation") or None,
                        employer.strip() or member.get("employer") or None,
                        national_id.strip() or member.get("national_id") or None,
                        next_of_kin_name.strip() or member.get("next_of_kin_name") or None,
                        next_of_kin_relationship.strip() or member.get("next_of_kin_relationship") or None,
                        next_of_kin_phone.strip() or member.get("next_of_kin_phone") or None,
                        emergency_contact_name.strip() or member.get("emergency_contact_name") or None,
                        emergency_contact_phone.strip() or member.get("emergency_contact_phone") or None,
                    )
                    submitted_profile = {
                        "full_name": full_name.strip() or member.get("full_name") or "",
                        "email": email.strip() or member.get("email") or "",
                        "phone": phone.strip() or member.get("phone") or "",
                        "date_of_birth": date_of_birth_value,
                        "gender": gender.strip() or member.get("gender") or None,
                        "nationality": nationality.strip() or member.get("nationality") or None,
                        "address": address.strip() or member.get("address") or None,
                        "city": city.strip() or member.get("city") or None,
                        "country": country.strip() or member.get("country") or None,
                        "occupation": occupation.strip() or member.get("occupation") or None,
                        "employer": employer.strip() or member.get("employer") or None,
                        "national_id": national_id.strip() or member.get("national_id") or None,
                        "next_of_kin_name": next_of_kin_name.strip() or member.get("next_of_kin_name") or None,
                        "next_of_kin_relationship": next_of_kin_relationship.strip() or member.get("next_of_kin_relationship") or None,
                        "next_of_kin_phone": next_of_kin_phone.strip() or member.get("next_of_kin_phone") or None,
                        "emergency_contact_name": emergency_contact_name.strip() or member.get("emergency_contact_name") or None,
                        "emergency_contact_phone": emergency_contact_phone.strip() or member.get("emergency_contact_phone") or None,
                        "notes": notes.strip() or member.get("notes") or None,
                    }
                    st.session_state["profile_last_submitted"] = submitted_profile
                    st.session_state["profile_edit_mode"] = False
                    for key in [
                        "profile_full_name",
                        "profile_email",
                        "profile_phone",
                        "profile_date_of_birth",
                        "profile_gender",
                        "profile_nationality",
                        "profile_address",
                        "profile_city",
                        "profile_country",
                        "profile_occupation",
                        "profile_employer",
                        "profile_national_id",
                        "profile_next_of_kin_name",
                        "profile_next_of_kin_relationship",
                        "profile_next_of_kin_phone",
                        "profile_emergency_contact_name",
                        "profile_emergency_contact_phone",
                        "profile_notes",
                    ]:
                        if key in st.session_state:
                            del st.session_state[key]
                    st.success("Your profile details have been updated.")
                    st.rerun()

    with tabs[1]:
        with st.container(border=True):
            st.markdown("<div class='section-title'>Photo Upload</div>", unsafe_allow_html=True)
            st.caption("Upload a portrait that will appear across the portal.")
            uploaded_photo = st.file_uploader("Upload passport/profile photo (JPEG/PNG)", type=["jpg", "png", "jpeg"])
            if uploaded_photo:
                st.image(uploaded_photo, caption="Uploaded Preview", width=200)
                if st.button("Save Profile Image", width="stretch"):
                    success, message, saved_path = update_member_avatar(user_id, uploaded_photo)
                    if success:
                        st.success(message)
                        if saved_path:
                            st.caption(f"Cloudinary URL: {saved_path}")
                    else:
                        st.error(message)

    with tabs[2]:
        with st.container(border=True):
            st.markdown("<div class='section-title'>Security & Password</div>", unsafe_allow_html=True)
            st.caption("Keep your account credentials secure and current.")
            with st.form("password_mutation_form"):
                old_pass = st.text_input("Confirm Current Password", type="password")
                new_pass = st.text_input("Enter New Secure Password", type="password")
                confirm_new = st.text_input("Confirm New Secure Password", type="password")
                submit_pass = st.form_submit_button("Update Password")
                if submit_pass:
                    if new_pass != confirm_new:
                        st.error("The new passwords do not match.")
                    elif not old_pass:
                        st.error("You must enter your current password to verify identity.")
                    elif len(new_pass) < 6:
                        st.error("Password must be at least 6 characters long.")
                    else:
                        success, message = update_member_password(user_id, old_pass, new_pass)
                        if success:
                            st.success(message)
                        else:
                            st.error(message)

    st.markdown("</div>", unsafe_allow_html=True)
