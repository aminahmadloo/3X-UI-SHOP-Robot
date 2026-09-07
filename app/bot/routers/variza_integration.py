from __future__ import annotations

from aiogram.types import InlineKeyboardButton

from app.bot.payment_gateways.variza_gateway import VarizaGateway
from app.bot.routers.subscription import managed_payment_compat_handler, payment_handler
from app.bot.routers.subscription.keyboard import pay_keyboard as base_pay_keyboard


def _pay_keyboard_with_variza(pay_url: str, callback_data):
    markup = base_pay_keyboard(pay_url=pay_url, callback_data=callback_data)
    if "abangateway.ir" not in (pay_url or "").lower() or not VarizaGateway.is_available():
        return markup

    buttons = markup.inline_keyboard
    if buttons and buttons[0] and buttons[0][0].url:
        buttons[0][0].text = "💳 پرداخت با درگاه آبان گیت"

    plan_id = int(getattr(callback_data, "plan_id", 0) or 0)
    if plan_id > 0 and not any(
        button.callback_data == f"variza:pay:{plan_id}"
        for row in buttons
        for button in row
    ):
        buttons.insert(
            1 if buttons else 0,
            [InlineKeyboardButton(
                text="💳 پرداخت با درگاه واریزا",
                callback_data=f"variza:pay:{plan_id}",
            )],
        )
    return markup


def install() -> None:
    # Customer-facing integration only: add Variza below the existing Aban action.
    # Admin navigation is owned by payment_gateway_settings_handler so Aban and Variza
    # remain separate entry points under Settings -> Payment gateways.
    managed_payment_compat_handler.pay_keyboard = _pay_keyboard_with_variza
    payment_handler.pay_keyboard = _pay_keyboard_with_variza
