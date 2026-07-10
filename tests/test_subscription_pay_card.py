from src.views.subscriptions import render_pay_subscription_card_html


def test_pay_subscription_card_contains_expected_ussd_and_message():
    html = render_pay_subscription_card_html()

    assert "Pay Monthly Subscription" in html
    assert "💳 Pay Subscription" in html
    assert "tel:*165*3*09390032%23" in html
    assert "Mobile Money prompts" in html
