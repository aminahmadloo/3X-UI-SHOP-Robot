from __future__ import annotations

from aiogram.types import InlineKeyboardButton

from app.bot.payment_gateways.variza_gateway import VarizaGateway
from app.bot.routers.admin_tools import payment_gateway_settings_handler
from app.bot.routers.subscription import managed_payment_compat_handler, payment_handler
from app.bot.routers.subscription.keyboard import pay_keyboard as base_pay_keyboard
from app.bot.utils.navigation import NavAdminTools


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


_ORIGINAL_ADMIN_MENU = payment_gateway_settings_handler.menu_markup


def _admin_menu_with_variza(settings):
    markup = _ORIGINAL_ADMIN_MENU(settings)
    callback = str(NavAdminTools.PAYMENT_GATEWAY_SETTINGS)
    if not any(
        button.callback_data == "paymentgateway:smart_card"
        for row in markup.inline_keyboard
        for button in row
    ):
        back_index = next(
            (i for i, row in enumerate(markup.inline_keyboard)
             if row and row[0].callback_data == callback),
            len(markup.inline_keyboard),
        )
        markup.inline_keyboard.insert(
            back_index,
            [InlineKeyboardButton(
                text="💳 مدیریت کارت به کارت هوشمند",
                callback_data="paymentgateway:smart_card",
            )],
        )
    return markup


def install() -> None:
    managed_payment_compat_handler.pay_keyboard = _pay_keyboard_with_variza
    payment_handler.pay_keyboard = _pay_keyboard_with_variza
    payment_gateway_settings_handler.menu_markup = _admin_menu_with_variza
