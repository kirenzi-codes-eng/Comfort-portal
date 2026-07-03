import streamlit as st
import zoneinfo
from html import escape
from datetime import date, datetime

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


def profile_view() -> None:
    uganda_tz = zoneinfo.ZoneInfo("Africa/Kampala")
    user_role = st.session_state.get("user_role", "Member")

    st.markdown("""
        <style>
            .profile-card {
                background-color: #FFFFFF;
                border: 1px solid #E5E7EB;
                border-radius: 12px;
                padding: 1.5rem;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.02);
                margin-bottom: 2rem;
            }
            .security-badge {
                background-color: #F8FAFC;
                border-left: 4px solid #3B82F6;
                padding: 1rem;
                border-radius: 0 8px 8px 0;
                margin-bottom: 1rem;
            }
        </style>
    """, unsafe_allow_html=True)

    # Premium dashboard header and refined styles
    st.markdown(
        """
        <style>
        /* Header gradient */
        .dashboard-header {
            background: linear-gradient(90deg, #0F172A 0%, #1E3A8A 100%);
            color: #ffffff;
            padding: 28px 22px;
            border-radius: 14px;
            display: flex;
            align-items: center;
            gap: 18px;
            box-shadow: 0 12px 28px rgba(12, 18, 36, 0.28);
            margin-bottom: 18px;
        }

        .profile-avatar-frame {
            width: 112px;
            height: 112px;
            border-radius: 50%;
            overflow: hidden;
            display: inline-block;
            background: #ffffff;
            padding: 4px;
            box-shadow: 0 6px 18px rgba(2,6,23,0.32);
            flex-shrink: 0;
        }

        .profile-avatar-frame img { display:block;width:100%;height:100%;object-fit:cover;border-radius:50%; }

        .profile-header-meta { display:flex;flex-direction:column;gap:6px; }
        .profile-name { font-size:1.28rem;font-weight:700;margin:0;color:#ffffff; }
        .role-badge { display:inline-block;background:#14B8A6;color:#042022;padding:6px 10px;border-radius:999px;font-weight:700;font-size:0.82rem;border:1px solid rgba(255,255,255,0.06); }

        /* White panel cards for forms */
        .form-panel-card { background: #ffffff; border: 1px solid #E2E8F0; border-radius: 10px; padding: 18px; box-shadow: 0 6px 16px rgba(15,23,42,0.04); margin-bottom: 14px; }

        @media (max-width: 640px) {
            .dashboard-header { flex-direction: column; align-items: flex-start; gap: 12px; padding: 18px; }
            .profile-header-meta { align-items: flex-start; }
            .profile-avatar-frame { width: 84px; height: 84px; }
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

    # Render premium full-width header
    st.markdown(
        f"""
        <div class="dashboard-header">
            <div class="profile-avatar-frame">
                <img src="{avatar_url}" alt="avatar" />
            </div>
            <div class="profile-header-meta">
                <div style="display:flex;gap:12px;align-items:center;">
                    <div class="profile-name">{st.session_state.get('user_name', 'Member')}</div>
                    <div class="role-badge">{st.session_state.get('user_role', 'Member')}</div>
                </div>
                <div style="color:rgba(255,255,255,0.86);font-size:0.92rem;">Age: {age if age is not None else 'Not set'}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tabs = st.tabs(["Profile Details", "Photo Upload", "Security & Password"])

    # Profile details panel: for regular members show summary and minimized professional edit form
    with tabs[0]:
        st.markdown('<div class="form-panel-card">', unsafe_allow_html=True)
        st.subheader("Personal & Contact Information")

        is_regular_member = (user_role == "Member")
        edit_mode = st.session_state.get("profile_edit_mode", False)

        if is_regular_member and not edit_mode:
            # Summary view (read-only)
            col1, col2 = st.columns([2, 1])
            with col1:
                st.markdown(f"**Full name:** {escape(str(member.get('full_name') or '-'))}")
                st.markdown(f"**Email:** {escape(str(member.get('email') or '-'))}")
                st.markdown(f"**Phone:** {escape(str(member.get('phone') or '-'))}")
                dob_text = _normalize_profile_date(member.get('date_of_birth'))
                st.markdown(f"**Date of birth:** {escape(str(dob_text or '-'))}")
                st.markdown(f"**Gender:** {escape(str(member.get('gender') or '-'))}")
                st.markdown(f"**Nationality:** {escape(str(member.get('nationality') or '-'))}")
                st.markdown(f"**Address:** {escape(str(member.get('address') or '-'))}")
            with col2:
                st.markdown(f"**Occupation:** {escape(str(member.get('occupation') or '-'))}")
                st.markdown(f"**Employer:** {escape(str(member.get('employer') or '-'))}")
                st.markdown(f"**National ID:** {escape(str(member.get('national_id') or '-'))}")
                st.markdown(f"**Emergency Contact:** {escape(str(member.get('emergency_contact_name') or '-'))} — {escape(str(member.get('emergency_contact_phone') or '-'))}")
                st.markdown(f"**Notes:** {escape(str(member.get('notes') or '-'))}")

            if st.button("Edit Profile Details", key="profile_edit_toggle"):
                st.session_state["profile_edit_mode"] = True

        else:
            # Minimized professional edit form
            st.markdown("<div style='margin-bottom:8px;color:#334155;'>Use this form to submit professional updates. Fields are minimized for clarity.</div>", unsafe_allow_html=True)
            with st.form("member_profile_form_min"):
                col1, col2 = st.columns(2)
                with col1:
                    full_name = st.text_input("Full name", value=str(member.get("full_name") or ""), key="profile_full_name")
                    email = st.text_input("Email", value=str(member.get("email") or ""), key="profile_email")
                    phone = st.text_input("Phone", value=str(member.get("phone") or ""), key="profile_phone")
                    date_of_birth_value = st.date_input(
                        "Date of birth",
                        value=date_of_birth or date.today(),
                        key="profile_date_of_birth",
                    )
                with col2:
                    address = st.text_input("Address", value=str(member.get("address") or ""), key="profile_address")
                    city = st.text_input("City", value=str(member.get("city") or ""), key="profile_city")
                    country = st.text_input("Country", value=str(member.get("country") or ""), key="profile_country")
                    nationality = st.text_input("Nationality", value=str(member.get("nationality") or ""), key="profile_nationality")

                btn_col1, btn_col2 = st.columns([1, 1])
                with btn_col1:
                    submit_min = st.form_submit_button("Save Changes")
                with btn_col2:
                    cancel_min = st.form_submit_button("Cancel")

            if cancel_min:
                st.session_state["profile_edit_mode"] = False
            if submit_min:
                update_member_profile(
                    user_id,
                    full_name.strip() or member.get("full_name") or "",
                    email.strip() or member.get("email") or "",
                    phone.strip() or member.get("phone") or "",
                    member.get("role") or "Member",
                    member.get("status") or "Active",
                    member.get("join_date"),
                    None,
                    date_of_birth_value,
                    None,
                    address.strip() or None,
                    city.strip() or None,
                    country.strip() or None,
                    nationality.strip() or None,
                )
                st.session_state["profile_edit_mode"] = False
                st.success("Your profile details have been updated.")

        st.markdown('</div>', unsafe_allow_html=True)

    # Photo upload panel
    with tabs[1]:
        st.markdown('<div class="form-panel-card">', unsafe_allow_html=True)
        st.subheader("Profile Photo Management")
        uploaded_photo = st.file_uploader("Upload passport/profile photo (JPEG/PNG)", type=["jpg", "png", "jpeg"])
        if uploaded_photo:
            st.image(uploaded_photo, caption="Uploaded Preview", width=150)
            if st.button("Save Profile Image"):
                success, message, saved_path = update_member_avatar(user_id, uploaded_photo)
                if success:
                    st.success(message)
                    if saved_path:
                        st.caption(f"Cloudinary URL: {saved_path}")
                else:
                    st.error(message)
        st.markdown('</div>', unsafe_allow_html=True)

    # Security / password panel
    with tabs[2]:
        st.markdown('<div class="form-panel-card">', unsafe_allow_html=True)
        st.subheader("Update Authentication Credentials")
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
        st.markdown('</div>', unsafe_allow_html=True)
