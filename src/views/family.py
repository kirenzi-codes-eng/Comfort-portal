import pandas as pd
from datetime import datetime

import streamlit as st

from src.database.connection import execute_query


def _build_family_records_query() -> str:
    """Build the family records query with PostgreSQL-safe quoted aliases."""
    return (
        'SELECT id, relationship_type AS "Relationship", full_legal_name AS "Full Name", '
        'primary_contact AS "Contact", vital_status AS "Vital Status" '
        'FROM family_registry WHERE member_id = %s ORDER BY relationship_type, full_legal_name;'
    )


def _render_professional_styles() -> None:
    """Render compact responsive CSS styles for the family registry."""
    st.markdown("""
        <style>
            * {
                font-family: 'Inter', sans-serif;
            }

            .registry-banner {
                background: linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%);
                color: #166534;
                padding: 12px 14px;
                border-radius: 12px;
                margin-bottom: 10px;
                box-shadow: 0 8px 24px rgba(22, 101, 52, 0.12);
                border: 1px solid #86efac;
            }

            .registry-banner h1 {
                margin: 0;
                font-size: 1.25rem;
                font-weight: 800;
                letter-spacing: -0.02em;
                color: #15803d;
            }

            .registry-banner p {
                margin: 4px 0 0 0;
                font-size: 0.8rem;
                color: #166534;
            }

            .registry-panel-card {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 12px;
                padding: 12px;
                margin-bottom: 10px;
                box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
            }

            .registry-panel-card h3 {
                margin: 0 0 8px 0;
                font-size: 0.95rem;
                font-weight: 700;
                color: #0f172a;
                padding-bottom: 0.4rem;
            }

            .form-label {
                font-size: 0.75rem;
                font-weight: 700;
                color: #64748b;
                margin-bottom: 0.3rem;
                text-transform: uppercase;
                letter-spacing: 0.06em;
            }

            .form-label.required::after {
                content: ' *';
                color: #dc3545;
                font-weight: 700;
            }

            .family-table-container {
                background: #ffffff;
                border-radius: 12px;
                padding: 0.5rem;
                margin: 0.5rem 0 0.8rem;
                box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
                border: 1px solid #e5e7eb;
                overflow-x: auto;
            }

            .family-table {
                width: 100%;
                border-collapse: collapse;
                font-size: 0.75rem;
            }

            .family-table thead {
                background: #f8f9fa;
                color: #0f172a;
                font-weight: 700;
            }

            .family-table th,
            .family-table td {
                padding: 0.45rem 0.5rem;
                text-align: left;
                border-bottom: 1px solid #e5e7eb;
            }

            .relationship-badge {
                display: inline-block;
                background: #f8f9fa;
                color: #2563eb;
                padding: 0.2rem 0.55rem;
                border-radius: 999px;
                font-weight: 700;
                font-size: 0.72rem;
                min-width: 80px;
                text-align: center;
            }

            .status-alive {
                display: inline-flex;
                align-items: center;
                gap: 0.3rem;
                background: #eafaf0;
                color: #28a745;
                padding: 0.2rem 0.55rem;
                border-radius: 999px;
                font-weight: 700;
                font-size: 0.72rem;
            }

            .status-deceased {
                display: inline-flex;
                align-items: center;
                gap: 0.3rem;
                background: #fdecee;
                color: #dc3545;
                padding: 0.2rem 0.55rem;
                border-radius: 999px;
                font-weight: 700;
                font-size: 0.72rem;
            }

            .registry-info-box {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-left: 3px solid #2563eb;
                padding: 10px 12px;
                border-radius: 10px;
                margin-bottom: 10px;
                font-size: 0.8rem;
                color: #334155;
                line-height: 1.45;
                box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
            }

            .registry-print-sheet {
                background: #ffffff;
                border: 1px solid #e5e7eb;
                border-radius: 14px;
                padding: 14px 16px;
                margin: 0.7rem 0 0.9rem;
                box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
            }

            .registry-print-header {
                border-bottom: 1px solid #e5e7eb;
                padding-bottom: 8px;
                margin-bottom: 8px;
            }

            .registry-print-header h3 {
                margin: 0 0 4px 0;
                color: #0f172a;
                font-size: 1rem;
            }

            .registry-print-meta {
                font-size: 0.8rem;
                color: #64748b;
                margin-bottom: 8px;
            }

            .registry-print-row {
                display: flex;
                justify-content: space-between;
                gap: 0.5rem;
                padding: 6px 0;
                border-bottom: 1px solid #f1f5f9;
                font-size: 0.84rem;
            }

            .registry-print-label {
                font-weight: 700;
                color: #334155;
                min-width: 120px;
            }

            .registry-print-value {
                color: #0f172a;
                text-align: right;
                flex: 1;
            }

            @media only screen and (max-width: 768px) {
                .registry-banner {
                    padding: 10px 12px;
                }

                .registry-panel-card {
                    padding: 10px;
                }

                .family-table th,
                .family-table td {
                    padding: 0.35rem 0.4rem !important;
                }
            }
        </style>
    """, unsafe_allow_html=True)


