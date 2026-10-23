from unittest.mock import Mock, patch

from streamlit.testing.v1 import AppTest


def test_family_registry_renders_selected_child_fields():
    def render_family():
        import streamlit as st
        from src.views import family_refactored as family

        st.session_state["user_id"] = "MEM-001"
        st.session_state["user_role"] = "Member"
        family.family_view()

    execute_query = Mock(return_value=None)
    with patch("src.views.family_refactored.execute_query", side_effect=execute_query):
        app_test = AppTest.from_function(render_family).run()

        assert not app_test.exception
        app_test.number_input(key="family_children_count").set_value(8).run()

        assert not app_test.exception
        child_name_labels = {widget.label for widget in app_test.text_input}
        assert all(f"Child {child_number} full name" in child_name_labels for child_number in range(1, 9))

        for index in range(8):
            app_test.text_input(key=f"child_name_{index}").set_value(f"Child Name {index + 1}")

        app_test.form_submit_button[0].click().run()

    assert not app_test.exception
    insert_call = next(
        call
        for call in execute_query.call_args_list
        if "INSERT INTO family_registry" in call.args[0]
    )
    inserted_values = insert_call.kwargs["params"]
    assert inserted_values.count("Child") == 8
    assert all(f"Child Name {child_number}" in inserted_values for child_number in range(1, 9))


def test_chairperson_can_add_children_to_existing_registry():
    def render_edit_view():
        import streamlit as st
        from src.views import family_refactored as family

        records = [
            {
                "id": 1,
                "Relationship": "Spouse",
                "Full Name": "Existing Relative",
                "Contact": "12345",
                "Vital Status": "Alive",
            }
        ]
        st.session_state["family_registry_edit_mode"] = True
        family._render_edit_view(records, "MEM-001", "Chairperson")

    execute_query = Mock(return_value=None)
    with patch("src.views.family_refactored.execute_query", side_effect=execute_query):
        app_test = AppTest.from_function(render_edit_view).run()

        assert not app_test.exception
        app_test.number_input(key="family_new_children_count").set_value(8).run()

        assert not app_test.exception
        child_name_labels = {widget.label for widget in app_test.text_input}
        assert all(f"Child {child_number} full name" in child_name_labels for child_number in range(1, 9))

        for index in range(8):
            app_test.text_input(key=f"family_new_child_name_{index}").set_value(f"New Child {index + 1}")

        app_test.form_submit_button[0].click().run()

    assert not app_test.exception
    insert_call = next(
        call
        for call in execute_query.call_args_list
        if "INSERT INTO family_registry" in call.args[0]
    )
    inserted_values = insert_call.kwargs["params"]
    assert inserted_values.count("Child") == 8
    assert all(f"New Child {child_number}" in inserted_values for child_number in range(1, 9))
