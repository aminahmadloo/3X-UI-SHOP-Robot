from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.models import ServicesContainer, SubscriptionData
from app.bot.payment_gateways import GatewayFactory
from app.bot.routers.my_services.handler import _status, _sync_subscriptions_with_xui
from app.bot.routers.wallet.handler import has_pending_payment
from app.db.models import Server, ServicePurchasePlan, Subscription, User
from app.bot.utils.jalali import format_jalali

logger = logging.getLogger(__name__)
router = Router(name=__name__)

ENTRY_CALLBACK = "main_menu:renew_service"
SERVICE_CALLBACK_PREFIX = "main_renewal:service:"
PAYMENT_METHODS_PREFIX = "main_renewal:methods:"
GATEWAY_PREFIX = "main_renewal:gateway:"
CARD_PREFIX = "main_renewal:card:"


def _home_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="main_menu")


def _services_keyboard(subscriptions: list[Subscription]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for subscription in subscriptions[:8]:
        icon, status_text = _status(subscription)
        builder.row(
            InlineKeyboardButton(
                text=f"{icon} {subscription.config_name} | {subscription.volume_gb}GB | {status_text}",
                callback_data=f"{SERVICE_CALLBACK_PREFIX}{subscription.id}",
            )
        )
    builder.row(_home_button())
    return builder.as_markup()


def _payment_methods_keyboard(
    subscription_id: int,
    plan_id: int,
    price: int,
    gateway_factory: GatewayFactory,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    # 1) درگاه‌های بانکی
    for gateway in gateway_factory.get_gateways():
        builder.row(
            InlineKeyboardButton(
                text=f"🏦 {gateway.name} | {price:,} تومان",
                callback_data=f"{GATEWAY_PREFIX}{subscription_id}:{plan_id}:{gateway.callback}",
            )
        )

    # 2) کارت به کارت
    builder.row(
        InlineKeyboardButton(
            text=f"💳 کارت به کارت | {price:,} تومان",
            callback_data=f"{CARD_PREFIX}{subscription_id}:{plan_id}",
        )
    )

    # 3) کیف پول
    builder.row(
        InlineKeyboardButton(
            text=f"👛 پرداخت از کیف پول | {price:,} تومان",
            callback_data=f"main_renewal:wallet:{subscription_id}:{plan_id}",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="🔙 تغییر سرویس",
            callback_data=f"{SERVICE_CALLBACK_PREFIX}{subscription_id}",
        )
    )

    builder.row(_home_button())

    return builder.as_markup()


def _payment_link_keyboard(pay_url: str, subscription_id: int, plan_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 پرداخت در زرین‌پال", url=pay_url)],
            [
                InlineKeyboardButton(
                    text="🔙 تغییر روش پرداخت",
                    callback_data=f"{PAYMENT_METHODS_PREFIX}{subscription_id}:{plan_id}",
                )
            ],
            [_home_button()],
        ]
    )


def _subscription_data(subscription: Subscription, plan: ServicePurchasePlan, user: User) -> SubscriptionData:
    data = SubscriptionData(
        state="pay",
        is_extend=True,
        is_change=False,
        user_id=user.tg_id,
        devices=subscription.devices,
        duration=plan.duration_days,
        price=plan.price_toman,
        plan_id=plan.id,
        volume_gb=plan.volume_gb,
        config_name=subscription.config_name,
    )
    data.subscription_id = subscription.id
    return data


async def _get_subscription(
    session: AsyncSession,
    user: User,
    subscription_id: int,
    services: ServicesContainer,
) -> Subscription | None:
    result = await session.execute(
        select(Subscription)
        .join(Server, Subscription.server_id == Server.id)
        .options(selectinload(Subscription.server))
        .where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
            Subscription.server_id.is_not(None),
        )
    )
    subscription = result.scalar_one_or_none()
    if subscription is None:
        return None
    synced = await _sync_subscriptions_with_xui(session, [subscription], services)
    return synced[0] if synced else None


