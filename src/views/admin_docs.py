import os
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
from html import escape

from src.database.connection import execute_query

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def ensure_member_profile_columns() -> None:
    try:
        execute_query(
            """
            ALTER TABLE members
            ADD COLUMN IF NOT EXISTS join_date DATE,
            ADD COLUMN IF NOT EXISTS notes TEXT,
            ADD COLUMN IF NOT EXISTS avatar_url TEXT,
            ADD COLUMN IF NOT EXISTS date_of_birth DATE,
            ADD COLUMN IF NOT EXISTS gender TEXT,
            ADD COLUMN IF NOT EXISTS address TEXT,
            ADD COLUMN IF NOT EXISTS city TEXT,
            ADD COLUMN IF NOT EXISTS country TEXT,
            ADD COLUMN IF NOT EXISTS nationality TEXT,
            ADD COLUMN IF NOT EXISTS occupation TEXT,
            ADD COLUMN IF NOT EXISTS employer TEXT,
            ADD COLUMN IF NOT EXISTS national_id TEXT,
            ADD COLUMN IF NOT EXISTS next_of_kin_name TEXT,
            ADD COLUMN IF NOT EXISTS next_of_kin_relationship TEXT,
            ADD COLUMN IF NOT EXISTS next_of_kin_phone TEXT,
            ADD COLUMN IF NOT EXISTS emergency_contact_name TEXT,
            ADD COLUMN IF NOT EXISTS emergency_contact_phone TEXT;
            """,
            params=None,
            fetch=False,
        )
    except Exception as exc:
        st.warning(f"Unable to prepare member profile fields: {exc}")


def _normalize_join_date(value: Optional[object]) -> Optional[date]:
    if value in (None, "", "None"):
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


def build_member_profile_update(
    member_id: str,
    full_name: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None,
    role: Optional[str] = None,
    status: Optional[str] = None,
    join_date: Optional[object] = None,
    notes: Optional[str] = None,
    date_of_birth: Optional[object] = None,
    gender: Optional[str] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    nationality: Optional[str] = None,
    occupation: Optional[str] = None,
    employer: Optional[str] = None,
    national_id: Optional[str] = None,
    next_of_kin_name: Optional[str] = None,
    next_of_kin_relationship: Optional[str] = None,
    next_of_kin_phone: Optional[str] = None,
    emergency_contact_name: Optional[str] = None,
    emergency_contact_phone: Optional[str] = None,
) -> Tuple[str, Tuple[object, ...]]:
    updates: List[str] = []
    params: List[object] = []

    if full_name is not None:
        updates.append("full_name = %s")
        params.append(full_name)
    if email is not None:
        updates.append("email = %s")
        params.append(email)
    if phone is not None:
        updates.append("phone = %s")
        params.append(phone)
    if role is not None:
        updates.append("role = %s")
        params.append(role)
    if status is not None:
        updates.append("status = %s")
        params.append(status)
    if join_date is not None:
        updates.append("join_date = %s")
        params.append(_normalize_join_date(join_date) or join_date)
    if notes is not None:
        updates.append("notes = %s")
        params.append(notes)
    if date_of_birth is not None:
        updates.append("date_of_birth = %s")
        params.append(_normalize_join_date(date_of_birth) or date_of_birth)
    if gender is not None:
        updates.append("gender = %s")
        params.append(gender)
    if address is not None:
        updates.append("address = %s")
        params.append(address)
    if city is not None:
        updates.append("city = %s")
        params.append(city)
    if country is not None:
        updates.append("country = %s")
        params.append(country)
    if nationality is not None:
        updates.append("nationality = %s")
        params.append(nationality)
    if occupation is not None:
        updates.append("occupation = %s")
        params.append(occupation)
    if employer is not None:
        updates.append("employer = %s")
        params.append(employer)
    if national_id is not None:
        updates.append("national_id = %s")
        params.append(national_id)
    if next_of_kin_name is not None:
        updates.append("next_of_kin_name = %s")
        params.append(next_of_kin_name)
    if next_of_kin_relationship is not None:
        updates.append("next_of_kin_relationship = %s")
        params.append(next_of_kin_relationship)
    if next_of_kin_phone is not None:
        updates.append("next_of_kin_phone = %s")
        params.append(next_of_kin_phone)
    if emergency_contact_name is not None:
        updates.append("emergency_contact_name = %s")
        params.append(emergency_contact_name)
    if emergency_contact_phone is not None:
        updates.append("emergency_contact_phone = %s")
        params.append(emergency_contact_phone)

    if not updates:
        return "", tuple()

    query = f"UPDATE members SET {', '.join(updates)} WHERE member_id = %s;"
    params.append(member_id)
    return query, tuple(params)


