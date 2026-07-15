import streamlit as st
from streamlit.testing.v1 import AppTest

from app import build_navigation_sections


def test_home_page_can_run_from_navigation_page_object():
    st.session_state.clear()
    st.session_state["logged_in"] = True
    st.session_state["user_id"] = "MEM-001"
    st.session_state["user_name"] = "Test User"
    st.session_state["user_role"] = "Member"

    pages = build_navigation_sections("Member")
    home_page = next((page for page in pages if getattr(page, "title", None) == "Home"), None)

    assert home_page is not None

    def run_selected_page():
        home_page.run()

    app_test = AppTest.from_function(run_selected_page)
    app_test.run()

    assert not app_test.exception
