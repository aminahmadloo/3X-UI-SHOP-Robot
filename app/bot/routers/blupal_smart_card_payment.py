from __future__ import annotations

import html
import logging
import os
import sqlite3
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import ServicesContainer, SubscriptionData
from app.bot.payment_gateways import GatewayFactory
from app.bot.payment_gateways.aban_gateway import AbanGateway
from app.bot.payment_gateways.blupal_gateway import BluPalGateway
from app.bot.routers.main_menu import renew_service_handler
from app.bot.routers.subscription import keyboard as subscription_keyboard
from app.bot.routers.subscription import payment_handler as subscription_payment_handler
from app.bot.routers.subscription import subscription_handler
from app.bot.routers.wallet import handler as wallet_handler
from app.bot.routers.wallet import gateway_payment as wallet_gateway_payment
from app.bot.utils.constants import Currency
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import PaymentMethodSettings, ServicePurchasePlan, User

router = Router(name=__name__)
logger = logging.getLogger(__name__)

SMART_PARENT_KEY = "mp_smart_card"
SMART_ABAN_KEY = "pay_aban"
SMART_BLUPAL_KEY = "pay_blupal"


def _db_enabled(key: str) -> bool:
    name = os.getenv("DB_NAME", "bot_database").strip() or "bot_database"
    path = f"/app/data/{name}.sqlite3"
    try:
        with sqlite3.connect(path, timeout=2) as db:
            row = db.execute(
                "SELECT enabled FROM payment_method_settings WHERE method_key = ?",
                (key,),
            ).fetchone()
        return True if row is None else bool(row[0])
    except (sqlite3.Error, OSError):
        return True


def _gateway_key(gateway: Any) -> str:
    value = getattr(gateway, "callback", "")
    return str(getattr(value, "value", value) or "")


def _smart_gateways(factory: GatewayFactory) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for gateway in factory.get_gateways():
        key = _gateway_key(gateway)
        if key in {SMART_ABAN_KEY, SMART_BLUPAL_KEY} and _db_enabled(key):
            result[key] = gateway
    return result


def _smart_available(factory: GatewayFactory) -> bool:
    return bool(_smart_gateways(factory))


def _smart_methods_keyboard(
    *,
    amount: int,
    choose_callback: str,
    back_callback: str,
    factory: GatewayFactory,
    wallet: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    smart = _smart_gateways(factory)
    if smart:
        builder.row(InlineKeyboardButton(
            text=f"💳 پرداخت کارت به کارت هوشمند | {amount:,} تومان",
            callback_data=choose_callback,
        ))
    if wallet:
        builder.row(InlineKeyboardButton(
            text=f"💰 کیف پول | {amount:,} تومان",
            callback_data=f"mp_wallet:0",
        ))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_callback))
    return builder.as_markup()


def _smart_provider_keyboard(
    *,
    amount: int,
    select_prefix: str,
    back_callback: str,
    factory: GatewayFactory,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    smart = _smart_gateways(factory)
    if SMART_ABAN_KEY in smart:
        builder.row(InlineKeyboardButton(
            text=f"💳 کارت به کارت هوشمند آبان گیت | {amount:,} تومان",
            callback_data=f"{select_prefix}:{SMART_ABAN_KEY}",
        ))
    if SMART_BLUPAL_KEY in smart:
        builder.row(InlineKeyboardButton(
            text=f"💳 کارت به کارت هوشمند بلوپال | {amount:,} تومان",
            callback_data=f"{select_prefix}:{SMART_BLUPAL_KEY}",
        ))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_callback))
    return builder.as_markup()


def _payment_back_keyboard(back_callback: str, home_callback: str = NavMain.MAIN_MENU) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 تغییر درگاه کارت به کارت", callback_data=back_callback)],
        [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=home_callback)],
    ])


def _deserialize_state(value: Any, user_id: int) -> SubscriptionData | None:
    if not value:
        return None
    try:
        data = SubscriptionData.deserialize(value) if isinstance(value, str) else SubscriptionData(**value)
    except Exception:
        return None
    if data.user_id != user_id or data.price <= 0:
        return None
    return data


