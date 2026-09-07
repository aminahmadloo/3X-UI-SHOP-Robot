from __future__ import annotations

import os

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.payment_gateways.variza_gateway import VarizaGateway
from app.bot.routers.main_menu import renew_service_handler
from app.bot.routers.subscription import managed_payment_compat_handler, payment_handler
from app.bot.routers.subscription.keyboard import pay_keyboard as base_pay_keyboard
from app.bot.routers.wallet import gateway_payment as wallet_gateway_payment
from app.bot.routers.wallet import handler as wallet_handler
from app.bot.routers.wallet.handler import has_pending_payment
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import User


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


def _aban_configured() -> bool:
    return bool(
        os.getenv("ABAN_GATEWAY_TOKEN", "").strip()
        and os.getenv("ABAN_GATEWAY_WEBHOOK_SECRET", "").strip()
    )


def _renewal_payment_methods_keyboard(
    subscription_id: int,
    plan_id: int,
    price: int,
    gateway_factory,
) -> InlineKeyboardMarkup:
    """Renewal payment methods with the same smart card gateway choice as purchase."""
    rows: list[list[InlineKeyboardButton]] = []

    # Preserve ordinary bank gateways (e.g. ZarinPal) exactly as before.
    for gateway in gateway_factory.get_gateways():
        if gateway.callback == "pay_aban":
            continue
        rows.append([InlineKeyboardButton(
            text=f"🏦 {gateway.name} | {price:,} تومان",
            callback_data=f"{renew_service_handler.GATEWAY_PREFIX}{subscription_id}:{plan_id}:{gateway.callback}",
        )])

    # The smart card-to-card entry intentionally opens the existing purchase
    # gateway selector, which then offers Aban and Variza independently.
    if _aban_configured() or VarizaGateway.is_available():
        rows.append([InlineKeyboardButton(
            text=f"💳 کارت به کارت | {price:,} تومان",
            callback_data=f"mp:pay_aban:{plan_id}",
        )])

    rows.append([InlineKeyboardButton(
        text=f"👛 پرداخت از کیف پول | {price:,} تومان",
        callback_data=f"main_renewal:wallet:{subscription_id}:{plan_id}",
    )])
    rows.append([InlineKeyboardButton(
        text="🔙 تغییر سرویس",
        callback_data=f"{renew_service_handler.SERVICE_CALLBACK_PREFIX}{subscription_id}",
    )])
    rows.append([renew_service_handler._home_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _wallet_payment_methods_keyboard(language: str, amount: int) -> InlineKeyboardMarkup:
    """Wallet payment methods with independent Aban and Variza card-to-card actions."""
    if language == "en":
        gateway_label, back = "🏦 Bank gateway", "🔙 Back"
    elif language == "ru":
        gateway_label, back = "🏦 Банковский шлюз", "🔙 Назад"
    else:
        gateway_label, back = "🏦 درگاه بانکی", "🔙 بازگشت"

    rows: list[list[InlineKeyboardButton]] = []

    if os.getenv("SHOP_PAYMENT_ZARINPAL_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}:
        rows.append([InlineKeyboardButton(
            text=gateway_label,
            callback_data=f"wallet:method:gateway:{amount}:pay_zarinpal",
        )])

    if _aban_configured():
        rows.append([InlineKeyboardButton(
            text="💳 کارت به کارت آبان گیت",
            callback_data=f"wallet:method:gateway:{amount}:pay_aban",
        )])

    if VarizaGateway.is_available():
        rows.append([InlineKeyboardButton(
            text="💳 کارت به کارت واریزا",
            callback_data=f"wallet:method:gateway:{amount}:pay_variza",
        )])

    rows.append([InlineKeyboardButton(text=back, callback_data=NavMain.WALLET)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _wallet_variza_payment(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    variza_gateway: VarizaGateway,
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 5:
        await callback.answer("❌ درخواست پرداخت نامعتبر است.", show_alert=True)
        return

    amount = int(parts[3])
    if amount <= 0 or not VarizaGateway.is_available():
        await callback.answer("❌ درگاه واریزا در حال حاضر فعال نیست.", show_alert=True)
        return

    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است.", show_alert=True)
        return

    data = SubscriptionData(
        state=NavSubscription.CONFIG_NAME,
        is_extend=False,
        is_change=False,
        user_id=user.tg_id,
        devices=0,
        duration=0,
        price=amount,
        plan_id=0,
        volume_gb=0,
        config_name="wallet_topup",
        payment_kind="wallet_topup",
    )

    try:
        pay_url = await variza_gateway.create_payment(data)
    except Exception:
        await callback.answer("❌ ایجاد لینک پرداخت واریزا برای شارژ کیف پول انجام نشد.", show_alert=True)
        return

    slug = pay_url.rstrip("/").rsplit("/", 1)[-1]
    await state.update_data(subscription_data=data.serialize())
    await callback.answer()
    await callback.message.edit_text(
        "💳 <b>شارژ کیف پول با درگاه واریزا</b>\n\n"
        f"💰 مبلغ شارژ: <b>{amount:,} تومان</b>\n"
        f"🔖 شماره فاکتور واریزا: <code>{slug}</code>\n\n"
        "برای تکمیل پرداخت روی دکمه زیر بزنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 پرداخت با واریزا", url=pay_url)],
            [InlineKeyboardButton(text="🔙 تغییر روش پرداخت", callback_data=NavMain.WALLET)],
        ]),
    )


def install() -> None:
    # Existing purchase flow: untouched; this preserves its current Aban + Variza UI.
    managed_payment_compat_handler.pay_keyboard = _pay_keyboard_with_variza
    payment_handler.pay_keyboard = _pay_keyboard_with_variza

    # Renewal: replace only its payment-method keyboard. The card-to-card action
    # enters the exact same gateway-choice flow already used by purchase.
    renew_service_handler._payment_methods_keyboard = _renewal_payment_methods_keyboard

    # Wallet: replace only the method keyboard and add an isolated Variza callback.
    wallet_handler.payment_method_keyboard = _wallet_payment_methods_keyboard
    wallet_gateway_payment.router.callback_query(
        F.data.regexp(r"^wallet:method:gateway:\d+:pay_variza$")
    )(_wallet_variza_payment)
