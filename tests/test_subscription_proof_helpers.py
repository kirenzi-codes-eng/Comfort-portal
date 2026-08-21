import io
from datetime import date

from src.views.subscriptions import (
    PROOF_STATUS_VERIFIED,
    get_member_monthly_subscription_total,
    get_subscription_proof_access_role,
    update_subscription_proof_verification,
    validate_subscription_proof_upload,
)


def test_access_role_detection_for_member_treasurer_and_chairperson():
    assert get_subscription_proof_access_role("Member") == "member"
    assert get_subscription_proof_access_role("Treasurer") == "treasurer"
    assert get_subscription_proof_access_role("Chairperson") == "chairperson"
    assert get_subscription_proof_access_role("Secretary") == "restricted"


def test_validate_subscription_proof_upload_rejects_unsupported_type_and_large_files():
    invalid_type = io.BytesIO(b"not-a-proof")
    invalid_type.name = "receipt.exe"
    ok, message = validate_subscription_proof_upload(invalid_type, max_bytes=1024 * 1024)
    assert ok is False
    assert "supported" in message.lower()

    oversized = io.BytesIO(b"a" * 2048)
    oversized.name = "receipt.png"
    ok, message = validate_subscription_proof_upload(oversized, max_bytes=10)
    assert ok is False
    assert "larger" in message.lower()


def test_monthly_subscription_total_includes_all_dates_in_month(monkeypatch):
    monkeypatch.setattr("src.views.subscriptions._ensure_subscription_proof_table", lambda: None)

    queries = []

    def fake_execute_query(query, params=None, fetch=False):
        queries.append((query, params, fetch))
        if "FROM subscriptions" in query:
            return [{"total_paid": 20000.0}]
        return [{"total_pending": 0.0}]

    monkeypatch.setattr("src.views.subscriptions.execute_query", fake_execute_query)

    assert get_member_monthly_subscription_total("M1", 2, 2026) == 20000.0
    assert queries[0][1] == ("M1", date(2026, 2, 1), date(2026, 3, 1))


def test_verifying_proof_posts_subscription_for_selected_month(monkeypatch):
    monkeypatch.setattr("src.views.subscriptions._ensure_subscription_proof_table", lambda: None)
    monkeypatch.setattr("src.views.subscriptions.record_audit_event", lambda **kwargs: None)
    monkeypatch.setattr("src.views.subscriptions.create_notification", lambda **kwargs: None)
    monkeypatch.setattr("src.views.subscriptions.check_and_update_member_status", lambda member_id: None)

    queries = []

    def fake_execute_query(query, params=None, fetch=False):
        queries.append((query, params, fetch))
        if "SELECT member_id, subscription_month" in query:
            return [{
                "member_id": "M1",
                "subscription_month": 8,
                "subscription_year": 2026,
                "amount_paid": 20000.0,
                "verification_status": "Pending Verification",
            }]
        return None

    monkeypatch.setattr("src.views.subscriptions.execute_query", fake_execute_query)

    assert update_subscription_proof_verification(7, "Treasurer", PROOF_STATUS_VERIFIED) is True
    insert_call = next(call for call in queries if "INSERT INTO subscriptions" in call[0])
    assert insert_call[1][0:3] == ("M1", date(2026, 8, 1), 20000.0)
