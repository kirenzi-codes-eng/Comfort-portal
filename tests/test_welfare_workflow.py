from datetime import date, datetime

from src.views import welfare_support
from src.views.welfare_support import (
    WELFARE_REQUEST_STATUS_APPROVED_BY_WELFARE,
    WELFARE_REQUEST_STATUS_APPROVED_BY_CHAIR,
    WELFARE_REQUEST_STATUS_PAID,
    WELFARE_REQUEST_STATUS_SUBMITTED,
    _get_member_row_value,
    _is_suspended_membership_status,
    _is_welfare_contribution_eligible,
    _should_suspend_for_zero_balance,
    can_transition_request,
    get_member_paid_welfare_details,
    validate_welfare_request_payload,
)
from src.views.welfare_support_optimized import (
    _build_announcement_content,
    _map_welfare_payload_errors,
    get_member_paid_welfare_details as get_optimized_member_paid_welfare_details,
)


def test_validate_welfare_request_requires_full_member_and_evidence_for_bereavement():
    errors = validate_welfare_request_payload(
        membership_status="Partial Member",
        support_category="BEREAVEMENT - Spouse",
        relationship="Spouse",
        event_date=date(2026, 1, 10),
        location="Kampala",
        description="",
        uploaded_file=None,
    )

    assert any("Full Member" in error for error in errors)
    assert any("evidence" in error.lower() for error in errors)
    assert any("description" in error.lower() for error in errors)


def test_can_transition_request_prevents_skipping_stages():
    assert can_transition_request(
        WELFARE_REQUEST_STATUS_SUBMITTED,
        WELFARE_REQUEST_STATUS_APPROVED_BY_WELFARE,
        "Welfare",
    )

    assert not can_transition_request(
        WELFARE_REQUEST_STATUS_SUBMITTED,
        WELFARE_REQUEST_STATUS_APPROVED_BY_CHAIR,
        "Chairperson",
    )

    assert not can_transition_request(
        WELFARE_REQUEST_STATUS_APPROVED_BY_WELFARE,
        WELFARE_REQUEST_STATUS_PAID,
        "Treasurer",
    )


def test_get_member_row_value_supports_mapping_and_tuple_rows():
    mapping_row = {"member_id": "M-100", "full_name": "Jane Doe"}
    tuple_row = ("M-101", "John Smith")

    assert _get_member_row_value(mapping_row, "member_id", 0) == "M-100"
    assert _get_member_row_value(mapping_row, "full_name", 1) == "Jane Doe"
    assert _get_member_row_value(tuple_row, "member_id", 0) == "M-101"
    assert _get_member_row_value(tuple_row, "full_name", 1) == "John Smith"


def test_map_welfare_payload_errors_groups_missing_fields_for_form_feedback():
    errors = [
        "Only Full Members can submit a welfare request.",
        "Please provide the relationship to the affected person.",
        "Supporting evidence is required for bereavement or illness requests.",
    ]

    mapped = _map_welfare_payload_errors(errors)

    assert mapped["membership_status"] == ["Only Full Members can submit a welfare request."]
    assert mapped["relationship"] == ["Please provide the relationship to the affected person."]
    assert mapped["evidence_file"] == ["Supporting evidence is required for bereavement or illness requests."]


def test_is_welfare_contribution_eligible_excludes_probationary_members():
    assert _is_welfare_contribution_eligible("Full Member") is True
    assert _is_welfare_contribution_eligible("Partial Member") is True
    assert _is_welfare_contribution_eligible("Probationary") is False
    assert _is_welfare_contribution_eligible("Pending") is True


def test_should_suspend_for_zero_balance_when_deduction_reaches_threshold():
    assert _should_suspend_for_zero_balance(0.0, 20000.0) is True
    assert _should_suspend_for_zero_balance(15000.0, 20000.0) is True
    assert _should_suspend_for_zero_balance(25000.0, 20000.0) is False


def test_is_suspended_membership_status_detects_suspended_accounts():
    assert _is_suspended_membership_status("Suspended") is True
    assert _is_suspended_membership_status("suspended") is True
    assert _is_suspended_membership_status("Full Member") is False


def test_get_member_paid_welfare_details_returns_latest_payment_and_contributions(monkeypatch):
    get_member_paid_welfare_details.clear()

    def fake_execute_query(query, params=None, fetch=False):
        if "FROM welfare_requests" in query:
            return [{
                "id": 7,
                "case_number": "WEL-1001",
                "payment_amount": 20000,
                "payment_reference": "REF-001",
                "payment_date": datetime(2026, 1, 10),
            }]
        if "FROM ledger_transactions" in query:
            return [{
                "member_id": "M-002",
                "member_name": "Jane Doe",
                "contribution_amount": 20000,
            }]
        return []

    monkeypatch.setattr("src.views.welfare_support.execute_query", fake_execute_query)

    details = get_member_paid_welfare_details("M-001")

    assert details["amount_paid"] == 20000.0
    assert details["payment_reference"] == "REF-001"
    assert details["contributions"][0]["member_name"] == "Jane Doe"


def test_optimized_welfare_announcement_is_concise_and_paid_details_helper_matches(monkeypatch):
    get_optimized_member_paid_welfare_details.clear()

    def fake_execute_query(query, params=None, fetch=False):
        if "FROM welfare_requests" in query:
            return [{
                "id": 8,
                "case_number": "WEL-2002",
                "payment_amount": 20000,
                "payment_reference": "REF-002",
                "payment_date": datetime(2026, 2, 10),
            }]
        if "FROM ledger_transactions" in query:
            return [{
                "member_id": "M-003",
                "member_name": "John Doe",
                "contribution_amount": 20000,
            }]
        return []

    monkeypatch.setattr("src.views.welfare_support_optimized.execute_query", fake_execute_query)

    message = _build_announcement_content({"support_category": "ILLNESS - Member", "member_name": "Asha"}, "Paid", "Treasurer")

    assert "Case Number:" not in message
    assert "Reason:" not in message
    assert "Asha" in message
    assert "paid" in message.lower()

    details = get_optimized_member_paid_welfare_details("M-001")
    assert details["amount_paid"] == 20000.0
    assert details["payment_reference"] == "REF-002"
    assert details["contributions"][0]["member_name"] == "John Doe"


def test_set_member_welfare_account_status_updates_status_and_audits(monkeypatch):
    queries = []

    def fake_execute_query(query, params=None, fetch=False):
        queries.append((query, params, fetch))
        if "SELECT" in query.upper() and "member_welfare_accounts" in query.lower():
            return []
        return None

    monkeypatch.setattr(welfare_support, "execute_query", fake_execute_query)
    monkeypatch.setattr(welfare_support, "record_audit_event", lambda **kwargs: None)
    monkeypatch.setattr(welfare_support, "_create_notification", lambda *args, **kwargs: None)

    result = welfare_support.set_member_welfare_account_status("M-002", "Suspended", "Chairperson", "Chairperson", "Rule violation")

    assert result is True
    assert any("UPDATE MEMBER_WELFARE_ACCOUNTS" in (query or "").upper() for query, _, _ in queries)