def _render_styled_family_table(records: list[dict]) -> None:
    """Render family records as vertically labeled cards in the requested order."""
    _render_professional_styles()

    if not records:
        st.info("No family records found.")
        return

    html_rows = ""
    for record in records:
        relationship = record.get("Relationship") or record.get("relationship_type") or ""
        name = record.get("Full Name") or record.get("full_legal_name") or ""
        contact = record.get("Contact") or record.get("primary_contact") or "N/A"
        vital_status = record.get("Vital Status") or record.get("vital_status") or "Alive"

        if str(vital_status).strip().lower() == "alive":
            status_html = '<div class="status-alive">🟢 Alive</div>'
        else:
            status_html = '<div class="status-deceased">⚫ Deceased</div>'

        html_rows += f"""
        <div class="registry-panel-card">
            <div class="registry-print-row">
                <div class="registry-print-label">NAME</div>
                <div class="registry-print-value">{name}</div>
            </div>
            <div class="registry-print-row">
                <div class="registry-print-label">CONTACT</div>
                <div class="registry-print-value">{contact}</div>
            </div>
            <div class="registry-print-row">
                <div class="registry-print-label">RELATIONSHIP</div>
                <div class="registry-print-value"><div class="relationship-badge">{relationship}</div></div>
            </div>
            <div class="registry-print-row">
                <div class="registry-print-label">STATUS</div>
                <div class="registry-print-value">{status_html}</div>
            </div>
        </div>
        """

    html_table = f"""
    <div class="family-table-container">
        {html_rows}
    </div>
    """

    st.markdown(html_table, unsafe_allow_html=True)


def _render_printable_family_sheet(records: list[dict], title: str = "Family Registry Summary") -> None:
    """Render a simple, readable family registry summary for members and admins."""
    _render_professional_styles()

    if not records:
        st.info("No family records available to print yet.")
        return

    member_name = st.session_state.get("user_name") or st.session_state.get("member_name") or "Member"
    generated_on = datetime.utcnow().strftime("%d %b %Y")

    st.markdown(f"### {title}")
    st.caption(f"Prepared for {member_name} • Generated on {generated_on}")

    for record in records:
        relationship = record.get("Relationship") or record.get("relationship_type") or ""
        name = record.get("Full Name") or record.get("full_legal_name") or ""
        contact = record.get("Contact") or record.get("primary_contact") or "N/A"
        vital_status = record.get("Vital Status") or record.get("vital_status") or "Alive"

        with st.container():
            st.write(f"**{relationship.upper()}**")
            st.write(f"Name: {name}")
            st.write(f"Contact: {contact}")
            st.write(f"Status: {vital_status}")
            st.write("")


def _ensure_family_registry_schema() -> None:
    """Create the family_registry table and required columns when missing."""
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


