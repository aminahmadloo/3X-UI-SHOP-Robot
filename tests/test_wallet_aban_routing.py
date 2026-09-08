from app.bot.routers.payment_method_runtime_integration import _wallet_payment_methods_keyboard
from app.bot.utils.navigation import NavMain


def _callback_data(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row]


def test_wallet_topup_uses_aban_gateway_callback_when_aban_is_visible():
    markup = _wallet_payment_methods_keyboard(
        "fa",
        350_000,
        zarinpal_visible=False,
        aban_visible=True,
    )

    callbacks = _callback_data(markup)

    assert "wallet:method:gateway:350000:pay_aban" in callbacks
    assert "wallet:method:card:350000" not in callbacks


def test_wallet_topup_hides_card_to_card_when_aban_is_not_visible():
    markup = _wallet_payment_methods_keyboard(
        "fa",
        350_000,
        zarinpal_visible=False,
        aban_visible=False,
    )

    callbacks = _callback_data(markup)

    assert "wallet:method:card:350000" not in callbacks
    assert NavMain.WALLET in callbacks