async def _original_plan(
    session: AsyncSession,
    subscription: Subscription,
) -> ServicePurchasePlan | None:
    """
    Resolve the original purchase plan using a safe fallback chain:

    1. subscription.plan_id
    2. volume + duration encoded in config_name
       (e.g. 50GB-90D-tg123-1)
    3. subscription's persisted volume_gb + duration_days

    The first successful match wins.
    """

    # --------------------------------------------------------
    # 1) Strongest source: persisted plan_id
    # --------------------------------------------------------
    if subscription.plan_id:
        plan = await ServicePurchasePlan.get(session, subscription.plan_id)
        if plan and plan.duration_days > 0 and plan.volume_gb > 0:
            return plan

    # --------------------------------------------------------
    # 2) Recover from config_name
    #    Example: 50GB-90D-tg78797797-1
    # --------------------------------------------------------
    match = re.search(
        r"(?P<volume>\d+)GB-(?P<days>\d+)D",
        subscription.config_name or "",
        re.IGNORECASE,
    )

    if match:
        volume = int(match.group("volume"))
        days = int(match.group("days"))

        result = await session.execute(
            select(ServicePurchasePlan)
            .where(
                ServicePurchasePlan.volume_gb == volume,
                ServicePurchasePlan.duration_days == days,
                ServicePurchasePlan.volume_gb > 0,
                ServicePurchasePlan.duration_days > 0,
                ServicePurchasePlan.price_toman > 0,
                ServicePurchasePlan.service_type.in_(
                    ("one_month", "period_2m", "three_month")
                ),
            )
            .order_by(ServicePurchasePlan.id)
        )

        plan = result.scalars().first()
        if plan:
            return plan

    # --------------------------------------------------------
    # 3) Final fallback: persisted subscription values
    # --------------------------------------------------------
    if subscription.volume_gb > 0 and subscription.duration_days > 0:
        result = await session.execute(
            select(ServicePurchasePlan)
            .where(
                ServicePurchasePlan.volume_gb == subscription.volume_gb,
                ServicePurchasePlan.duration_days == subscription.duration_days,
                ServicePurchasePlan.volume_gb > 0,
                ServicePurchasePlan.duration_days > 0,
                ServicePurchasePlan.price_toman > 0,
                ServicePurchasePlan.service_type.in_(
                    ("one_month", "period_2m", "three_month")
                ),
            )
            .order_by(ServicePurchasePlan.id)
        )

        plan = result.scalars().first()
        if plan:
            return plan

    logger.warning(
        "Unable to resolve original plan for subscription id=%s "
        "(plan_id=%s, config_name=%r, volume_gb=%s, duration_days=%s)",
        subscription.id,
        subscription.plan_id,
        subscription.config_name,
        subscription.volume_gb,
        subscription.duration_days,
    )

    return None


@router.callback_query(F.data == ENTRY_CALLBACK)
async def entry(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    state: FSMContext,
) -> None:
    await state.clear()

    result = await session.execute(
        select(Subscription)
        .join(Server, Subscription.server_id == Server.id)
        .options(selectinload(Subscription.server))
        .where(
            Subscription.user_id == user.id,
            Subscription.server_id.is_not(None),
        )
        .order_by(Subscription.id.desc())
    )
    subscriptions = await _sync_subscriptions_with_xui(
        session,
        list(result.scalars().all()),
        services,
    )
    subscriptions = [
        subscription
        for subscription in subscriptions
        if _status(subscription)[1] in {"فعال", "رو به اتمام", "منقضی شده"}
    ]

    await callback.answer()
    if not subscriptions:
        await callback.message.edit_text(
            "🔄 <b>تمدید سرویس</b>\n\n"
            "شما در حال حاضر سرویس قابل تمدیدی ندارید.\n\n"
            "ابتدا یک سرویس خریداری کنید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_home_button()]]),
        )
        return

    await callback.message.edit_text(
        "🔄 <b>تمدید سرویس</b>\n\n"
        "سرویسی را که می‌خواهید تمدید کنید انتخاب کنید:\n\n"
        "⚠️ تمدید، روی همان سرویس و همان کلاینت انجام می‌شود و سرویس جدیدی ساخته نخواهد شد.",
        reply_markup=_services_keyboard(subscriptions),
    )


