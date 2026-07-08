from src.views.inquiry import _member_label


def test_member_label_prefers_name_and_id() -> None:
    inquiry = {"member_name": "Jane Doe", "member_id": "M-100"}
    assert _member_label(inquiry) == "Jane Doe • M-100"


def test_member_label_falls_back_to_member_id() -> None:
    inquiry = {"member_id": "M-100"}
    assert _member_label(inquiry) == "M-100"
