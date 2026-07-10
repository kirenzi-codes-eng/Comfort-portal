import io

from src.views.subscriptions import (
    get_subscription_proof_access_role,
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
