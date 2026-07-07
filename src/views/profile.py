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


def _format_profile_summary_value(value):
    if value is None or value == "":
        return "Not provided"
    if isinstance(value, date):
        return value.strftime("%d %b %Y")
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y")
    return str(value)


def _render_profile_summary_table(profile_data: dict) -> None:
    """Render the submitted profile information as a clear, full-width summary table."""
    st.markdown('<div class="profile-summary-card">', unsafe_allow_html=True)
    st.markdown("<h4 style='margin:0 0 10px 0; color:#0f172a;'>Profile Summary</h4>", unsafe_allow_html=True)

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

    html_rows = "".join(
        f"<tr><th>{escape(str(label))}</th><td>{escape(_format_profile_summary_value(value))}</td></tr>"
        for label, value in rows
    )

    st.markdown(
        f"""
        <table class="profile-summary-table">
            <tbody>{html_rows}</tbody>
        </table>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)


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
            .profile-summary-card {
                background: #ffffff;
                border: 1px solid #E2E8F0;
                border-radius: 12px;
                padding: 14px 16px;
                box-shadow: 0 6px 16px rgba(15,23,42,0.04);
                margin-bottom: 14px;
            }
            .profile-summary-table {
                width: 100%;
                border-collapse: collapse;
                font-size: 0.92rem;
            }
            .profile-summary-table th {
                text-align: left;
                font-weight: 700;
                color: #334155;
                padding: 8px 10px;
                border-bottom: 1px solid #E2E8F0;
                width: 38%;
                vertical-align: top;
            }
            .profile-summary-table td {
                padding: 8px 10px;
                border-bottom: 1px solid #E2E8F0;
                color: #0f172a;
                vertical-align: top;
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

        summary_source = st.session_state.get("profile_last_submitted") or member or {}
        if summary_source:
            st.markdown("### Saved Profile Information")
            _render_profile_summary_table(summary_source)
        else:
            st.info("No profile information has been saved yet.")

        if is_regular_member and not edit_mode:
            if st.button("Edit Profile Details", key="profile_edit_toggle"):
                st.session_state["profile_edit_mode"] = True

        else:
            st.markdown("<div style='margin-bottom:8px;color:#334155;'>Use this form to update your profile. All personal and contact fields are visible below.</div>", unsafe_allow_html=True)
            with st.form("member_profile_form_full"):
                col1, col2 = st.columns(2)
                with col1:
                    full_name = st.text_input("Full Name", value=str(member.get("full_name") or ""), key="profile_full_name")
                    email = st.text_input("Email", value=str(member.get("email") or ""), key="profile_email")
                    phone = st.text_input("Phone", value=str(member.get("phone") or ""), key="profile_phone")
                    safe_date = date_of_birth if date_of_birth and date(1962, 1, 1) <= date_of_birth <= date(2016, 12, 31) else date(2000, 1, 1)
                    date_of_birth_value = st.date_input(
                        "Date of Birth",
                        value=safe_date,
                        min_value=date(1962, 1, 1),
                        max_value=date(2026, 12, 31),
                        key="profile_date_of_birth",
                    )
                    gender = st.selectbox(
                        "Gender",
                        ["Male", "Female", "Other", "Prefer not to say"],
                        index=["Male", "Female", "Other", "Prefer not to say"].index(str(member.get("gender") or "Prefer not to say")) if str(member.get("gender") or "") in ["Male", "Female", "Other"] else 3,
                        key="profile_gender",
                    )
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

                btn_col1, btn_col2 = st.columns([1, 1])
                with btn_col1:
                    submit_full = st.form_submit_button("Save Changes")
                with btn_col2:
                    cancel_full = st.form_submit_button("Cancel")

            if cancel_full:
                st.session_state["profile_edit_mode"] = False
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
                st.markdown("### Saved Profile Information")
                _render_profile_summary_table(submitted_profile)
                st.rerun()

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