def family_view() -> None:
    raw_member = st.session_state.get("member_id") or st.session_state.get("user_id")
    if not raw_member:
        st.warning("Please log in to access the Family Tree & Family Registry.")
        return

    user_role = st.session_state.get("user_role", "Member")
    allowed_vitals_managers = ["Chairperson", "Welfare"]
    executive_view_roles = ["Chairperson", "Secretary", "Welfare", "Treasurer", "Vice Chairperson"]

    if user_role in executive_view_roles:
        member_rows = execute_query(
            "SELECT member_id, full_name FROM members ORDER BY full_name;",
            params=None,
            fetch=True,
        ) or []
        member_options = [f"{r.get('full_name') or 'Unnamed'} ({r.get('member_id')})" for r in member_rows]
        member_map = {f"{r.get('full_name') or 'Unnamed'} ({r.get('member_id')})": r.get('member_id') for r in member_rows}
        if member_options:
            selected_member_label = st.selectbox(
                "Select member to view family tree",
                options=member_options,
                key="family_tree_member_select",
            )
            raw_member = member_map.get(selected_member_label, raw_member)

    # Render professional styles
    _render_professional_styles()
    
    # Render professional banner header
    st.markdown("""
        <div class="registry-banner">
            <h1>Family Tree & Family Registry</h1>
            <p>Manage your family relationships, emergency contacts, and vital status records</p>
        </div>
    """, unsafe_allow_html=True)

    def resolve_member_identifier(member_id_value: str | int) -> str | None:
        if isinstance(member_id_value, str) and member_id_value.strip() and not member_id_value.isdigit():
            return member_id_value.strip()

        query = "SELECT member_id FROM members WHERE id = %s OR member_id = %s LIMIT 1;"
        rows = execute_query(query, params=(member_id_value, str(member_id_value)), fetch=True)
        if rows:
            return rows[0].get("member_id")
        return None

    member_identifier = resolve_member_identifier(raw_member)
    if member_identifier is None:
        st.error("Your member profile could not be resolved to an active member identifier. Please contact support.")
        return

    try:
        _ensure_family_registry_schema()
    except Exception:
        st.warning("The family registry schema could not be initialized automatically. Please contact support if records fail to load.")

    def fetch_family_records(member_id_value: str) -> list[dict]:
        query = _build_family_records_query()
        try:
            return execute_query(query, params=(member_id_value,), fetch=True) or []
        except Exception:
            st.error("Unable to load family registry records at this time.")
            return []

    def insert_family_records(member_pk_value: str, entries: list[tuple[str, str, str, str]]) -> None:
        insert_sql = (
            "INSERT INTO family_registry (member_id, relationship_type, full_legal_name, primary_contact, vital_status, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s);"
        )
        # Perform bulk insert in a single query to avoid per-row roundtrips.
        if not entries:
            return
        # Build a multi-row VALUES clause with parameter placeholders
        values_placeholders = []
        params: list = []
        for relationship_type, full_legal_name, primary_contact, vital_status in entries:
            values_placeholders.append("(%s, %s, %s, %s, %s, %s)")
            params.extend([member_pk_value, relationship_type, full_legal_name, primary_contact, vital_status, datetime.utcnow()])

        multi_insert_sql = (
            "INSERT INTO family_registry (member_id, relationship_type, full_legal_name, primary_contact, vital_status, created_at) VALUES "
            + ", ".join(values_placeholders)
            + ";"
        )
        execute_query(multi_insert_sql, params=tuple(params), fetch=False)

    def update_family_records(updates: list[tuple[str, str, str, int]]) -> None:
        update_sql = (
            "UPDATE family_registry SET full_legal_name = %s, primary_contact = %s, vital_status = %s "
            "WHERE id = %s;"
        )
        for full_name, primary_contact, vital_status, record_id in updates:
            execute_query(update_sql, params=(full_name, primary_contact, vital_status, record_id), fetch=False)

    records = fetch_family_records(member_identifier)
    has_records = len(records) > 0
    edit_mode = st.session_state.get("family_registry_edit_mode", False)

    # =====================================================================
    # VIEW A: FRESH INITIAL SUBMISSION WORKSPACE (UNLOCKED)
    # =====================================================================
    if not has_records:
        preview_records = st.session_state.get("family_registry_preview_entries") or []
        if preview_records:
            st.markdown("<div class='registry-info-box'><strong>✅ Your submitted family registry is ready to view</strong><br>Below is the printable summary of the information you just submitted.</div>", unsafe_allow_html=True)
            _render_printable_family_sheet(preview_records, title="Submitted Family Registry Sheet")
            st.markdown("<div class='registry-info-box'><strong>Note:</strong> Use your browser's print option to print this sheet for your records.</div>", unsafe_allow_html=True)

        st.markdown("""
            <div class="registry-info-box">
                    <strong>Registry Information</strong><br>
        """, unsafe_allow_html=True)

        # Define a small rerun helper (used by the children selector)
        def _rerun_on_children_change():
            rerun = getattr(st, "experimental_rerun", None)
            if callable(rerun):
                rerun()

        with st.form("family_entry_form"):
            # ========== SPOUSE CORE PROFILE INFORMATION =========="
            st.markdown("""
                <div class="registry-panel-card">
                    <h3>💍 Spouse Core Profile Information</h3>
            """, unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
            with col1:
                spouse_name = st.text_input("Spouse Full Name", key="spouse_name", placeholder="Enter spouse's legal name")
            with col2:
                spouse_tel = st.text_input("Spouse Phone Contact", key="spouse_tel", placeholder="e.g., +256700000000")
            
            st.markdown("</div>", unsafe_allow_html=True)
            
            # ========== DIRECT PARENTS LINEAGE RECORDS ==========
            st.markdown("""
                <div class="registry-panel-card">
                    <h3>👨‍👩 Direct Parents Lineage Records</h3>
            """, unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown('<div class="form-label">Father Information</div>', unsafe_allow_html=True)
                father_name = st.text_input("Father Full Name", key="father_name", placeholder="Enter father's legal name")
                father_tel = st.text_input("Father Phone Contact", key="father_tel", placeholder="e.g., +256700000000")
            with col2:
                st.markdown('<div class="form-label">Mother Information</div>', unsafe_allow_html=True)
                mother_name = st.text_input("Mother Full Name", key="mother_name", placeholder="Enter mother's legal name")
                mother_tel = st.text_input("Mother Phone Contact", key="mother_tel", placeholder="e.g., +256700000000")
            
            st.markdown("</div>", unsafe_allow_html=True)
            
            # ========== EXTENDED FAMILY IN-LAW RECORDS ==========
            st.markdown("""
                <div class="registry-panel-card">
                    <h3>👪 Extended Family In-Law Records</h3>
            """, unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown('<div class="form-label">Father-in-Law Information</div>', unsafe_allow_html=True)
                f_in_law = st.text_input("Father-in-Law Full Name", key="f_in_law", placeholder="Enter father-in-law's legal name")
                f_in_law_tel = st.text_input("Father-in-Law Phone Contact", key="f_in_law_tel", placeholder="e.g., +256700000000")
            with col2:
                st.markdown('<div class="form-label">Mother-in-Law Information</div>', unsafe_allow_html=True)
                m_in_law = st.text_input("Mother-in-Law Full Name", key="m_in_law", placeholder="Enter mother-in-law's legal name")
                m_in_law_tel = st.text_input("Mother-in-Law Phone Contact", key="m_in_law_tel", placeholder="e.g., +256700000000")
            
            st.markdown("</div>", unsafe_allow_html=True)
            
            # ========== EMERGENCY CONTACT (NOK) ==========
            st.markdown("""
                <div class="registry-panel-card">
                    <h3>🚨 Emergency Contact — Next of Kin (NOK)</h3>
            """, unsafe_allow_html=True)
            
            col1, col2 = st.columns(2)
            with col1:
                st.markdown('<div class="form-label required">NOK Full Name</div>', unsafe_allow_html=True)
                nok = st.text_input("Next of Kin (NOK) Full Name", key="nok", placeholder="Enter NOK legal name (Required)")
            with col2:
                st.markdown('<div class="form-label required">NOK Phone Contact</div>', unsafe_allow_html=True)
                nok_tel = st.text_input("Next of Kin Phone Contact", key="nok_tel", placeholder="e.g., +256700000000 (Required)")
            
            st.markdown("</div>", unsafe_allow_html=True)
            
            # ========== CHILDREN REGISTRY ==========
            st.markdown("""
                <div class="registry-panel-card">
                    <h3>👶 Children Registry</h3>
            """, unsafe_allow_html=True)

            # Children count selector placed outside the form so the layout updates on selection.
            num_children = st.radio(
                "How many children do you have?",
                options=list(range(0, 7)),
                index=1,
                key="num_children_selector",
                horizontal=True,
            )

            # Generate child input groups based on the selector value
            children_data = []
            for i in range(int(num_children)):
                st.markdown(f'<div class="form-label">Child {i+1} Information</div>', unsafe_allow_html=True)
                child_col1, child_col2, child_col3 = st.columns(3)
                with child_col1:
                    child_type = st.selectbox(f"Designation", ["Son", "Daughter"], key=f"child_type_{i}")
                with child_col2:
                    child_name = st.text_input(f"Full Name", key=f"child_name_{i}", placeholder="Child's legal name")
                with child_col3:
                    child_tel = st.text_input(f"Contact (Optional)", key=f"child_tel_{i}", placeholder="Phone number")

                children_data.append((child_type, child_name, child_tel))
            
            st.markdown("</div>", unsafe_allow_html=True)

            col1, col2 = st.columns([1, 1])
            with col1:
                submit_family = st.form_submit_button("🔒 Securely Commit Family Registry", width='stretch')

            if submit_family:
                if not nok or not nok_tel:
                    st.error("❌ Next of Kin (NOK) information is mandatory. Please provide NOK name and phone number.")
                else:
                    valid_inserts = [
                        ("Spouse", spouse_name, spouse_tel),
                        ("Father", father_name, father_tel),
                        ("Mother", mother_name, mother_tel),
                        ("Father-in-law", f_in_law, f_in_law_tel),
                        ("Mother-in-law", m_in_law, m_in_law_tel),
                    ]

                    entries = [
                        (
                            relation,
                            name.strip(),
                            contact.strip() or "N/A",
                            "Alive",
                        )
                        for relation, name, contact in valid_inserts
                        if isinstance(name, str) and name.strip() != ""
                    ]

                    entries.append(("Next of Kin", nok.strip(), nok_tel.strip(), "Alive"))
                    for child_type, child_name, child_tel in children_data:
                        if isinstance(child_name, str) and child_name.strip() != "":
                            entries.append((child_type, child_name.strip(), child_tel.strip() or "N/A", "Alive"))

                    if not entries:
                        st.error("❌ No valid family entries were provided. Please ensure at least Next of Kin information is filled.")
                    else:
                        try:
                            insert_family_records(member_identifier, entries)
                            st.session_state["family_registry_preview_entries"] = [
                                {
                                    "Relationship": relation,
                                    "Full Name": name,
                                    "Contact": contact,
                                    "Vital Status": vital_status,
                                }
                                for relation, name, contact, vital_status in entries
                            ]
                            st.success("✅ Your family tree records have been securely saved to the registry.")
                            rerun = getattr(st, "experimental_rerun", None)
                            if callable(rerun):
                                rerun()
                        except Exception as exc:
                            st.error(f"❌ Error saving records: {exc}")
    else:
        st.markdown("""
            <div class="registry-info-box" style="background: linear-gradient(135deg, #fee2e2 0%, #fecaca 100%); border-left-color: #dc2626; color: #7f1d1d;">
                <strong>🔒 Registry Status: LOCKED</strong><br>
                Your family registry is locked to maintain institutional data integrity. To modify records, please submit a formal revision request to the Chairperson or Welfare Officer.
            </div>
        """, unsafe_allow_html=True)

        # Use Streamlit header API to avoid raw markdown rendering issues
        st.subheader("Your Registered Family Members")
        _render_printable_family_sheet(records, title="Registered Family Registry Sheet")

        if user_role in ["Chairperson", "Welfare"]:
            st.markdown("<br><hr>", unsafe_allow_html=True)
            st.markdown("""
                <div style="margin-top: 0.8rem; padding-top: 0.8rem; border-top: 1px solid #e5e7eb;">
                    <div class="registry-panel-card">
                        <h3>Executive Management Panel</h3>
            """, unsafe_allow_html=True)

            st.caption(f"🔐 {user_role} Clearance — Review relative profiles and unlock the family registry for member edits")

            unlock_label = st.text_input(
                "Type UNLOCK below to confirm that this family registry may be unlocked for editing:",
                key="unlock_registry_confirmation",
            )

            unlock_ready = unlock_label.strip().upper() == "UNLOCK"
            if unlock_ready:
                st.success("Unlock confirmation accepted. The registry will now be editable by the member.")

            if st.button("🔓 Unlock Family Registry for Editing", width='stretch', key="unlock_registry"):
                if not unlock_ready:
                    st.error("Type UNLOCK exactly in the confirmation field before unlocking.")
                else:
                    st.session_state["family_registry_edit_mode"] = True
                    st.success("✅ Family registry unlocked for member edits. The member can now revise the existing entries and resubmit.")
                    rerun = getattr(st, "experimental_rerun", None)
                    if callable(rerun):
                        rerun()

            st.markdown("</div></div>", unsafe_allow_html=True)

        if st.session_state.get("family_registry_edit_mode", False):
            st.markdown("<br><div class='registry-panel-card'><h3>Unlocked Edit Mode</h3><p>The member may now edit the existing family registry entries below. Submitting the form will lock the registry again.</p></div>", unsafe_allow_html=True)

            with st.form("family_edit_form"):
                update_rows = []
                for idx, record in enumerate(records):
                    st.markdown(f"<div class='registry-panel-card'><h4>{record['Relationship']}</h4>", unsafe_allow_html=True)
                    full_name = st.text_input(
                        f"Full Name for {record['Relationship']}",
                        value=record["Full Name"],
                        key=f"edit_full_name_{record['id']}",
                    )
                    contact = st.text_input(
                        f"Contact for {record['Relationship']}",
                        value=record["Contact"],
                        key=f"edit_contact_{record['id']}",
                    )
                    vital_status = st.selectbox(
                        f"Vital Status for {record['Relationship']}",
                        ["Alive", "Deceased"],
                        index=0 if record["Vital Status"] == "Alive" else 1,
                        key=f"edit_vital_status_{record['id']}",
                    )
                    st.markdown("</div>", unsafe_allow_html=True)
                    update_rows.append(((full_name or "").strip(), (contact or "").strip() or "N/A", vital_status, record["id"]))

                save_updates = st.form_submit_button("💾 Save Updated Family Registry and Re-lock", width='stretch')
                if save_updates:
                    try:
                        update_family_records(update_rows)
                        st.session_state["family_registry_edit_mode"] = False
                        st.success("✅ Family registry updated and re-locked successfully.")
                        rerun = getattr(st, "experimental_rerun", None)
                        if callable(rerun):
                            rerun()
                    except Exception as exc:
                        st.error(f"❌ Unable to save updated family registry: {exc}")

        elif user_role in allowed_vitals_managers:
            st.markdown("<br><hr>", unsafe_allow_html=True)
            st.markdown("""
                <div style="margin-top: 0.8rem; padding-top: 0.8rem; border-top: 1px solid #e5e7eb;">
                    <div class="registry-panel-card">
                        <h3>Executive Management Panel</h3>
            """, unsafe_allow_html=True)

            st.caption(f"🔐 {user_role} Clearance — Review relative profiles and update vital status flags")

            target_relative = st.selectbox("Select Target Relative to Update", [r["Full Name"] for r in records], key="target_relative")
            new_vital_status = st.radio("Update Vital Status Flag", ["🟢 Alive", "⚫ Deceased"], horizontal=True, key="vital_status")

            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("💾 Apply Status Registry Update", width='stretch', key="apply_update"):
                    clean_status = "Alive" if "Alive" in new_vital_status else "Deceased"
                    try:
                        update_sql = "UPDATE family_registry SET vital_status = %s WHERE member_id = %s AND full_legal_name = %s;"
                        execute_query(update_sql, params=(clean_status, member_identifier, target_relative), fetch=False)
                        st.success("✅ Vital status updated successfully.")
                    except Exception as exc:
                        st.error(f"❌ Unable to update vital status: {exc}")
            st.markdown("</div></div>", unsafe_allow_html=True)