def fetch_member_directory() -> List[Dict]:
    """Fetch member directory with 5-minute cache TTL."""
    return fetch_member_directory_cached()


@st.cache_data(ttl=300)
def fetch_member_directory_cached() -> List[Dict]:
    rows = execute_query(
        "SELECT member_id, full_name, email, phone, role, status, join_date, notes, avatar_url FROM members ORDER BY full_name;",
        params=None,
        fetch=True,
    )
    return rows or []


def fetch_member_record(member_id: str) -> Optional[Dict]:
    rows = execute_query(
        "SELECT member_id, full_name, email, phone, role, status, join_date, notes, avatar_url, date_of_birth, gender, address, city, country, nationality, occupation, employer, national_id, next_of_kin_name, next_of_kin_relationship, next_of_kin_phone, emergency_contact_name, emergency_contact_phone FROM members WHERE member_id = %s LIMIT 1;",
        params=(member_id,),
        fetch=True,
    )
    return rows[0] if rows else None


def fetch_documents() -> List[Dict]:
    """Fetch documents with 5-minute cache TTL."""
    return fetch_documents_cached()


@st.cache_data(ttl=300)
def fetch_documents_cached() -> List[Dict]:
    rows = execute_query(
        "SELECT title, file_url, uploaded_at FROM group_documents ORDER BY uploaded_at DESC;",
        params=None,
        fetch=True,
    )
    return rows or []


def save_document_record(title: str, file_url: str, uploaded_by: str) -> None:
    execute_query(
        "INSERT INTO group_documents (title, file_url, uploaded_at, uploaded_by) VALUES (%s, %s, %s, %s);",
        params=(title, file_url, datetime.utcnow(), uploaded_by),
        fetch=False,
    )


def update_member_role_status(member_id: str, new_role: str, new_status: str) -> None:
    execute_query(
        "UPDATE members SET role = %s, status = %s WHERE member_id = %s;",
        params=(new_role, new_status, member_id),
        fetch=False,
    )


def approve_new_registration(member_id: str) -> None:
    execute_query(
        "UPDATE members SET status = %s, role = %s WHERE member_id = %s;",
        params=("Active", "Member", member_id),
        fetch=False,
    )
    try:
        fetch_member_directory_cached.clear()
    except Exception:
        pass


