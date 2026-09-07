from __future__ import annotations

import os
import secrets

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
from app.db.models import PaymentMethodSettings, User, WalletTopupAmount


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


def _zarinpal_enabled() -> bool:
    return os.getenv("SHOP_PAYMENT_ZARINPAL_ENABLED", "").strip().lower() in {
        "1", "true", "yes", "on"
    }


async def _zarinpal_visible(session: AsyncSession) -> bool:
    """Return the admin-configured customer visibility for ZarinPal.

    The admin payment-method screen stores visibility in PaymentMethodSettings;
    the environment flag alone is not the source of truth for customer display.
    """
    method = await PaymentMethodSettings.get_by_key(session, "pay_zarinpal")
    return bool(method and method.enabled and _zarinpal_enabled())


def _renewal_payment_methods_keyboard(
    subscription_id: int,
    plan_id: int,
    price: int,
    gateway_factory,
    *,
    zarinpal_visible: bool,
) -> InlineKeyboardMarkup:
    """Renewal payment methods with admin-controlled ZarinPal visibility."""
    rows: list[list[InlineKeyboardButton]] = []

    for gateway in gateway_factory.get_gateways():
        if gateway.callback == "pay_aban":
            continue
        if gateway.callback == "pay_zarinpal" and not zarinpal_visible:
            continue
        rows.append([InlineKeyboardButton(
            text=f"🏦 {gateway.name} | {price:,} تومان",
            callback_data=f"{renew_service_handler.GATEWAY_PREFIX}{subscription_id}:{plan_id}:{gateway.callback}",
        )])

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