def _invoice_id(url: str) -> str:
    """
    Extract the provider invoice identifier from a payment URL.

    Invoice identifiers are provider-defined and are not necessarily numeric
    (e.g. AbanGateway uses IDs such as ``inv_...``). Do not impose a numeric
    constraint here; the gateway itself is responsible for validating the ID.
    """
    from urllib.parse import urlparse

    value = (url or "").strip()
    if not value:
        return ""

    parsed = urlparse(value)
    path = parsed.path.rstrip("/")
    invoice_id = path.rsplit("/", 1)[-1].strip() if path else ""

    return invoice_id


def _purchase_top_level(plan, callback_data, gateways, price_override=None):
    builder = InlineKeyboardBuilder()
    price = price_override
    if price is None and plan is not None:
        price = plan.get_price(currency=Currency.TOMAN, duration=callback_data.duration)
    if price is None:
        return builder.as_markup()

    if _smart_available_from_list(gateways):
        builder.row(InlineKeyboardButton(
            text=f"💳 پرداخت کارت به کارت هوشمند | {price:,} تومان",
            callback_data=f"smartcard:choose:subscription:{callback_data.plan_id or 0}",
        ))
    if _enabled_from_list(gateways, "mp_wallet"):
        builder.row(InlineKeyboardButton(
            text=f"💰 کیف پول | {price:,} تومان",
            callback_data=f"mp_wallet:{callback_data.plan_id or 0}",
        ))
    # Preserve configured non-card gateways such as ZarinPal exactly as separate options.
    for gateway in gateways:
        key = _gateway_key(gateway)
        if key in {SMART_ABAN_KEY, SMART_BLUPAL_KEY}:
            continue
        if not _db_enabled(key):
            continue
        if key == "pay_zarinpal":
            gateway_price = price_override if price_override is not None else plan.get_price(currency=gateway.currency, duration=callback_data.duration)
            if gateway_price is not None:
                callback_data.state = NavSubscription.PAY_ZARINPAL
                builder.row(InlineKeyboardButton(
                    text=f"{gateway.name} | {gateway_price:,} {gateway.currency.symbol}",
                    callback_data=callback_data.pack(),
                ))
    callback_data.state = NavSubscription.DEVICES
    builder.row(InlineKeyboardButton(text="🔙 تغییر مدت", callback_data=callback_data.pack()))
    builder.row(InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU))
    return builder.as_markup()


def _enabled_from_list(gateways, key: str) -> bool:
    if key == "mp_wallet":
        return _db_enabled(key)
    return any(_gateway_key(g) == key and _db_enabled(key) for g in gateways)


def _smart_available_from_list(gateways) -> bool:
    return any(_gateway_key(g) in {SMART_ABAN_KEY, SMART_BLUPAL_KEY} and _db_enabled(_gateway_key(g)) for g in gateways)


def _managed_keyboard(plan_id: int, price: int, gateways, back_callback: str):
    builder = InlineKeyboardBuilder()
    if _smart_available_from_list(gateways):
        builder.row(InlineKeyboardButton(
            text=f"💳 پرداخت کارت به کارت هوشمند | {price:,} تومان",
            callback_data=f"smartcard:choose:subscription:{plan_id}",
        ))
    if _enabled_from_list(gateways, "mp_wallet"):
        builder.row(InlineKeyboardButton(text=f"💰 کیف پول | {price:,} تومان", callback_data=f"mp_wallet:{plan_id}"))
    for gateway in gateways:
        key = _gateway_key(gateway)
        if key in {SMART_ABAN_KEY, SMART_BLUPAL_KEY} or not _db_enabled(key):
            continue
        builder.row(InlineKeyboardButton(text=f"{gateway.name} | {price:,} {gateway.currency.symbol}", callback_data=f"mp:{key}:{plan_id}"))
    builder.row(InlineKeyboardButton(text="◀️ نام کانفیگ", callback_data=back_callback))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data=NavMain.MAIN_MENU, style="danger"))
    return builder.as_markup()