def update_member_profile(
    member_id: str,
    full_name: str,
    email: str,
    phone: str,
    role: str,
    status: str,
    join_date: Optional[object],
    notes: Optional[str],
    date_of_birth: Optional[object] = None,
    gender: Optional[str] = None,
    address: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    nationality: Optional[str] = None,
    occupation: Optional[str] = None,
    employer: Optional[str] = None,
    national_id: Optional[str] = None,
    next_of_kin_name: Optional[str] = None,
    next_of_kin_relationship: Optional[str] = None,
    next_of_kin_phone: Optional[str] = None,
    emergency_contact_name: Optional[str] = None,
    emergency_contact_phone: Optional[str] = None,
) -> None:
    ensure_member_profile_columns()
    query, params = build_member_profile_update(
        member_id,
        full_name=full_name,
        email=email,
        phone=phone,
        role=role,
        status=status,
        join_date=join_date,
        notes=notes,
        date_of_birth=date_of_birth,
        gender=gender,
        address=address,
        city=city,
        country=country,
        nationality=nationality,
        occupation=occupation,
        employer=employer,
        national_id=national_id,
        next_of_kin_name=next_of_kin_name,
        next_of_kin_relationship=next_of_kin_relationship,
        next_of_kin_phone=next_of_kin_phone,
        emergency_contact_name=emergency_contact_name,
        emergency_contact_phone=emergency_contact_phone,
    )
    if query:
        execute_query(query, params=params, fetch=False)
        if st.session_state.get("user_id") == member_id:
            st.session_state["join_date"] = join_date
            st.session_state["user_status"] = status
        try:
            fetch_member_directory_cached.clear()
        except Exception:
            pass


