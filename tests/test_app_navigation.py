import streamlit as st
from streamlit.testing.v1 import AppTest
from unittest.mock import MagicMock, patch

from app import build_menu, build_navigation_sections
from src.views.subscriptions import chairperson_monitor_view


def test_home_page_can_run_from_navigation_page_object():
    st.session_state.clear()
    st.session_state["logged_in"] = True
    st.session_state["user_id"] = "MEM-001"
    st.session_state["user_name"] = "Test User"
    st.session_state["user_role"] = "Member"

    pages = build_navigation_sections("Member")
    home_page = next((page for page in pages if getattr(page, "title", None) == "Home"), None)

    assert home_page is not None
    assert not any(getattr(page, "title", None) == "Group Chat" for page in pages)

    def run_selected_page():
        home_page.run()

    app_test = AppTest.from_function(run_selected_page)
    app_test.run()

    assert not app_test.exception


def test_subscription_monitor_is_visible_only_to_chairperson_secretary_and_treasurer():
    for role in ("Chairperson", "Secretary", "Treasurer"):
        menu = build_menu(role)
        visible_titles = {
            entry["title"]
            for entries in menu.values()
            for entry in entries
        }
        assert "Subscription Monitor" in visible_titles

    for role in ("Member", "Vice Chairperson", "Welfare"):
        menu = build_menu(role)
        visible_titles = {
            entry["title"]
            for entries in menu.values()
            for entry in entries
        }
        assert "Subscription Monitor" not in visible_titles


def test_subscription_monitor_renders_selected_members_activity_timeline_for_secretary():
    mock_streamlit = MagicMock()
    mock_streamlit.session_state = {"user_role": "Secretary"}
    mock_streamlit.columns.return_value = (MagicMock(), MagicMock())
    mock_streamlit.selectbox.return_value = "Sample Member (MEM-001)"
    events = [{"title": "Recent payment"}]

    with patch("src.views.subscriptions.st", mock_streamlit), patch(
        "src.views.subscriptions.render_subscriptions_styles"
    ), patch(
        "src.views.subscriptions.fetch_subscription_summary",
        return_value={"members_with_payments": 1, "total_paid": 1000},
    ), patch(
        "src.views.subscriptions.fetch_recent_subscriptions", return_value=[]
    ), patch(
        "src.views.subscriptions.render_chairperson_proof_audit"
    ), patch(
        "src.views.subscriptions.fetch_all_members",
        return_value=[("MEM-001", "Sample Member")],
    ), patch(
        "src.views.home.get_member_activity_timeline", return_value=events
    ) as get_timeline, patch(
        "src.views.home.render_member_activity_timeline"
    ) as render_timeline, patch(
        "src.views.subscriptions.member_view"
    ) as render_member:
        chairperson_monitor_view()

    get_timeline.assert_called_once_with("MEM-001", limit=6)
    render_timeline.assert_called_once_with(events)
    render_member.assert_called_once_with(
        "MEM-001", show_proof_section=False, user_role="Secretary"
    )