def _renewal_keyboard(subscription_id: int, plan_id: int, price: int, factory: GatewayFactory):
    builder = InlineKeyboardBuilder()
    gateways = factory.get_gateways()
    if _smart_available_from_list(gateways):
        builder.row(InlineKeyboardButton(
            text=f"💳 پرداخت کارت به کارت هوشمند | {price:,} تومان",
            callback_data=f"smartcard:choose:renewal:{subscription_id}:{plan_id}",
        ))
    if _enabled_from_list(gateways, "mp_wallet"):
        builder.row(InlineKeyboardButton(text=f"👛 پرداخت از کیف پول | {price:,} تومان", callback_data=f"main_renewal:wallet:{subscription_id}:{plan_id}"))
    for gateway in gateways:
        key = _gateway_key(gateway)
        if key in {SMART_ABAN_KEY, SMART_BLUPAL_KEY} or not _db_enabled(key):
            continue
        builder.row(InlineKeyboardButton(
            text=f"{gateway.name} | {price:,} {gateway.currency.symbol}",
            callback_data=f"{renew_service_handler.GATEWAY_PREFIX}{subscription_id}:{plan_id}:{key}",
        ))
    builder.row(InlineKeyboardButton(text="🔙 تغییر سرویس", callback_data=f"{renew_service_handler.SERVICE_CALLBACK_PREFIX}{subscription_id}"))
    builder.row(renew_service_handler._home_button())
    return builder.as_markup()