@router.callback_query(F.data.regexp(r"^main_renewal:service:\d+$"))
async def service_selected(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    state: FSMContext,
) -> None:
    subscription_id = int((callback.data or "").rsplit(":", 1)[1])
    subscription = await _get_subscription(session, user, subscription_id, services)
    if subscription is None:
        await callback.answer("❌ سرویس پیدا نشد یا دیگر در 3X-UI وجود ندارد.", show_alert=True)
        return

    original_plan = await _original_plan(session, subscription)
    if original_plan is None:
        await callback.answer(
            "❌ پلن اصلی این سرویس پیدا نشد؛ تمدید امن این سرویس ممکن نیست.",
            show_alert=True,
        )
        return

    logger.warning(
        "RENEW DEBUG subscription=%s plan_id=%s original_plan=%s user=%s",
        subscription.id,
        subscription.plan_id,
        original_plan.id if original_plan else None,
        user.tg_id,
    )

    data = _subscription_data(subscription, original_plan, user)
    await state.update_data(subscription_data=data.serialize())

    expire = subscription.expire_date
    if expire is not None and expire.tzinfo is None:
        expire = expire.replace(tzinfo=timezone.utc)

    expire_text = format_jalali(expire) if expire else "نامحدود"

    client_data = await services.vpn.get_client_data(
        user,
        subscription_id=subscription.id,
    )

    traffic_remaining = (
        client_data.traffic_remaining_formatted
        if client_data
        else "در دسترس نیست"
    )

    if client_data:
        remaining_gb = client_data.traffic_remaining / (1024 ** 3)
        traffic_remaining_value = round(remaining_gb, 2)
        final_traffic_gb = round(
            remaining_gb + original_plan.volume_gb,
            2,
        )
    else:
        traffic_remaining_value = subscription.volume_gb
        final_traffic_gb = subscription.volume_gb + original_plan.volume_gb

    remaining_days = 0
    if expire:
        diff = expire - datetime.now(timezone.utc)
        remaining_days = max(diff.days, 0)

    final_days = remaining_days + original_plan.duration_days

    new_expire_text = "نامحدود"
    if expire:
        new_expire = expire + timedelta(days=original_plan.duration_days)
        new_expire_text = format_jalali(new_expire)

    icon, status_text = _status(subscription)

    await callback.answer()
    await callback.message.edit_text(
        "🔄 <b>خلاصه تمدید سرویس</b>\n\n"
        f"{icon} <b>سرویس:</b> <code>{subscription.config_name}</code>\n\n"
        f"📊 <b>حجم باقی‌مانده:</b> {traffic_remaining_value} GB\n"
        f"➕ <b>حجم تمدید:</b> {original_plan.volume_gb} GB\n"
        f"💾 <b>حجم نهایی پس از تمدید:</b> {final_traffic_gb} GB\n\n"
        f"⏳ <b>زمان باقی‌مانده:</b> {remaining_days} روز\n"
        f"📅 <b>زمان تمدید:</b> {original_plan.duration_days} روز\n"
        f"🗓 <b>مدت نهایی پس از تمدید:</b> {final_days} روز\n"
        f"📆 <b>تاریخ انقضا پس از تمدید:</b> {new_expire_text}\n\n"
        f"💰 <b>مبلغ تمدید:</b> {original_plan.price_toman:,} تومان\n\n"
        "این عملیات همان سرویس و همان کلاینت فعلی را تمدید می‌کند.\n"
        "کلید اتصال، سرور و مشخصات اتصال موجود حفظ می‌شوند.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="💳 انتخاب روش پرداخت",
                        callback_data=f"{PAYMENT_METHODS_PREFIX}{subscription.id}:{original_plan.id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 تغییر سرویس",
                        callback_data=ENTRY_CALLBACK,
                    )
                ],
                [_home_button()],
            ]
        ),
    )


