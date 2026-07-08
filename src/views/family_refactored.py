from datetime import datetime
from html import escape

import streamlit as st

from src.database.connection import execute_query


def _inject_family_css() -> None:
    st.markdown(
        """
        <style>
            :root { color-scheme: light; }
            .stApp { background: linear-gradient(180deg, #f8fbff 0%, #f6f8fc 100%); }
            .block-container {
                max-width: 1200px;
                padding-top: 1rem;
                padding-bottom: 2rem;
            }

            body, .stApp {
                font-family: "Inter", "Plus Jakarta Sans", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }

            .family-shell { padding: 0.25rem 0 0.6rem; }
            .hero-block {
                margin-bottom: 1rem;
                padding: 1.1rem 1.2rem;
                border-radius: 22px;
                background: rgba(255,255,255,0.92);
                border: 1px solid rgba(148,163,184,0.18);
                box-shadow: 0 14px 40px rgba(15,23,42,0.05);
            }
            .hero-title {
                margin: 0;
                font-size: clamp(1.45rem, 2.2vw, 2rem);
                font-weight: 800;
                color: #0f172a;
                letter-spacing: -0.02em;
            }
            .hero-caption {
                margin: 0.25rem 0 0;
                font-size: 0.95rem;
                color: #64748b;
                line-height: 1.55;
            }
            .meta-card {
                height: 100%;
                border-radius: 16px;
                background: linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%);
                border: 1px solid rgba(99,102,241,0.12);
                padding: 0.9rem 1rem;
                box-shadow: inset 0 1px 0 rgba(255,255,255,0.6);
            }
            .meta-label {
                display: block;
                font-size: 0.72rem;
                font-weight: 700;
                color: #6366f1;
                text-transform: uppercase;
                letter-spacing: 0.08em;
                margin-bottom: 0.2rem;
            }
            .meta-value {
                font-size: 0.95rem;
                font-weight: 700;
                color: #111827;
                line-height: 1.4;
                word-break: break-word;
            }
            .state-banner {
                display: flex;
                flex-direction: column;
                gap: 0.35rem;
                padding: 0.95rem 1rem;
                border-radius: 18px;
                margin-bottom: 1rem;
                border: 1px solid rgba(148,163,184,0.16);
                box-shadow: 0 12px 30px rgba(15,23,42,0.05);
            }
            .state-banner.locked { background: linear-gradient(135deg, #f8fafc 0%, #fef3c7 100%); color: #4b5563; }
            .state-banner.unlocked { background: linear-gradient(135deg, #f0fdf4 0%, #ecfeff 100%); color: #166534; }
            .state-banner-title {
                font-size: 1rem;
                font-weight: 800;
                display: flex;
                align-items: center;
                gap: 0.45rem;
            }
            .state-banner-copy { font-size: 0.87rem; opacity: 0.95; line-height: 1.5; }
            .registry-card {
                background: white;
                border: 1px solid rgba(148,163,184,0.18);
                border-radius: 16px;
                padding: 1rem;
                box-shadow: 0 16px 40px rgba(15,23,42,0.04);
                margin-bottom: 0.9rem;
            }
            .registry-card-head {
                display: flex;
                justify-content: space-between;
                gap: 0.55rem;
                align-items: flex-start;
                margin-bottom: 0.8rem;
            }
            .registry-role {
                font-size: 0.8rem;
                font-weight: 800;
                letter-spacing: 0.09em;
                text-transform: uppercase;
                color: #111827;
            }
            .status-pill {
                display: inline-flex;
                align-items: center;
                gap: 0.38rem;
                padding: 0.35rem 0.65rem;
                border-radius: 999px;
                font-size: 0.75rem;
                font-weight: 700;
            }
            .status-pill.alive { background: #ecfdf3; color: #047857; }
            .status-pill.deceased { background: #fef2f2; color: #b91c1c; }
            .registry-grid {
                display: grid;
                grid-template-columns: repeat(2, minmax(0, 1fr));
                gap: 0.65rem;
            }
            .metric-block {
                background: #f8fafc;
                border-radius: 12px;
                padding: 0.65rem 0.75rem;
            }
            .metric-label {
                display: block;
                font-size: 0.7rem;
                font-weight: 700;
                color: #64748b;
                text-transform: uppercase;
                letter-spacing: 0.06em;
                margin-bottom: 0.25rem;
            }
            .metric-value {
                display: block;
                font-size: 0.92rem;
                font-weight: 700;
                color: #111827;
                line-height: 1.45;
                word-break: break-word;
            }
            .form-card {
                margin-bottom: 0.9rem;
                padding: 0.95rem 1rem;
                border-radius: 18px;
                background: white;
                border: 1px solid rgba(148,163,184,0.16);
                box-shadow: 0 14px 38px rgba(15,23,42,0.04);
            }
            .form-card-title {
                font-size: 1rem;
                font-weight: 800;
                color: #0f172a;
                margin-bottom: 0.8rem;
            }
            .form-card .stTextInput > div > div > input,
            .form-card .stSelectbox > div > div > select {
                border-radius: 12px;
                border: 1px solid #dbe2ea;
                background: #f8fafc;
                padding: 0.72rem 0.85rem;
                min-height: 48px;
                color: #111827;
            }
            .form-card .stTextInput > div > div > input:focus,
            .form-card .stSelectbox > div > div > select:focus {
                border-color: #6366f1;
                box-shadow: 0 0 0 3px rgba(99,102,241,0.16);
            }
            .accent-btn button {
                background: linear-gradient(135deg, #4f46e5 0%, #4338ca 100%);
                color: white;
                border: none;
                border-radius: 999px;
                padding: 0.7rem 1.2rem;
                font-weight: 700;
                box-shadow: 0 12px 28px rgba(79,70,229,0.22);
            }
            .accent-btn button:hover { filter: brightness(1.02); }

            @media (max-width: 768px) {
                .block-container { padding-left: 0.65rem; padding-right: 0.65rem; }
                .hero-block { padding: 1rem; border-radius: 16px; }
                .registry-grid { grid-template-columns: 1fr; }
                .state-banner { padding: 0.85rem 0.9rem; }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _build_family_records_query() -> str:
    return (
        'SELECT id, relationship_type AS "Relationship", full_legal_name AS "Full Name", '
        'primary_contact AS "Contact", vital_status AS "Vital Status" '
        'FROM family_registry WHERE member_id = %s ORDER BY relationship_type, full_legal_name;'
    )


def _ensure_family_registry_schema() -> None:
    create_table_sql = """
    CREATE TABLE IF NOT EXISTS family_registry (
        id BIGSERIAL PRIMARY KEY,
        member_id TEXT NOT NULL,
        relationship_type TEXT,
        full_legal_name TEXT,
        primary_contact TEXT,
        vital_status TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    execute_query(create_table_sql, params=None, fetch=False)

    for column_sql in [
        "ALTER TABLE family_registry ADD COLUMN IF NOT EXISTS member_id TEXT;",
        "ALTER TABLE family_registry ADD COLUMN IF NOT EXISTS relationship_type TEXT;",
        "ALTER TABLE family_registry ADD COLUMN IF NOT EXISTS full_legal_name TEXT;",
        "ALTER TABLE family_registry ADD COLUMN IF NOT EXISTS primary_contact TEXT;",
        "ALTER TABLE family_registry ADD COLUMN IF NOT EXISTS vital_status TEXT;",
        "ALTER TABLE family_registry ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
    ]:
        execute_query(column_sql, params=None, fetch=False)


def _resolve_member_identifier(member_id_value: str | int) -> str | None:
    if isinstance(member_id_value, str) and member_id_value.strip() and not member_id_value.isdigit():
        return member_id_value.strip()

    query = "SELECT member_id FROM members WHERE id = %s OR member_id = %s LIMIT 1;"
    rows = execute_query(query, params=(member_id_value, str(member_id_value)), fetch=True)
    if rows:
        return rows[0].get("member_id")
    return None


def _fetch_family_records(member_id_value: str) -> list[dict]:
    try:
        return execute_query(_build_family_records_query(), params=(member_id_value,), fetch=True) or []
    except Exception as exc:
        st.error(f"Unable to load family registry records: {exc}")
        return []


def _insert_family_records(member_pk_value: str, entries: list[tuple[str, str, str, str]]) -> None:
    if not entries:
        return

    placeholders = []
    params: list = []
    for relationship_type, full_legal_name, primary_contact, vital_status in entries:
        placeholders.append("(%s, %s, %s, %s, %s, %s)")
        params.extend([member_pk_value, relationship_type, full_legal_name, primary_contact, vital_status, datetime.utcnow()])

    multi_insert_sql = (
        "INSERT INTO family_registry (member_id, relationship_type, full_legal_name, primary_contact, vital_status, created_at) VALUES "
        + ", ".join(placeholders)
        + ";"
    )
    execute_query(multi_insert_sql, params=tuple(params), fetch=False)


def _update_family_records(updates: list[tuple[str, str, str, int]]) -> None:
    update_sql = (
        "UPDATE family_registry SET full_legal_name = %s, primary_contact = %s, vital_status = %s WHERE id = %s;"
    )
    for full_name, primary_contact, vital_status, record_id in updates:
        execute_query(update_sql, params=(full_name, primary_contact, vital_status, record_id), fetch=False)


def _render_status_banner(has_records: bool, edit_mode: bool) -> None:
    if edit_mode:
        st.markdown(
            """
            <div class="state-banner unlocked">
                <div class="state-banner-title">🔓 Unlocked Edit Mode</div>
                <div class="state-banner-copy">Submitting the form will lock the registry again.</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    title = "Registry Status: Locked for Editing" if has_records else "Registry Status: Ready for First Submission"
    copy = "Request access from the Chairperson or Welfare team to make changes." if has_records else "Start with a first submission to create the family registry record."
    st.markdown(
        f"""
        <div class="state-banner locked">
            <div class="state-banner-title">🔒 {title}</div>
            <div class="state-banner-copy">{copy}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_read_only_view(records: list[dict]) -> None:
    if not records:
        st.info("No family registry records have been created yet. Switch to the edit workspace to submit the first record set.")
        return

    for record in records:
        relationship = record.get("Relationship") or record.get("relationship_type") or "Unknown"
        name = record.get("Full Name") or record.get("full_legal_name") or "—"
        contact = record.get("Contact") or record.get("primary_contact") or "N/A"
        vital_status = record.get("Vital Status") or record.get("vital_status") or "Alive"
        status_class = "alive" if str(vital_status).strip().lower() == "alive" else "deceased"
        status_label = "Alive" if status_class == "alive" else "Deceased"

        st.markdown(
            f"""
            <div class="registry-card">
                <div class="registry-card-head">
                    <div class="registry-role">{escape(relationship.upper())}</div>
                    <div class="status-pill {status_class}">● {status_label}</div>
                </div>
                <div class="registry-grid">
                    <div class="metric-block">
                        <span class="metric-label">Name</span>
                        <span class="metric-value">{escape(str(name))}</span>
                    </div>
                    <div class="metric-block">
                        <span class="metric-label">Contact</span>
                        <span class="metric-value">{escape(str(contact))}</span>
                    </div>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _render_edit_view(records: list[dict], member_identifier: str, user_role: str) -> None:
    if records:
        if not st.session_state.get("family_registry_edit_mode", False):
            st.info("The registry is currently locked. Only authorized executives can unlock it for editing.")
            if user_role in ["Chairperson", "Welfare"]:
                unlock_label = st.text_input("Type UNLOCK to permit member edits", key="family_unlock_confirm")
                if st.button("Unlock registry for editing", key="family_unlock_btn"):
                    if unlock_label.strip().upper() == "UNLOCK":
                        st.session_state["family_registry_edit_mode"] = True
                        st.success("Registry unlocked.")
                        st.rerun()
                    else:
                        st.error("Type UNLOCK exactly to continue.")
            return

        with st.form("family_edit_form"):
            update_rows: list[tuple[str, str, str, int]] = []
            for record in records:
                st.markdown(
                    f"""
                    <div class="form-card">
                        <div class="form-card-title">{escape(str(record.get('Relationship') or 'Record'))}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                col1, col2 = st.columns(2)
                with col1:
                    full_name = st.text_input("Full Name", value=record.get("Full Name") or "", key=f"edit_name_{record['id']}")
                with col2:
                    contact = st.text_input("Contact Number", value=record.get("Contact") or "", key=f"edit_contact_{record['id']}")
                vital_status = st.selectbox(
                    "Vital Status",
                    ["Alive", "Deceased"],
                    index=0 if str(record.get("Vital Status") or "Alive").strip().lower() == "alive" else 1,
                    key=f"edit_status_{record['id']}",
                )
                update_rows.append(((full_name or "").strip(), (contact or "").strip() or "N/A", vital_status, record["id"]))

            st.markdown('<div class="accent-btn">', unsafe_allow_html=True)
            submitted = st.form_submit_button("Save registry updates")
            st.markdown('</div>', unsafe_allow_html=True)
            if submitted:
                _update_family_records(update_rows)
                st.session_state["family_registry_edit_mode"] = False
                st.success("Registry updated and locked again.")
                st.rerun()
        return

    with st.form("family_create_form"):
        default_entries = [
            ("Spouse", "Spouse full name", "Spouse contact"),
            ("Father", "Father full name", "Father contact"),
            ("Mother", "Mother full name", "Mother contact"),
            ("Father-in-law", "Father-in-law full name", "Father-in-law contact"),
            ("Mother-in-law", "Mother-in-law full name", "Mother-in-law contact"),
            ("Next of Kin", "Next of Kin full name", "NOK contact"),
        ]

        entry_rows: list[tuple[str, str, str, str]] = []
        for relation, name_label, contact_label in default_entries:
            st.markdown(
                f"""
                <div class="form-card">
                    <div class="form-card-title">{escape(relation)}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            col1, col2 = st.columns(2)
            with col1:
                name_value = st.text_input(name_label, key=f"create_name_{relation.lower().replace(' ', '_')}")
            with col2:
                contact_value = st.text_input(contact_label, key=f"create_contact_{relation.lower().replace(' ', '_')}")
            if name_value and name_value.strip():
                entry_rows.append((relation, name_value.strip(), (contact_value or "").strip() or "N/A", "Alive"))

        st.markdown(
            """
            <div class="form-card">
                <div class="form-card-title">👶 Children</div>
                <p style="margin: 0 0 0.6rem; color: #475569;">You can add up to 8 children. Choose the number below and the matching entry fields will appear.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        children_count = st.number_input(
            "How many children would you like to add? (max 8)",
            min_value=0,
            max_value=8,
            value=0,
            step=1,
            help="Optional — add up to 8 children.",
        )
        if children_count > 0:
            st.caption(f"Child entry fields ready: {int(children_count)}")
        for index in range(int(children_count)):
            st.markdown(
                f"""
                <div class="form-card">
                    <div class="form-card-title">Child {index + 1}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            col1, col2 = st.columns(2)
            with col1:
                child_name = st.text_input(f"Child {index + 1} full name", key=f"child_name_{index}")
            with col2:
                child_contact = st.text_input(f"Child {index + 1} contact", key=f"child_contact_{index}")
            if child_name and child_name.strip():
                entry_rows.append(("Child", child_name.strip(), (child_contact or "").strip() or "N/A", "Alive"))

        st.markdown('<div class="accent-btn">', unsafe_allow_html=True)
        submitted = st.form_submit_button("Submit family registry")
        st.markdown('</div>', unsafe_allow_html=True)
        if submitted:
            if not entry_rows:
                st.error("Add at least one relationship before submitting.")
            else:
                _insert_family_records(member_identifier, entry_rows)
                st.session_state["family_registry_preview_entries"] = [
                    {"Relationship": relationship, "Full Name": full_name, "Contact": contact, "Vital Status": vital_status}
                    for relationship, full_name, contact, vital_status in entry_rows
                ]
                st.success("Family registry submitted successfully.")
                st.rerun()


def family_view() -> None:
    _inject_family_css()

    raw_member = st.session_state.get("member_id") or st.session_state.get("user_id")
    if not raw_member:
        st.warning("Please log in to access the Family Registry Hub.")
        return

    user_role = st.session_state.get("user_role", "Member")
    executive_view_roles = ["Chairperson", "Secretary", "Welfare", "Treasurer", "Vice Chairperson"]
    member_display = st.session_state.get("user_name") or st.session_state.get("member_name") or "Member"

    if user_role in executive_view_roles:
        member_rows = execute_query(
            "SELECT member_id, full_name FROM members ORDER BY full_name;",
            params=None,
            fetch=True,
        ) or []
        member_options = [f"{row.get('full_name') or 'Unnamed'} ({row.get('member_id')})" for row in member_rows]
        member_map = {f"{row.get('full_name') or 'Unnamed'} ({row.get('member_id')})": row.get('member_id') for row in member_rows}
        if member_options:
            selected_label = st.selectbox("Select member to view family tree", options=member_options, key="family_member_selector")
            raw_member = member_map.get(selected_label, raw_member)
            member_display = selected_label or member_display

    st.markdown("<div class='family-shell'>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class="hero-block">
            <h1 class="hero-title">Family Registry Hub</h1>
            <p class="hero-caption">Review household relationships and emergency contacts in a calm, polished workspace designed for both desktop and mobile.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    selector_col, meta_col = st.columns([1.4, 0.8])
    with selector_col:
        member_identifier = _resolve_member_identifier(raw_member)
        if member_identifier is None:
            st.error("This member profile could not be resolved.")
            return
        st.markdown(
            f"""
            <div class="meta-card">
                <span class="meta-label">Member</span>
                <div class="meta-value">{escape(member_display)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with meta_col:
        st.markdown(
            f"""
            <div class="meta-card">
                <span class="meta-label">Member ID</span>
                <div class="meta-value">{escape(member_identifier)}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    try:
        _ensure_family_registry_schema()
    except Exception as exc:
        st.warning(f"Schema initialization could not be completed: {exc}")

    records = _fetch_family_records(member_identifier)
    has_records = bool(records)
    edit_mode = st.session_state.get("family_registry_edit_mode", False)
    _render_status_banner(has_records, edit_mode)

    tabs = st.tabs(["👁️ View Family Registry", "📝 Modify Registry Records"])
    with tabs[0]:
        _render_read_only_view(records)
    with tabs[1]:
        _render_edit_view(records, member_identifier, user_role)

    st.markdown("</div>", unsafe_allow_html=True)


if __name__ == "__main__":
    family_view()