def _wallet_keyboard(language: str, amount: int):
    if language == "en":
        smart_label, wallet_back = "💳 Smart card-to-card", "🔙 Back"
    elif language == "ru":
        smart_label, wallet_back = "💳 Умная оплата с карты на карту", "🔙 Назад"
    else:
        smart_label, wallet_back = "💳 پرداخت کارت به کارت هوشمند", "🔙 بازگشت"
    # Wallet gateway callback is handled by this module; provider selection is a second step.
    rows = []
    if _wallet_smart_configured_from_env():
        rows.append([InlineKeyboardButton(text=smart_label, callback_data=f"smartcard:choose:wallet:{amount}")])
    rows.append([InlineKeyboardButton(text=wallet_back, callback_data=NavMain.WALLET)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _wallet_smart_configured_from_env() -> bool:
    return bool(os.getenv("ABAN_GATEWAY_TOKEN", "").strip() and os.getenv("ABAN_GATEWAY_WEBHOOK_SECRET", "").strip()) or bool(os.getenv("BLUPAL_API_KEY", "").strip())


async def _restore_purchase_methods(callback: CallbackQuery, state: FSMContext, factory: GatewayFactory) -> None:
    data = await state.get_data()
    subscription_data = _deserialize_state(data.get("subscription_data"), callback.from_user.id)
    if subscription_data is None:
        await state.clear()
        await callback.answer("❌ اطلاعات سفارش منقضی شده است.", show_alert=True)
        return
    plan = None
    try:
        if subscription_data.plan_id:
            plan = await ServicePurchasePlan.get(session=None, id=subscription_data.plan_id)  # type: ignore[arg-type]
    except Exception:
        plan = None
    # Existing managed keyboard path is safer because it does not require a DB lookup here.
    await callback.answer()
    await callback.message.edit_text(
        "💳 <b>انتخاب روش پرداخت</b>\n\n"
        f"📝 نام کانفیگ: <code>{html.escape(subscription_data.config_name)}</code>\n"
        f"💰 مبلغ قابل پرداخت: <b>{subscription_data.price:,.0f} تومان</b>\n\n"
        "روش پرداخت را انتخاب کنید:",
        reply_markup=_managed_keyboard(
            subscription_data.plan_id,
            int(subscription_data.price),
            factory.get_gateways(),
            f"subscription_back_config_name:{subscription_data.plan_id}",
        ),
    )


@router.callback_query(F.data.regexp(r"^smartcard:choose:subscription:\d+$"))
async def choose_subscription_smart_card(callback: CallbackQuery, state: FSMContext, gateway_factory: GatewayFactory) -> None:
    plan_id = int((callback.data or "").rsplit(":", 1)[1])
    data = await state.get_data()
    subscription_data = _deserialize_state(data.get("subscription_data"), callback.from_user.id)
    if subscription_data is None or subscription_data.plan_id != plan_id:
        await callback.answer("❌ اطلاعات سفارش منقضی یا نامعتبر است.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "💳 <b>درگاه‌های کارت به کارت هوشمند</b>\n\n"
        f"💰 مبلغ سفارش: <b>{subscription_data.price:,.0f} تومان</b>\n\n"
        "درگاه موردنظر را انتخاب کنید:",
        reply_markup=_smart_provider_keyboard(
            amount=int(subscription_data.price),
            select_prefix=f"smartcard:pay:subscription:{plan_id}",
            back_callback=f"smartcard:back:subscription:{plan_id}",
            factory=gateway_factory,
        ),
    )


@router.callback_query(F.data.regexp(r"^smartcard:back:subscription:\d+$"))
async def back_subscription_smart_card(callback: CallbackQuery, state: FSMContext, gateway_factory: GatewayFactory) -> None:
    await _restore_purchase_methods(callback, state, gateway_factory)


@router.callback_query(F.data.regexp(r"^smartcard:pay:subscription:\d+:(?:pay_aban|pay_blupal)$"))
async def pay_subscription_smart_card(callback: CallbackQuery, user: User, state: FSMContext, services: ServicesContainer, gateway_factory: GatewayFactory) -> None:
    parts = (callback.data or "").split(":")
    plan_id = int(parts[3])
    provider = parts[4]
    data = await state.get_data()
    subscription_data = _deserialize_state(data.get("subscription_data"), user.tg_id)
    if subscription_data is None or subscription_data.plan_id != plan_id:
        await callback.answer("❌ اطلاعات سفارش منقضی یا نامعتبر است.", show_alert=True)
        return
    gateway = _smart_gateways(gateway_factory).get(provider)
    if gateway is None:
        await callback.answer("❌ این درگاه در حال حاضر فعال نیست.", show_alert=True)
        return
    try:
        logger.info(
            "SMARTCARD_DIAG create_payment:start flow=purchase provider=%s user=%s",
            provider,
            user.tg_id,
        )
        pay_url = await gateway.create_payment(subscription_data)
        logger.info(
            "SMARTCARD_DIAG create_payment:done flow=purchase provider=%s user=%s pay_url_present=%s",
            provider,
            user.tg_id,
            bool(pay_url),
        )
        invoice_id = _invoice_id(pay_url)
        logger.info(
            "SMARTCARD_DIAG invoice_id provider=%s user=%s invoice_id=%s",
            provider,
            user.tg_id,
            invoice_id or "<empty>",
        )
        if not invoice_id:
            raise RuntimeError("Invalid payment URL")
        if provider == SMART_ABAN_KEY:
            logger.info(
                "SMARTCARD_DIAG get_invoice:start flow=purchase provider=%s user=%s invoice_id=%s",
                provider,
                user.tg_id,
                invoice_id,
            )
            invoice = await gateway._get_invoice(invoice_id)  # type: ignore[attr-defined]
            logger.info(
                "SMARTCARD_DIAG get_invoice:done flow=purchase provider=%s user=%s invoice_id=%s invoice_type=%s",
                provider,
                user.tg_id,
                invoice_id,
                type(invoice).__name__,
            )
            order_id = str(invoice.get("order_id") or invoice_id)
            payable = invoice.get("payable_toman")
            if payable is None:
                payable = subscription_data.price
            text = (
                "💳 <b>فاکتور کارت به کارت هوشمند آبان گیت</b>\n"
                "━━━━━━━━━━━━━━━\n"
                f"کد پیگیری: <code>{html.escape(order_id)}</code>\n"
                f"شماره فاکتور آبان گیت: <code>{html.escape(invoice_id)}</code>\n"
                f"نام کانفیگ: <code>{html.escape(subscription_data.config_name)}</code>\n"
                f"حجم: <code>{subscription_data.volume_gb} گیگ</code>\n"
                f"مدت: <code>{subscription_data.duration} روز</code>\n"
                f"مبلغ سفارش: <code>{subscription_data.price:,.0f}</code> تومان\n"
                f"مبلغ قابل پرداخت: <code>{float(payable):,.0f}</code> تومان\n"
                "━━━━━━━━━━━━━━━\n\n"
                "برای پرداخت روی دکمه «💳 پرداخت» بزنید."
            )
        else:
            logger.info(
                "SMARTCARD_DIAG get_invoice:start flow=purchase provider=%s user=%s invoice_id=%s",
                provider,
                user.tg_id,
                invoice_id,
            )
            invoice = await gateway.get_invoice(invoice_id)  # type: ignore[attr-defined]
            logger.info(
                "SMARTCARD_DIAG get_invoice:done flow=purchase provider=%s user=%s invoice_id=%s invoice_type=%s",
                provider,
                user.tg_id,
                invoice_id,
                type(invoice).__name__,
            )
            final_rial = int(invoice.get("final_amount") or 0)
            final_toman = final_rial / 10
            card_number = str(invoice.get("card_number") or "").strip()
            text = (
                "💳 <b>فاکتور کارت به کارت هوشمند بلوپال</b>\n"
                "━━━━━━━━━━━━━━━\n"
                f"شماره فاکتور: <code>{html.escape(invoice_id)}</code>\n"
                f"نام کانفیگ: <code>{html.escape(subscription_data.config_name)}</code>\n"
                f"مبلغ سفارش: <code>{subscription_data.price:,.0f}</code> تومان\n"
                f"مبلغ نهایی پرداخت: <code>{final_toman:,.0f}</code> تومان\n"
                f"شماره کارت مقصد: <code>{html.escape(card_number or 'طبق صفحه پرداخت بلوپال')}</code>\n"
                "━━━━━━━━━━━━━━━\n\n"
                "مبلغ نهایی را دقیقاً واریز کنید و سپس وضعیت پرداخت به‌صورت خودکار بررسی می‌شود."
            )
        await callback.answer()
        await callback.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="💳 پرداخت", url=pay_url)],
                [InlineKeyboardButton(text="🔙 تغییر درگاه کارت به کارت", callback_data=f"smartcard:choose:subscription:{plan_id}")],
                [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)],
            ]),
        )
    except Exception:
        logger.exception(
            "SMARTCARD_DIAG exception flow=purchase provider=%s user=%s invoice_id=%s",
            provider,
            user.tg_id,
            locals().get("invoice_id", "<not-set>"),
        )
        await callback.answer("❌ ایجاد فاکتور پرداخت انجام نشد. لطفاً درگاه دیگری را انتخاب کنید.", show_alert=True)