@router.callback_query(F.data.regexp(r"^main_renewal:methods:\d+:\d+$"))
async def payment_methods(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    state: FSMContext,
    gateway_factory: GatewayFactory,
) -> None:
    _, _, subscription_id_text, plan_id_text = (callback.data or "").split(":")
    subscription_id = int(subscription_id_text)
    plan_id = int(plan_id_text)

    packed = (await state.get_data()).get("subscription_data")
    if not packed:
        await callback.answer("❌ اطلاعات سفارش تمدید منقضی شده است.", show_alert=True)
        await state.clear()
        return

    try:
        data = SubscriptionData.deserialize(packed)
    except Exception:
        await callback.answer("❌ اطلاعات سفارش تمدید نامعتبر است.", show_alert=True)
        await state.clear()
        return

    if data.user_id != user.tg_id or data.subscription_id != subscription_id or data.plan_id != plan_id:
        await callback.answer("❌ اطلاعات سفارش با این کاربر یا سرویس مطابقت ندارد.", show_alert=True)
        await state.clear()
        return

    subscription = await _get_subscription(session, user, subscription_id, services)
    plan = await ServicePurchasePlan.get(session, plan_id)
    if subscription is None or plan is None or plan.volume_gb <= 0 or plan.duration_days <= 0:
        await callback.answer("❌ سرویس یا پلن تمدید دیگر معتبر نیست.", show_alert=True)
        await state.clear()
        return

    if plan.id != subscription.plan_id:
        original_plan = await _original_plan(session, subscription)
        if original_plan is None or original_plan.id != plan.id:
            await callback.answer("❌ پلن اصلی سرویس تغییر کرده است؛ سفارش تمدید را دوباره بسازید.", show_alert=True)
            await state.clear()
            return

    data.duration = plan.duration_days
    data.volume_gb = plan.volume_gb
    data.price = plan.price_toman
    data.devices = subscription.devices
    data.config_name = subscription.config_name
    data.subscription_id = subscription.id
    await state.update_data(subscription_data=data.serialize())

    await callback.answer()
    await callback.message.edit_text(
        "💳 <b>انتخاب روش پرداخت تمدید سرویس</b>\n\n"
        f"🟢 <b>سرویس:</b> <code>{subscription.config_name}</code>\n\n"
        f"📦 حجم افزوده: <b>{plan.volume_gb} GB</b>\n"
        f"📅 زمان افزوده: <b>{plan.duration_days} روز</b>\n"
        f"💰 مبلغ: <b>{plan.price_toman:,} تومان</b>\n\n"
        "روش پرداخت را انتخاب کنید:",
        reply_markup=_payment_methods_keyboard(
            subscription.id,
            plan.id,
            plan.price_toman,
            gateway_factory,
        ),
    )