def admin_docs_view():
    st.header("Member Directory & Document Repository")
    user_role = st.session_state.get("user_role")
    user_name = st.session_state.get("user_name")

    allowed_roles = {"Chairperson", "Secretary", "Treasurer", "Vice Chairperson", "Welfare"}
    if user_role not in allowed_roles:
        st.info("You do not have access to the admin directory or document repository.")
        return

    ensure_member_profile_columns()

    # Member Directory
    st.subheader("Member Details Directory")
    members = fetch_member_directory()
    if members:
        df = pd.DataFrame(members)
        st.dataframe(df)
    else:
        st.info("No members found.")

    if user_role == "Chairperson":
        st.write("---")
        st.subheader("Approve New Registrations")
        pending_members = [row for row in members if str(row.get("status") or "").lower() in {"pending", "new"}]
        if pending_members:
            for member in pending_members:
                with st.container():
                    st.markdown(
                        f"""
                        <div style='background: linear-gradient(135deg, #fef3c7 0%, #fff7ed 100%); border: 1px solid #fdba74; border-radius: 16px; padding: 14px 16px; margin-bottom: 10px;'>
                          <div style='font-weight: 700; color: #9a2c00;'>{member.get('full_name') or 'Unnamed Member'} ({member.get('member_id')})</div>
                          <div style='color: #7c2d12; margin-top: 4px;'>Email: {member.get('email') or '-'} • Phone: {member.get('phone') or '-'}</div>
                          <div style='color: #7c2d12; margin-top: 6px;'>Current status: {member.get('status') or 'Pending'}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
                    if st.button("Approve Registration", key=f"approve_{member['member_id']}"):
                        approve_new_registration(member["member_id"])
                        st.toast(f"Approved registration for {member['member_id']}", icon="✅")
                        st.rerun()
        else:
            st.info("No pending registrations to approve right now.")

        st.write("---")
        st.subheader("Update Member Profile")
        member_map = {f"{row['full_name']} ({row['member_id']})": row for row in members}
        selected_key = st.selectbox("Select member", options=list(member_map.keys()), key="chairperson_member_profile_select")
        selected_member = member_map[selected_key]
        selected_member_detail = fetch_member_record(selected_member["member_id"]) or selected_member

        # Display member avatar if available
        with st.container():
            avatar_url = selected_member_detail.get("avatar_url")
            if avatar_url:
                st.image(avatar_url, width=100, caption="Member profile photo")
            else:
                st.info("No profile photo set for this member.")

        member_key = selected_member_detail.get("member_id")
        edit_flag_key = f"chairperson_edit_mode_{member_key}"
        if edit_flag_key not in st.session_state:
            st.session_state[edit_flag_key] = False

        # If not editing, show a read-only summary and an Edit button
        if not st.session_state[edit_flag_key]:
            st.markdown("**Member Summary**")
            c1, c2 = st.columns([2, 1])
            with c1:
                st.markdown(f"**Full name:** {escape(str(selected_member_detail.get('full_name') or '-'))}")
                st.markdown(f"**Email:** {escape(str(selected_member_detail.get('email') or '-'))}")
                st.markdown(f"**Phone:** {escape(str(selected_member_detail.get('phone') or '-'))}")
                st.markdown(f"**Role:** {escape(str(selected_member_detail.get('role') or '-'))}")
                st.markdown(f"**Status:** {escape(str(selected_member_detail.get('status') or '-'))}")
                st.markdown(f"**Join date:** {escape(str(selected_member_detail.get('join_date') or '-'))}")
            with c2:
                st.markdown(f"**Occupation:** {escape(str(selected_member_detail.get('occupation') or '-'))}")
                st.markdown(f"**Employer:** {escape(str(selected_member_detail.get('employer') or '-'))}")
                st.markdown(f"**National ID:** {escape(str(selected_member_detail.get('national_id') or '-'))}")
                st.markdown(f"**Emergency Contact:** {escape(str(selected_member_detail.get('next_of_kin_name') or '-'))} — {escape(str(selected_member_detail.get('next_of_kin_phone') or '-'))}")
                st.markdown(f"**Notes:** {escape(str(selected_member_detail.get('notes') or '-'))}")

            if st.button("Edit Member Profile", key=f"edit_toggle_{member_key}"):
                st.session_state[edit_flag_key] = True
                st.experimental_rerun()

        else:
            # Existing full-edit form (chairperson)
            with st.form("chairperson_member_profile_form"):
                col1, col2 = st.columns(2)
                with col1:
                    full_name = st.text_input("Full name", value=str(selected_member_detail.get("full_name") or ""), key="chairperson_full_name")
                    email = st.text_input("Email", value=str(selected_member_detail.get("email") or ""), key="chairperson_email")
                    phone = st.text_input("Phone", value=str(selected_member_detail.get("phone") or ""), key="chairperson_phone")
                    date_of_birth_value = st.date_input(
                        "Date of birth",
                        value=_normalize_join_date(selected_member_detail.get("date_of_birth")) or date.today(),
                        key="chairperson_date_of_birth",
                    )
                    gender = st.text_input("Gender", value=str(selected_member_detail.get("gender") or ""), key="chairperson_gender")
                    address = st.text_input("Address", value=str(selected_member_detail.get("address") or ""), key="chairperson_address")
                    city = st.text_input("City", value=str(selected_member_detail.get("city") or ""), key="chairperson_city")
                    country = st.text_input("Country", value=str(selected_member_detail.get("country") or ""), key="chairperson_country")
                    nationality = st.text_input("Nationality", value=str(selected_member_detail.get("nationality") or ""), key="chairperson_nationality")

                with col2:
                    role_options = ["Member", "Secretary", "Treasurer", "Chairperson", "Vice Chairperson", "Welfare"]
                    new_role = st.selectbox(
                        "Role",
                        options=role_options,
                        index=role_options.index(selected_member_detail.get("role")) if selected_member_detail.get("role") in role_options else 0,
                        key="chairperson_role",
                    )
                    status_options = ["Active", "Inactive", "Pending", "Full"]
                    new_status = st.selectbox(
                        "Status",
                        options=status_options,
                        index=status_options.index(selected_member_detail.get("status")) if selected_member_detail.get("status") in status_options else 0,
                        key="chairperson_status",
                    )
                    join_date_value = st.date_input(
                        "Join date",
                        value=_normalize_join_date(selected_member_detail.get("join_date")) or date.today(),
                        key="chairperson_join_date",
                    )
                    occupation = st.text_input("Occupation", value=str(selected_member_detail.get("occupation") or ""), key="chairperson_occupation")
                    employer = st.text_input("Employer", value=str(selected_member_detail.get("employer") or ""), key="chairperson_employer")
                    national_id = st.text_input("National ID", value=str(selected_member_detail.get("national_id") or ""), key="chairperson_national_id")
                    notes = st.text_area("Admin notes", value=str(selected_member_detail.get("notes") or ""), key="chairperson_notes")

                st.markdown("---")
                st.markdown("**Emergency Contact**")
                next_of_kin_name = st.text_input("Next of kin name", value=str(selected_member_detail.get("next_of_kin_name") or ""), key="chairperson_next_of_kin_name")
                next_of_kin_relationship = st.text_input("Next of kin relationship", value=str(selected_member_detail.get("next_of_kin_relationship") or ""), key="chairperson_next_of_kin_relationship")
                next_of_kin_phone = st.text_input("Next of kin phone", value=str(selected_member_detail.get("next_of_kin_phone") or ""), key="chairperson_next_of_kin_phone")
                emergency_contact_name = st.text_input("Emergency contact name", value=str(selected_member_detail.get("emergency_contact_name") or ""), key="chairperson_emergency_contact_name")
                emergency_contact_phone = st.text_input("Emergency contact phone", value=str(selected_member_detail.get("emergency_contact_phone") or ""), key="chairperson_emergency_contact_phone")

                btn_col_a, btn_col_b = st.columns([1, 1])
                with btn_col_a:
                    save_clicked = st.form_submit_button("Save Member Profile")
                with btn_col_b:
                    cancel_clicked = st.button("Cancel Edit", key=f"cancel_edit_{member_key}")

            if cancel_clicked:
                st.session_state[edit_flag_key] = False
                st.experimental_rerun()

            if save_clicked:
                update_member_profile(
                    selected_member_detail["member_id"],
                    full_name.strip(),
                    email.strip(),
                    phone.strip(),
                    new_role,
                    new_status,
                    join_date_value,
                    notes.strip() or None,
                    date_of_birth_value,
                    gender.strip() or None,
                    address.strip() or None,
                    city.strip() or None,
                    country.strip() or None,
                    nationality.strip() or None,
                    occupation.strip() or None,
                    employer.strip() or None,
                    national_id.strip() or None,
                    next_of_kin_name.strip() or None,
                    next_of_kin_relationship.strip() or None,
                    next_of_kin_phone.strip() or None,
                    emergency_contact_name.strip() or None,
                    emergency_contact_phone.strip() or None,
                )
                st.toast("Member profile updated.", icon="✅")
                st.session_state[edit_flag_key] = False
                st.experimental_rerun()

    st.write("---")
    st.subheader("Document Repository")

    if user_role == "Secretary":
        uploaded_file = st.file_uploader("Upload meeting minutes or documents", type=None)
        if uploaded_file is not None:
            title = st.text_input("Document Title", value=uploaded_file.name)
            if st.button("Upload Document"):
                if not title.strip():
                    st.toast("Please provide a title for the document.", icon="⚠️")
                else:
                    file_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{uploaded_file.name}"
                    save_path = os.path.join(UPLOAD_DIR, file_name)
                    with open(save_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    save_document_record(title.strip(), save_path, user_name or "Secretary")
                    st.toast("Document uploaded successfully.", icon="✅")

    documents = fetch_documents()
    if documents:
        for doc in documents:
            title = doc.get("title") or "Untitled"
            file_url = doc.get("file_url") or ""
            uploaded_at = doc.get("uploaded_at")
            uploaded_at_str = uploaded_at.strftime("%Y-%m-%d %H:%M") if hasattr(uploaded_at, "strftime") else str(uploaded_at)
            if os.path.exists(file_url):
                with st.container():
                    st.markdown(f"**{title}**")
                    st.write(f"Uploaded at: {uploaded_at_str}")
                    st.download_button(
                        label="Download",
                        data=open(file_url, "rb").read(),
                        file_name=os.path.basename(file_url),
                        mime="application/octet-stream",
                    )
            else:
                st.markdown(f"- [{title}]({file_url}) — {uploaded_at_str}")
    else:
        st.info("No documents have been uploaded yet.")


if __name__ == "__main__":
    admin_docs_view()