@router.callback_query(F.data.regexp(r"^smartcard:choose:renewal:\d+:\d+$"))
async def choose_renewal_smart_card(callback: CallbackQuery, user: User, session: AsyncSession, services: ServicesContainer, gateway_factory: GatewayFactory) -> None:
    _, _, _, subscription_id, plan_id = (callback.data or "").split(":")
    from app.bot.routers.main_menu.renew_service_handler import _resolve_renewal_payment_data
    resolved = await _resolve_renewal_payment_data(session, user, int(subscription_id), int(plan_id), services)
    if resolved is None:
        await callback.answer("❌ سرویس یا پلن اصلی دیگر معتبر نیست.", show_alert=True)
        return
    _, plan, data = resolved
    await callback.answer()
    await callback.message.edit_text(
        "💳 <b>درگاه‌های کارت به کارت هوشمند تمدید سرویس</b>\n\n"
        f"💰 مبلغ: <b>{data.price:,.0f} تومان</b>\n"
        f"📦 حجم افزوده: <b>{plan.volume_gb} GB</b>\n"
        f"📅 زمان افزوده: <b>{plan.duration_days} روز</b>\n\n"
        "درگاه موردنظر را انتخاب کنید:",
        reply_markup=_smart_provider_keyboard(
            amount=int(data.price),
            select_prefix=f"smartcard:pay:renewal:{subscription_id}:{plan_id}",
            back_callback=f"main_renewal:methods:{subscription_id}:{plan_id}",
            factory=gateway_factory,
        ),
    )


