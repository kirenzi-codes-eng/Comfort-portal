from src.components.auth import (
    ALLOWED_LOGIN_STATUSES,
    can_login_with_membership_status,
    canonicalize_membership_status,
    get_membership_login_block_message,
)


def test_pending_members_cannot_sign_in():
    assert can_login_with_membership_status("Pending") is False
    assert get_membership_login_block_message("Pending") == (
        "Your membership application is still under review. Please wait for approval by the SACCO administration."
    )


def test_allowed_statuses_remain_accessible():
    for status in ["Probation", "Probationary", "Partial Member", "Full Member"]:
        assert can_login_with_membership_status(status) is True
        assert canonicalize_membership_status(status) in ALLOWED_LOGIN_STATUSES


def test_restricted_statuses_are_blocked_with_targeted_messages():
    for status, message in [
        ("Rejected", "Your membership application was not approved. Please contact the SACCO office for assistance."),
        ("Suspended", "Your account has been suspended. Please contact the SACCO administration."),
        ("Terminated", "Your membership has been terminated. Access to this account is no longer available."),
    ]:
        assert can_login_with_membership_status(status) is False
        assert get_membership_login_block_message(status) == message
