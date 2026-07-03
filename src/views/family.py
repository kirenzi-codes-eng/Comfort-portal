import pandas as pd
from datetime import datetime

import streamlit as st

from src.database.connection import execute_query


def _render_professional_styles() -> None:
    """Render comprehensive professional CSS styles for the family registry."""
    st.markdown("""
        <style>
            * {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Roboto', 'Oxygen', 'Ubuntu', 'Cantarell', sans-serif;
            }
            
            /* ========== PROFESSIONAL HEADER BANNER ========== */
            .registry-banner {
                background: linear-gradient(135deg, #0F172A 0%, #1E3A8A 100%);
                color: white;
                padding: 2rem 2.5rem;
                border-radius: 8px;
                margin-bottom: 2rem;
                box-shadow: 0 10px 30px rgba(15, 23, 42, 0.3);
            }
            
            .registry-banner h1 {
                margin: 0;
                font-size: 2.25rem;
                font-weight: 700;
                letter-spacing: -0.5px;
                color: white;
            }
            
            .registry-banner p {
                margin: 0.5rem 0 0 0;
                font-size: 1rem;
                opacity: 0.95;
                color: #e0e7ff;
            }
            
            /* ========== REGISTRY PANEL CARDS ========== */
            .registry-panel-card {
                background: white;
                border: 1px solid #E2E8F0;
                border-radius: 8px;
                padding: 1.75rem;
                margin-bottom: 1.5rem;
                box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
                transition: all 0.3s ease;
            }
            
            .registry-panel-card:hover {
                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
                border-color: #CBD5E1;
            }
            
            .registry-panel-card h3 {
                margin: 0 0 1.5rem 0;
                font-size: 1.1rem;
                font-weight: 600;
                color: #0F172A;
                border-bottom: 2px solid #1E3A8A;
                padding-bottom: 0.75rem;
                letter-spacing: 0.3px;
            }
            
            /* ========== FORM LAYOUT ========== */
            .form-row {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 1.5rem;
                margin-bottom: 1.25rem;
            }
            
            .form-group {
                display: flex;
                flex-direction: column;
            }
            
            .form-label {
                font-size: 0.85rem;
                font-weight: 600;
                color: #475569;
                margin-bottom: 0.5rem;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            
            .form-label.required::after {
                content: ' *';
                color: #e11d48;
                font-weight: 700;
            }
            
            /* ========== TABLE STYLES ========== */
            .family-table-container {
                background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
                border-radius: 12px;
                padding: 1.5rem;
                margin: 1.5rem 0;
                box-shadow: 0 8px 16px rgba(0, 0, 0, 0.1);
            }
            
            .family-table {
                width: 100%;
                border-collapse: collapse;
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            }
            
            .family-table thead {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                font-weight: 600;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            
            .family-table th {
                padding: 1rem 1.25rem;
                text-align: left;
                border-bottom: 3px solid #667eea;
                font-size: 0.9rem;
            }
            
            .family-table tbody tr {
                background: white;
                border-bottom: 1px solid #e0e6ed;
                transition: all 0.3s ease;
            }
            
            .family-table tbody tr:hover {
                background: linear-gradient(90deg, #f0f4ff 0%, #ffffff 100%);
                box-shadow: inset 0 2px 4px rgba(102, 126, 234, 0.1);
                transform: translateX(2px);
            }
            
            .family-table tbody tr:nth-child(even) {
                background: #f9fafb;
            }
            
            .family-table tbody tr:nth-child(even):hover {
                background: linear-gradient(90deg, #f0f4ff 0%, #f9fafb 100%);
            }
            
            .family-table td {
                padding: 1rem 1.25rem;
                font-size: 0.95rem;
                color: #2d3748;
            }
            
            .relationship-badge {
                display: inline-block;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 0.4rem 0.8rem;
                border-radius: 20px;
                font-weight: 600;
                font-size: 0.85rem;
                min-width: 90px;
                text-align: center;
            }
            
            .status-alive {
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
                color: white;
                padding: 0.5rem 1rem;
                border-radius: 20px;
                font-weight: 600;
                font-size: 0.85rem;
                box-shadow: 0 4px 8px rgba(17, 153, 142, 0.3);
            }
            
            .status-deceased {
                display: inline-flex;
                align-items: center;
                gap: 0.5rem;
                background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%);
                color: white;
                padding: 0.5rem 1rem;
                border-radius: 20px;
                font-weight: 600;
                font-size: 0.85rem;
                box-shadow: 0 4px 8px rgba(235, 51, 73, 0.3);
            }
            
            .contact-info {
                color: #667eea;
                font-weight: 500;
                font-family: 'Courier New', monospace;
            }
            
            .name-cell {
                color: #2d3748;
                font-weight: 600;
                font-size: 0.96rem;
            }
            
            /* ========== INFO BOX ========== */
            .registry-info-box {
                background: linear-gradient(135deg, #fef3c7 0%, #fde68a 100%);
                border-left: 4px solid #f59e0b;
                padding: 1rem 1.25rem;
                border-radius: 6px;
                margin-bottom: 1.5rem;
                font-size: 0.95rem;
                color: #92400e;
                line-height: 1.5;
            }
            
            /* ========== BUTTON STYLING ========== */
            .submit-button {
                background: linear-gradient(135deg, #1E3A8A 0%, #0F172A 100%);
                color: white;
                padding: 0.75rem 2rem;
                border-radius: 6px;
                font-weight: 600;
                font-size: 0.95rem;
                border: none;
                cursor: pointer;
                transition: all 0.3s ease;
                margin-top: 1.5rem;
            }
            
            .submit-button:hover {
                box-shadow: 0 8px 16px rgba(15, 23, 42, 0.3);
                transform: translateY(-2px);
            }
            
            /* ========== MOBILE RESPONSIVENESS (< 768px) ========== */
            @media (max-width: 768px) {
                .registry-banner {
                    padding: 1.5rem 1.25rem;
                }
                
                .registry-banner h1 {
                    font-size: 1.75rem;
                }
                
                .registry-banner p {
                    font-size: 0.9rem;
                }
                
                .registry-panel-card {
                    padding: 1.25rem;
                    margin-bottom: 1rem;
                }
                
                .registry-panel-card h3 {
                    font-size: 1rem;
                    margin-bottom: 1rem;
                    padding-bottom: 0.5rem;
                }
                
                .form-row {
                    grid-template-columns: 1fr;
                    gap: 1rem;
                    margin-bottom: 1rem;
                }
                
                .form-label {
                    font-size: 0.8rem;
                    margin-bottom: 0.4rem;
                }
                
                input[type="text"],
                input[type="number"],
                select {
                    font-size: 16px !important;
                    padding: 0.6rem !important;
                }
                
                .family-table {
                    font-size: 0.85rem;
                }
                
                .family-table th,
                .family-table td {
                    padding: 0.75rem 0.5rem !important;
                }
                
                .relationship-badge,
                .status-alive,
                .status-deceased {
                    font-size: 0.75rem;
                    padding: 0.35rem 0.6rem;
                }
                
                .registry-info-box {
                    padding: 0.75rem 1rem;
                    font-size: 0.85rem;
                    margin-bottom: 1rem;
                }
            }
            
            /* ========== TABLET RESPONSIVENESS (768px - 1024px) ========== */
            @media (max-width: 1024px) and (min-width: 769px) {
                .form-row {
                    grid-template-columns: 1fr;
                }
                
                .registry-banner h1 {
                    font-size: 1.85rem;
                }
            }
        </style>
    """, unsafe_allow_html=True)