@router.callback_query(F.data.regexp(r"^smartcard:pay:renewal:\d+:\d+:(?:pay_aban|pay_blupal)$"))
async def pay_renewal_smart_card(callback: CallbackQuery, user: User, session: AsyncSession, services: ServicesContainer, gateway_factory: GatewayFactory) -> None:
    parts = (callback.data or "").split(":")
    subscription_id, plan_id, provider = int(parts[3]), int(parts[4]), parts[5]
    from app.bot.routers.main_menu.renew_service_handler import _resolve_renewal_payment_data
    resolved = await _resolve_renewal_payment_data(session, user, subscription_id, plan_id, services)
    if resolved is None:
        await callback.answer("❌ سرویس یا پلن اصلی دیگر معتبر نیست.", show_alert=True)
        return
    _, plan, data = resolved
    gateway = _smart_gateways(gateway_factory).get(provider)
    if gateway is None:
        await callback.answer("❌ این درگاه در حال حاضر فعال نیست.", show_alert=True)
        return
    try:
        logger.info(
            "SMARTCARD_DIAG create_payment:start provider=%s user=%s",
            provider,
            user.tg_id,
        )
        pay_url = await gateway.create_payment(data)
        logger.info(
            "SMARTCARD_DIAG create_payment:done provider=%s user=%s pay_url_present=%s",
            provider,
            user.tg_id,
            bool(pay_url),
        )
        invoice_id = _invoice_id(pay_url)
        logger.info(
            "SMARTCARD_DIAG invoice_id provider=%s user=%s invoice_id=%s",
            provider,
            user.tg_id,
            invoice_id or "<empty>",
        )
        logger.info(
            "SMARTCARD_DIAG get_invoice:start provider=%s user=%s invoice_id=%s",
            provider,
            user.tg_id,
            invoice_id or "<empty>",
        )
        invoice = await gateway._get_invoice(invoice_id) if provider == SMART_ABAN_KEY else await gateway.get_invoice(invoice_id)  # type: ignore[attr-defined]
        logger.info(
            "SMARTCARD_DIAG get_invoice:done provider=%s user=%s invoice_id=%s invoice_type=%s",
            provider,
            user.tg_id,
            invoice_id or "<empty>",
            type(invoice).__name__,
        )
        if provider == SMART_ABAN_KEY:
            payable = invoice.get("payable_toman") or data.price
            text = (
                "💳 <b>فاکتور کارت به کارت هوشمند آبان گیت</b>\n\n"
                f"کد پیگیری: <code>{html.escape(str(invoice.get('order_id') or invoice_id))}</code>\n"
                f"مبلغ قابل پرداخت: <code>{float(payable):,.0f}</code> تومان\n"
                f"حجم افزوده: <code>{plan.volume_gb} GB</code>\n"
                f"زمان افزوده: <code>{plan.duration_days} روز</code>"
            )
        else:
            final_toman = int(invoice.get("final_amount") or 0) / 10
            text = (
                "💳 <b>فاکتور کارت به کارت هوشمند بلوپال</b>\n\n"
                f"شماره فاکتور: <code>{invoice_id}</code>\n"
                f"مبلغ نهایی پرداخت: <code>{final_toman:,.0f}</code> تومان\n"
                f"حجم افزوده: <code>{plan.volume_gb} GB</code>\n"
                f"زمان افزوده: <code>{plan.duration_days} روز</code>\n"
                f"شماره کارت مقصد: <code>{html.escape(str(invoice.get('card_number') or 'طبق صفحه پرداخت'))}</code>"
            )
        await callback.answer()
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 پرداخت", url=pay_url)],
            [InlineKeyboardButton(text="🔙 تغییر درگاه کارت به کارت", callback_data=f"smartcard:choose:renewal:{subscription_id}:{plan_id}")],
            [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)],
        ]))
    except Exception:
        logger.exception(
            "SMARTCARD_DIAG exception flow=renewal provider=%s user=%s invoice_id=%s",
            provider,
            user.tg_id,
            locals().get("invoice_id", "<not-set>"),
        )
        await callback.answer("❌ ایجاد فاکتور تمدید انجام نشد. لطفاً درگاه دیگری را انتخاب کنید.", show_alert=True)


@router.callback_query(F.data.regexp(r"^smartcard:choose:wallet:\d+$"))
async def choose_wallet_smart_card(callback: CallbackQuery, user: User, gateway_factory: GatewayFactory) -> None:
    amount = int((callback.data or "").rsplit(":", 1)[1])
    await callback.answer()
    await callback.message.edit_text(
        "💳 <b>درگاه‌های کارت به کارت هوشمند شارژ کیف پول</b>\n\n"
        f"💰 مبلغ شارژ: <b>{amount:,} تومان</b>\n\n"
        "درگاه موردنظر را انتخاب کنید:",
        reply_markup=_smart_provider_keyboard(
            amount=amount,
            select_prefix=f"smartcard:pay:wallet:{amount}",
            back_callback=NavMain.WALLET,
            factory=gateway_factory,
        ),
    )