@router.callback_query(F.data.regexp(r"^main_renewal:gateway:\d+:\d+:[^:]+$"))
async def gateway_payment(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    state: FSMContext,
    gateway_factory: GatewayFactory,
) -> None:
    parts = (callback.data or "").split(":")
    subscription_id = int(parts[2])
    plan_id = int(parts[3])
    gateway_name = parts[4]

    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً ابتدا همان درخواست را تعیین تکلیف کنید.", show_alert=True)
        return

    current_state = await state.get_data()
    logger.warning("GATEWAY DEBUG FULL STATE=%s", current_state)

    packed = current_state.get("subscription_data")
    logger.warning("GATEWAY DEBUG PACKED=%s", packed)

    try:
        data = SubscriptionData.deserialize(packed or "")
    except Exception:
        await callback.answer("❌ اطلاعات سفارش تمدید منقضی یا نامعتبر است.", show_alert=True)
        await state.clear()
        return

    if data.user_id != user.tg_id or data.subscription_id != subscription_id or data.plan_id != plan_id:
        await callback.answer("❌ اطلاعات سفارش با این کاربر یا سرویس مطابقت ندارد.", show_alert=True)
        await state.clear()
        return

    subscription = await _get_subscription(session, user, subscription_id, services)
    plan = await ServicePurchasePlan.get(session, plan_id)
    if subscription is None or plan is None or plan.id != subscription.plan_id:
        await callback.answer("❌ سرویس یا پلن اصلی دیگر معتبر نیست.", show_alert=True)
        await state.clear()
        return

    data.duration = plan.duration_days
    data.volume_gb = plan.volume_gb
    data.price = plan.price_toman
    data.devices = subscription.devices
    data.config_name = subscription.config_name
    data.subscription_id = subscription.id
    await state.update_data(subscription_data=data.serialize())

    try:
        gateway = gateway_factory.get_gateway(gateway_name)
        pay_url = await gateway.create_payment(data)
    except Exception as exc:
        logger.exception("Main-menu renewal payment creation failed for user %s: %s", user.tg_id, exc)
        await callback.answer("❌ ایجاد لینک پرداخت تمدید انجام نشد. لطفاً دوباره تلاش کنید.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        "🏦 <b>پرداخت تمدید سرویس</b>\n\n"
        f"📦 حجم افزوده: <b>{plan.volume_gb} GB</b>\n"
        f"📅 زمان افزوده: <b>{plan.duration_days} روز</b>\n"
        f"💰 مبلغ: <b>{plan.price_toman:,} تومان</b>\n\n"
        "برای تکمیل پرداخت روی دکمه زیر بزنید:",
        reply_markup=_payment_link_keyboard(pay_url, subscription.id, plan.id),
    )


@router.callback_query(F.data.regexp(r"^main_renewal:card:\d+:\d+$"))
async def card_payment(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    state: FSMContext,
) -> None:
    subscription_id, plan_id = [int(x) for x in (callback.data or "").split(":")[-2:]]

    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً ابتدا همان درخواست را تعیین تکلیف کنید.", show_alert=True)
        return

    packed = (await state.get_data()).get("subscription_data")
    try:
        data = SubscriptionData.deserialize(packed or "")
    except Exception:
        await callback.answer("❌ اطلاعات سفارش تمدید منقضی یا نامعتبر است.", show_alert=True)
        await state.clear()
        return

    if data.user_id != user.tg_id or data.subscription_id != subscription_id or data.plan_id != plan_id:
        await callback.answer("❌ اطلاعات سفارش با این کاربر یا سرویس مطابقت ندارد.", show_alert=True)
        await state.clear()
        return

    subscription = await _get_subscription(session, user, subscription_id, services)
    plan = await ServicePurchasePlan.get(session, plan_id)
    if subscription is None or plan is None or plan.id != subscription.plan_id:
        await callback.answer("❌ سرویس یا پلن اصلی دیگر معتبر نیست.", show_alert=True)
        await state.clear()
        return

    data.duration = plan.duration_days
    data.volume_gb = plan.volume_gb
    data.price = plan.price_toman
    data.devices = subscription.devices
    data.config_name = subscription.config_name
    data.subscription_id = subscription.id
    await state.update_data(subscription_data=data.serialize())

    await callback.answer()
    await callback.message.edit_text(
        "💳 <b>کارت به کارت تمدید سرویس</b>\n\n"
        f"📦 حجم افزوده: <b>{plan.volume_gb} GB</b>\n"
        f"📅 زمان افزوده: <b>{plan.duration_days} روز</b>\n"
        f"💰 مبلغ: <b>{plan.price_toman:,} تومان</b>\n\n"
        "برای ادامه پرداخت، گزینه کارت به کارت را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💳 ادامه کارت به کارت", callback_data="custom_service:payment:card")],
                [InlineKeyboardButton(text="🔙 تغییر روش پرداخت", callback_data=f"{PAYMENT_METHODS_PREFIX}{subscription.id}:{plan.id}")],
                [_home_button()],
            ]
        ),
    )