def _wallet_payment_methods_keyboard(
    language: str,
    amount: int,
    *,
    zarinpal_visible: bool,
) -> InlineKeyboardMarkup:
    """Wallet method screen; visibility follows the admin payment-method setting."""
    if language == "en":
        gateway_label, card_label, back = "🏦 Bank gateway", "💳 Card-to-card", "🔙 Back"
    elif language == "ru":
        gateway_label, card_label, back = "🏦 Банковский шлюз", "💳 Перевод с карты на карту", "🔙 Назад"
    else:
        gateway_label, card_label, back = "🏦 درگاه بانکی", "💳 کارت به کارت", "🔙 بازگشت"

    rows: list[list[InlineKeyboardButton]] = []

    if zarinpal_visible:
        rows.append([InlineKeyboardButton(
            text=gateway_label,
            callback_data=f"wallet:method:gateway:{amount}",
        )])

    if _aban_configured() or VarizaGateway.is_available():
        rows.append([InlineKeyboardButton(
            text=card_label,
            callback_data=f"wallet:card:choice:{amount}",
        )])

    rows.append([InlineKeyboardButton(text=back, callback_data=NavMain.WALLET)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _wallet_card_gateway_choice(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 4:
        await callback.answer("❌ درخواست پرداخت نامعتبر است.", show_alert=True)
        return

    amount = int(parts[3])
    if amount <= 0:
        await callback.answer("❌ مبلغ شارژ معتبر نیست.", show_alert=True)
        return

    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است.", show_alert=True)
        return

    rows: list[list[InlineKeyboardButton]] = []
    if _aban_configured():
        rows.append([InlineKeyboardButton(
            text="💳 پرداخت با درگاه آبان گیت",
            callback_data=f"wallet:method:gateway:{amount}:pay_aban",
        )])
    if VarizaGateway.is_available():
        rows.append([InlineKeyboardButton(
            text="💳 پرداخت با درگاه واریزا",
            callback_data=f"wallet:method:gateway:{amount}:pay_variza",
        )])
    rows.append([InlineKeyboardButton(text="🔙 بازگشت به روش‌های پرداخت", callback_data=NavMain.WALLET)])

    await callback.answer()
    await callback.message.edit_text(
        "💳 <b>انتخاب درگاه پرداخت کارت به کارت هوشمند</b>\n\n"
        f"💰 مبلغ شارژ: <b>{amount:,} تومان</b>\n\n"
        "لطفاً یکی از درگاه‌های کارت به کارت را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


def _wallet_variza_invoice_text(data: SubscriptionData, slug: str) -> str:
    tracking_code = VarizaGateway.tracking_code_for_order(data)
    return (
        "💳 <b>فاکتور کارت به کارت هوشمند واریزا</b>\n"
        "━━━━━━━━━━━━━━━\n"
        "نوع پرداخت: <b>شارژ کیف پول</b>\n"
        f"کد پیگیری: <code>{tracking_code}</code>\n"
        f"شماره فاکتور واریزا: <code>{slug}</code>\n"
        f"مبلغ شارژ: <code>{data.price:,.0f}</code> تومان\n"
        "مبلغ قابل واریز: <b>دقیقاً مطابق مبلغ نمایش‌داده‌شده در صفحه واریزا</b>\n"
        "مهلت پرداخت: <b>طبق زمان اعلام‌شده در صفحه واریزا</b>\n"
        "━━━━━━━━━━━━━━━\n\n"
        "⚠️ <b>مهم:</b> مبلغ قابل پرداخت را <b>دقیقاً همان‌طور که در صفحه واریزا نمایش داده می‌شود</b> وارد کنید.\n"
        "در صورت واریز مبلغ متفاوت، تطبیق و تأیید خودکار پرداخت ممکن است انجام نشود.\n\n"
        "برای پرداخت، روی دکمه <b>«💳 پرداخت»</b> بزنید.\n"
        "پس از تأیید واریزا، مبلغ به‌صورت خودکار به کیف پول شما اضافه می‌شود."
    )


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

    state_data = await state.get_data()
    nonce = str(state_data.get("wallet_variza_nonce") or "").strip()
    if not nonce:
        nonce = secrets.token_urlsafe(12)
        await state.update_data(wallet_variza_nonce=nonce)

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
        config_name=f"wallet_topup:{nonce}",
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
        _wallet_variza_invoice_text(data, slug),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 پرداخت", url=pay_url)],
            [InlineKeyboardButton(text="🔙 تغییر روش پرداخت", callback_data=NavMain.WALLET)],
        ]),
    )


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
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً منتظر بمانید.", show_alert=True)
        return

    await state.clear()
    await state.update_data(card_payment_amount=item.amount)
    visible = await _zarinpal_visible(session)

    await callback.answer()
    await callback.message.edit_text(
        wallet_handler.payment_method_text(user.language_code, item.amount),
        reply_markup=_wallet_payment_methods_keyboard(
            user.language_code,
            item.amount,
            zarinpal_visible=visible,
        ),
    )


def _replace_router_handler(router, callback_name: str, replacement) -> None:
    for handler in router.callback_query.handlers:
        if getattr(handler.callback, "__name__", "") == callback_name:
            handler.callback = replacement
            return
    raise RuntimeError(f"Unable to replace router callback: {callback_name}")


def install() -> None:
    # Existing purchase flow: untouched; this preserves its current Aban + Variza UI.
    managed_payment_compat_handler.pay_keyboard = _pay_keyboard_with_variza
    payment_handler.pay_keyboard = _pay_keyboard_with_variza

    # Renewal: read the persisted admin visibility setting at the moment the
    # payment-method screen is opened. Purchase flow is not touched.
    _replace_router_handler(
        renew_service_handler.router,
        "payment_methods",
        _renewal_payment_methods,
    )

    # Wallet: read the persisted admin visibility setting at the moment the
    # top-up payment-method screen is opened. This avoids relying on stale env state.
    _replace_router_handler(
        wallet_handler.router,
        "callback_wallet_topup",
        _wallet_topup_payment_methods,
    )

    wallet_gateway_payment.router.callback_query(
        F.data.regexp(r"^wallet:card:choice:\d+$")
    )(_wallet_card_gateway_choice)
    wallet_gateway_payment.router.callback_query(
        F.data.regexp(r"^wallet:method:gateway:\d+:pay_variza$")
    )(_wallet_variza_payment)