@router.callback_query(F.data.regexp(r"^smartcard:pay:wallet:\d+:(?:pay_aban|pay_blupal)$"))
async def pay_wallet_smart_card(callback: CallbackQuery, user: User, gateway_factory: GatewayFactory, services: ServicesContainer) -> None:
    parts = (callback.data or "").split(":")
    amount, provider = int(parts[3]), parts[4]
    gateway = _smart_gateways(gateway_factory).get(provider)
    if gateway is None or amount <= 0:
        await callback.answer("❌ این درگاه در حال حاضر فعال نیست.", show_alert=True)
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
        logger.info(
            "SMARTCARD_DIAG create_payment:start provider=%s user=%s",
            provider,
            user.tg_id,
        )
        pay_url = await gateway.create_payment(data)
        logger.info(
            "SMARTCARD_DIAG create_payment:done provider=%s user=%s pay_url_present=%s",
            provider,
            user.tg_id,
            bool(pay_url),
        )
        invoice_id = _invoice_id(pay_url)
        logger.info(
            "SMARTCARD_DIAG invoice_id provider=%s user=%s invoice_id=%s",
            provider,
            user.tg_id,
            invoice_id or "<empty>",
        )
        logger.info(
            "SMARTCARD_DIAG get_invoice:start provider=%s user=%s invoice_id=%s",
            provider,
            user.tg_id,
            invoice_id or "<empty>",
        )
        invoice = await gateway._get_invoice(invoice_id) if provider == SMART_ABAN_KEY else await gateway.get_invoice(invoice_id)  # type: ignore[attr-defined]
        logger.info(
            "SMARTCARD_DIAG get_invoice:done provider=%s user=%s invoice_id=%s invoice_type=%s",
            provider,
            user.tg_id,
            invoice_id or "<empty>",
            type(invoice).__name__,
        )
        if provider == SMART_ABAN_KEY:
            payable = invoice.get("payable_toman") or amount
            text = (
                "💳 <b>شارژ کیف پول — آبان گیت</b>\n\n"
                f"💰 مبلغ قابل پرداخت: <code>{float(payable):,.0f}</code> تومان\n"
                f"کد پیگیری: <code>{html.escape(str(invoice.get('order_id') or invoice_id))}</code>"
            )
        else:
            final_toman = int(invoice.get("final_amount") or 0) / 10
            text = (
                "💳 <b>شارژ کیف پول — بلوپال</b>\n\n"
                f"💰 مبلغ نهایی پرداخت: <code>{final_toman:,.0f}</code> تومان\n"
                f"شماره کارت مقصد: <code>{html.escape(str(invoice.get('card_number') or 'طبق صفحه پرداخت'))}</code>"
            )
        await callback.answer()
        await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 پرداخت", url=pay_url)],
            [InlineKeyboardButton(text="🔙 تغییر درگاه کارت به کارت", callback_data=f"smartcard:choose:wallet:{amount}")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavMain.WALLET)],
        ]))
    except Exception:
        logger.exception(
            "SMARTCARD_DIAG exception flow=wallet provider=%s user=%s invoice_id=%s",
            provider,
            user.tg_id,
            locals().get("invoice_id", "<not-set>"),
        )
        await callback.answer("❌ ایجاد فاکتور شارژ انجام نشد. لطفاً درگاه دیگری را انتخاب کنید.", show_alert=True)


# The common customer keyboards are patched here, after the existing payment
# visibility module has installed its compatibility hooks. Existing gateways
# remain registered and their own handlers are not modified.
def install() -> None:
    subscription_handler.payment_method_keyboard = _purchase_top_level
    subscription_handler.managed_payment_method_keyboard = (
        lambda p, price, gateways: _managed_keyboard(
            p,
            price,
            gateways,
            f"subscription_back_config_name:{p}",
        )
    )
    subscription_keyboard.payment_method_keyboard = _purchase_top_level
    subscription_keyboard.managed_payment_method_keyboard = (
        lambda p, price, gateways: _managed_keyboard(
            p,
            price,
            gateways,
            f"subscription_back_config_name:{p}",
        )
    )
    subscription_keyboard.managed_payment_method_keyboard_traffic = lambda sid, p, price, gateways: _managed_keyboard(p, price, gateways, f"traffic:add:{sid}")
    subscription_keyboard.managed_payment_method_keyboard_renewal = lambda p, price, gateways: _managed_keyboard(p, price, gateways, f"renewal:service:{p}")
    wallet_handler.payment_method_keyboard = _wallet_keyboard
    renew_service_handler._payment_methods_keyboard = _renewal_keyboard
    # managed_card_payment imported these functions by name before our patch.
    try:
        from app.bot.routers import managed_card_payment
        managed_card_payment.managed_payment_method_keyboard = _managed_keyboard
        managed_card_payment.managed_payment_method_keyboard_renewal = lambda p, price, gateways: _renewal_keyboard(0, p, price, GatewayFactory())
    except Exception:
        pass


install()