def _render_styled_family_table(records: list[dict]) -> None:
    """Render a beautifully styled HTML table for family records."""
    _render_professional_styles()
    
    if not records:
        st.info("No family records found.")
        return
    
    # Build HTML table
    html_rows = ""
    for record in records:
        relationship = record.get("Relationship", "")
        name = record.get("Full Name", "")
        contact = record.get("Contact", "N/A")
        vital_status = record.get("Vital Status", "Alive")
        
        # Status badge styling
        if vital_status == "Alive":
            status_html = f'<div class="status-alive">🟢 Alive</div>'
        else:
            status_html = f'<div class="status-deceased">⚫ Deceased</div>'
        
        html_rows += f"""
        <tr>
            <td><div class="relationship-badge">{relationship}</div></td>
            <td><div class="name-cell">{name}</div></td>
            <td><div class="contact-info">{contact}</div></td>
            <td>{status_html}</td>
        </tr>
        """
    
    html_table = f"""
    <div class="family-table-container">
        <table class="family-table">
            <thead>
                <tr>
                    <th>Relationship</th>
                    <th>Full Name</th>
                    <th>Contact</th>
                    <th>Vital Status</th>
                </tr>
            </thead>
            <tbody>
                {html_rows}
            </tbody>
        </table>
    </div>
    """
    
    st.markdown(html_table, unsafe_allow_html=True)


