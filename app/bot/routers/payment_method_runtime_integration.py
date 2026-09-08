from __future__ import annotations

import os

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.routers.main_menu import renew_service_handler
from app.bot.routers.wallet import handler as wallet_handler
from app.bot.routers.wallet.handler import has_pending_payment
from app.bot.utils.navigation import NavMain
from app.db.models import PaymentMethodSettings, User, WalletTopupAmount


def _aban_configured() -> bool:
    return bool(
        os.getenv("ABAN_GATEWAY_TOKEN", "").strip()
        and os.getenv("ABAN_GATEWAY_WEBHOOK_SECRET", "").strip()
    )


def _zarinpal_enabled() -> bool:
    return os.getenv("SHOP_PAYMENT_ZARINPAL_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


async def _zarinpal_visible(session: AsyncSession) -> bool:
    method = await PaymentMethodSettings.get_by_key(session, "pay_zarinpal")
    return bool(method and method.enabled and _zarinpal_enabled())


async def _aban_visible(session: AsyncSession) -> bool:
    if not _aban_configured():
        return False
    method = await PaymentMethodSettings.get_by_key(session, "pay_aban")
    return bool(method and method.enabled)


def _renewal_payment_methods_keyboard(
    subscription_id: int,
    plan_id: int,
    price: int,
    gateway_factory,
    *,
    zarinpal_visible: bool,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for gateway in gateway_factory.get_gateways():
        if gateway.callback == "pay_aban":
            continue
        if gateway.callback == "pay_zarinpal" and not zarinpal_visible:
            continue
        rows.append([
            InlineKeyboardButton(
                text=f"🏦 {gateway.name} | {price:,} تومان",
                callback_data=f"{renew_service_handler.GATEWAY_PREFIX}{subscription_id}:{plan_id}:{gateway.callback}",
            )
        ])

    if _aban_configured():
        rows.append([
            InlineKeyboardButton(
                text=f"💳 کارت به کارت | {price:,} تومان",
                callback_data=f"mp:pay_aban:{plan_id}",
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text=f"👛 پرداخت از کیف پول | {price:,} تومان",
            callback_data=f"main_renewal:wallet:{subscription_id}:{plan_id}",
        )
    ])
    rows.append([
        InlineKeyboardButton(
            text="🔙 تغییر سرویس",
            callback_data=f"{renew_service_handler.SERVICE_CALLBACK_PREFIX}{subscription_id}",
        )
    ])
    rows.append([renew_service_handler._home_button()])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _wallet_payment_methods_keyboard(
    language: str,
    amount: int,
    *,
    zarinpal_visible: bool,
    aban_visible: bool,
) -> InlineKeyboardMarkup:
    if language == "en":
        gateway_label, aban_label, back = "🏦 Bank gateway", "💳 Smart card-to-card", "🔙 Back"
    elif language == "ru":
        gateway_label, aban_label, back = "🏦 Банковский шлюз", "💳 Умный перевод с карты на карту", "🔙 Назад"
    else:
        gateway_label, aban_label, back = "🏦 درگاه بانکی", "💳 پرداخت خودکار کارت به کارت", "🔙 بازگشت"

    rows: list[list[InlineKeyboardButton]] = []
    if zarinpal_visible:
        rows.append([
            InlineKeyboardButton(
                text=gateway_label,
                callback_data=f"wallet:method:gateway:{amount}:pay_zarinpal",
            )
        ])
    if aban_visible:
        rows.append([
            InlineKeyboardButton(
                text=aban_label,
                callback_data=f"wallet:method:gateway:{amount}:pay_aban",
            )
        ])
    rows.append([InlineKeyboardButton(text=back, callback_data=NavMain.WALLET)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _renewal_payment_methods(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services,
    state: FSMContext,
    gateway_factory,
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer("❌ درخواست تمدید نامعتبر است.", show_alert=True)
        return

    subscription_id = int(parts[2])
    plan_id = int(parts[3])
    resolved = await renew_service_handler._resolve_renewal_payment_data(
        session, user, subscription_id, plan_id, services
    )
    if resolved is None:
        await callback.answer("❌ سرویس یا پلن اصلی دیگر معتبر نیست.", show_alert=True)
        return

    subscription, plan, data = resolved
    await state.update_data(subscription_data=data.serialize())
    visible = await _zarinpal_visible(session)

    await callback.answer()
    await callback.message.edit_text(
        "💳 <b>انتخاب روش پرداخت تمدید سرویس</b>\n\n"
        f"🟢 <b>سرویس:</b> <code>{subscription.config_name}</code>\n\n"
        f"📦 حجم افزوده: <b>{plan.volume_gb} GB</b>\n"
        f"📅 زمان افزوده: <b>{plan.duration_days} روز</b>\n"
        f"💰 مبلغ: <b>{data.price:,} تومان</b>\n\n"
        "روش پرداخت را انتخاب کنید:",
        reply_markup=_renewal_payment_methods_keyboard(
            subscription.id,
            plan.id,
            int(data.price),
            gateway_factory,
            zarinpal_visible=visible,
        ),
    )


async def _wallet_topup_payment_methods(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    config,
    state: FSMContext,
) -> None:
    amount_id = int((callback.data or "").rsplit(":", 1)[1])
    item = await WalletTopupAmount.get(session, amount_id)
    if not item or not item.is_active:
        await callback.answer("❌ این مبلغ دیگر فعال نیست.", show_alert=True)
        return

    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً ابتدا همان درخواست را تعیین تکلیف کنید.", show_alert=True)
        return

    await state.clear()
    await state.update_data(card_payment_amount=item.amount)
    visible = await _zarinpal_visible(session)
    aban_visible = await _aban_visible(session)

    await callback.answer()
    await callback.message.edit_text(
        wallet_handler.payment_method_text(user.language_code, item.amount),
        reply_markup=_wallet_payment_methods_keyboard(
            user.language_code,
            item.amount,
            zarinpal_visible=visible,
            aban_visible=aban_visible,
        ),
    )


def _replace_router_handler(router, callback_name: str, replacement) -> None:
    for handler in router.callback_query.handlers:
        if getattr(handler.callback, "__name__", "") == callback_name:
            handler.callback = replacement
            return
    raise RuntimeError(f"Unable to replace router callback: {callback_name}")


def install() -> None:
    _replace_router_handler(
        renew_service_handler.router,
        "payment_methods",
        _renewal_payment_methods,
    )
    _replace_router_handler(
        wallet_handler.router,
        "callback_wallet_topup",
        _wallet_topup_payment_methods,
    )


install()