def family_view() -> None:
    raw_member = st.session_state.get("member_id") or st.session_state.get("user_id")
    if not raw_member:
        st.warning("Please log in to access the Family Tree & Family Registry.")
        return

    user_role = st.session_state.get("user_role", "Member")
    allowed_vitals_managers = ["Chairperson", "Welfare"]

    # Render professional styles
    _render_professional_styles()
    
    # Render professional banner header
    st.markdown("""
        <div class="registry-banner">
            <h1>Family Tree & Family Registry</h1>
            <p>Manage your family relationships, emergency contacts, and vital status records</p>
        </div>
    """, unsafe_allow_html=True)

    def resolve_member_pk(member_id_value: str | int) -> int | None:
        if isinstance(member_id_value, int):
            return member_id_value
        if isinstance(member_id_value, str) and member_id_value.isdigit():
            return int(member_id_value)
        query = "SELECT id FROM members WHERE member_id = %s LIMIT 1;"
        rows = execute_query(query, params=(member_id_value,), fetch=True)
        if rows:
            return rows[0].get("id")
        return None

    member_pk = resolve_member_pk(raw_member)
    if member_pk is None:
        st.error("Your member profile could not be resolved to an active numeric member ID. Please contact support.")
        return

    def fetch_family_records(member_pk_value: int) -> list[dict]:
        query = (
            "SELECT id, relationship_type AS Relationship, full_legal_name AS \"Full Name\", primary_contact AS Contact, vital_status AS \"Vital Status\" "
            "FROM family_registry WHERE member_id = %s ORDER BY relationship_type, full_legal_name;"
        )
        try:
            return execute_query(query, params=(member_pk_value,), fetch=True) or []
        except Exception as exc:
            st.error("Unable to load family registry records at this time.")
            return []

    def insert_family_records(member_pk_value: int, entries: list[tuple[str, str, str, str]]) -> None:
        insert_sql = (
            "INSERT INTO family_registry (member_id, relationship_type, full_legal_name, primary_contact, vital_status, created_at) "
            "VALUES (%s, %s, %s, %s, %s, %s);"
        )
        for relationship_type, full_legal_name, primary_contact, vital_status in entries:
            execute_query(
                insert_sql,
                params=(member_pk_value, relationship_type, full_legal_name, primary_contact, vital_status, datetime.utcnow()),
                fetch=False,
            )

    records = fetch_family_records(member_pk)
    has_records = len(records) > 0

    # =====================================================================
    # VIEW A: FRESH INITIAL SUBMISSION WORKSPACE (UNLOCKED)
    # =====================================================================
    if not has_records:
        st.markdown("""
            <div class="registry-info-box">
                <strong>📋 Registry Information:</strong><br>
                Please fill out your complete family tree records below. Verify all information carefully before submission—once saved, modifications require executive review from Chairperson or Welfare Officer.
            </div>
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
                submit_family = st.form_submit_button("🔒 Securely Commit Family Registry", use_container_width=True)

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
                            insert_family_records(member_pk, entries)
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

        st.markdown("### 📋 Your Registered Family Members")
        _render_styled_family_table(records)

        # =====================================================================
        # VIEW C: EXECUTIVE RECONCILIATION CONTROL (CHAIRPERSON & WELFARE DESKS ONLY)
        # =====================================================================
        if user_role in allowed_vitals_managers:
            st.markdown("<br><hr>", unsafe_allow_html=True)
            st.markdown("""
                <div style="margin-top: 2rem; padding-top: 2rem; border-top: 2px solid #E2E8F0;">
                    <div class="registry-panel-card">
                        <h3>🛡️ Executive Management Panel</h3>
            """, unsafe_allow_html=True)
            
            st.caption(f"🔐 {user_role} Clearance — Review relative profiles and update vital status flags")

            target_relative = st.selectbox("Select Target Relative to Update", [r["Full Name"] for r in records], key="target_relative")
            new_vital_status = st.radio("Update Vital Status Flag", ["🟢 Alive", "⚫ Deceased"], horizontal=True, key="vital_status")

            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("💾 Apply Status Registry Update", use_container_width=True, key="apply_update"):
                    clean_status = "Alive" if "Alive" in new_vital_status else "Deceased"
                    try:
                        update_sql = "UPDATE family_registry SET vital_status = %s WHERE member_id = %s AND full_legal_name = %s;"
                        execute_query(update_sql, params=(clean_status, member_pk, target_relative), fetch=False)
                        st.success(f"✅ '{target_relative}' status updated to **{clean_status}** by {user_role}.")
                    except Exception as exc:
                        st.error(f"❌ Update failed: {exc}")
            
            st.markdown("</div></div>", unsafe_allow_html=True)
