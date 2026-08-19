from __future__ import annotations

from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.models import ServicesContainer, SubscriptionData
from app.bot.routers.my_services.handler import (
    _effective_expire_date,
    _status,
    _sync_subscriptions_with_xui,
)
from app.bot.routers.subscription.keyboard import managed_payment_method_keyboard
from app.bot.payment_gateways import GatewayFactory
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import Server, ServicePurchasePlan, Subscription, User

router = Router(name=__name__)


async def _get_user_subscription(
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
    if not subscription:
        return None

    synced = await _sync_subscriptions_with_xui(session, [subscription], services)
    return synced[0] if synced else None


def _main_menu_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)


def _service_list_keyboard(subscriptions: list[Subscription]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for subscription in subscriptions:
        icon, status_text = _status(subscription)
        builder.row(
            InlineKeyboardButton(
                text=f"{icon} {subscription.config_name} | {subscription.volume_gb}GB | {status_text}",
                callback_data=f"renewal:service:{subscription.id}",
            )
        )
    builder.row(InlineKeyboardButton(text="🛒 خرید سرویس جدید", callback_data=NavSubscription.BUY))
    builder.row(_main_menu_button())
    return builder.as_markup()


def _duration_keyboard(subscription: Subscription, plans: list[ServicePurchasePlan]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        period = "یک ماه" if plan.duration_days <= 31 else "سه ماه"
        builder.row(
            InlineKeyboardButton(
                text=f"📅 {period} | {plan.duration_days} روز | {plan.price_toman:,} تومان",
                callback_data=f"renewal:plan:{subscription.id}:{plan.id}",
            )
        )
    builder.row(InlineKeyboardButton(text="🔙 تغییر سرویس", callback_data=NavSubscription.RENEW_SERVICE))
    builder.row(_main_menu_button())
    return builder.as_markup()


def _summary_keyboard(subscription_id: int, plan_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 انتخاب روش پرداخت", callback_data=f"renewal:payment_methods:{subscription_id}:{plan_id}")],
            [InlineKeyboardButton(text="🔙 تغییر مدت", callback_data=f"renewal:service:{subscription_id}")],
            [_main_menu_button()],
        ]
    )


def _format_expire(value: datetime | None) -> str:
    if not value:
        return "نامحدود"
    return value.astimezone(timezone.utc).strftime("%Y/%m/%d %H:%M")


def _format_remaining_time(value: datetime | None) -> str:
    if not value:
        return "نامحدود"

    remaining = value - datetime.now(timezone.utc)
    total_seconds = int(remaining.total_seconds())
    if total_seconds <= 0:
        return "منقضی شده"

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60
    parts = []
    if days:
        parts.append(f"{days} روز")
    if hours:
        parts.append(f"{hours} ساعت")
    if not days and not hours and minutes:
        parts.append(f"{minutes} دقیقه")
    return " و ".join(parts) if parts else "کمتر از ۱ دقیقه"


@router.callback_query(F.data == NavSubscription.RENEW_SERVICE)
async def callback_renew_service(
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
    items = list(result.scalars().all())
    items = await _sync_subscriptions_with_xui(session, items, services)
    items = [item for item in items if _status(item)[1] in {"فعال", "رو به اتمام", "منقضی شده"}]

    await callback.answer()
    if not items:
        await callback.message.edit_text(
            "🔄 <b>تمدید سرویس</b>\n\n"
            "شما در حال حاضر سرویس قابل تمدیدی ندارید.\n\n"
            "برای استفاده از این بخش ابتدا یک سرویس خریداری کنید.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🛒 خرید سرویس جدید", callback_data=NavSubscription.BUY)],
                    [_main_menu_button()],
                ]
            ),
        )
        return

    await callback.message.edit_text(
        "🔄 <b>تمدید سرویس</b>\n\nسرویسی را که می‌خواهید تمدید کنید انتخاب کنید:",
        reply_markup=_service_list_keyboard(items),
    )


@router.callback_query(F.data.regexp(r"^renewal:service:\d+$"))
async def callback_renewal_service_selected(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    subscription_id = int(callback.data.rsplit(":", 1)[1])
    subscription = await _get_user_subscription(session, user, subscription_id, services)
    if not subscription:
        await callback.answer("❌ این سرویس دیگر قابل تمدید نیست.", show_alert=True)
        return

    plans = await ServicePurchasePlan.list_by_type(session, "one_month")
    plans += await ServicePurchasePlan.list_by_type(session, "three_month")
    plans = [plan for plan in plans if plan.volume_gb == subscription.volume_gb and plan.duration_days > 0]
    plans.sort(key=lambda plan: (plan.duration_days, plan.id))

    await callback.answer()
    if not plans:
        await callback.message.edit_text(
            "🔄 <b>تمدید سرویس</b>\n\n"
            f"برای حجم فعلی این سرویس ({subscription.volume_gb} GB) هنوز پلن تمدید فعالی ثبت نشده است.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 انتخاب سرویس دیگر", callback_data=NavSubscription.RENEW_SERVICE)],
                    [_main_menu_button()],
                ]
            ),
        )
        return

    icon, status_text = _status(subscription)
    current_expire = _effective_expire_date(subscription)
    remaining_time = _format_remaining_time(current_expire)

    client_data = await services.vpn.get_client_data(user, subscription_id=subscription.id)
    traffic_remaining = client_data.traffic_remaining if client_data else "در دسترس نیست"

    await callback.message.edit_text(
        "🔄 <b>انتخاب مدت تمدید</b>\n\n"
        f"{icon} <b>سرویس:</b> <code>{subscription.config_name}</code>\n"
        f"💾 <b>حجم کل:</b> {subscription.volume_gb} GB\n"
        f"📊 <b>حجم باقی‌مانده:</b> {traffic_remaining}\n"
        f"⏳ <b>زمان باقی‌مانده:</b> {remaining_time}\n"
        f"📌 <b>وضعیت:</b> {status_text}\n\n"
        "مدت تمدید را انتخاب کنید:",
        reply_markup=_duration_keyboard(subscription, plans),
    )


@router.callback_query(F.data.regexp(r"^renewal:plan:\d+:\d+$"))
async def callback_renewal_plan_selected(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    state: FSMContext,
) -> None:
    _, _, subscription_id_text, plan_id_text = callback.data.split(":")
    subscription_id = int(subscription_id_text)
    plan_id = int(plan_id_text)

    subscription = await _get_user_subscription(session, user, subscription_id, services)
    plan = await ServicePurchasePlan.get(session, plan_id)
    if not subscription or not plan or plan.volume_gb != subscription.volume_gb or plan.duration_days <= 0:
        await callback.answer("❌ اطلاعات تمدید نامعتبر یا منقضی شده است.", show_alert=True)
        return

    data = SubscriptionData(
        state=NavSubscription.PAY,
        is_extend=True,
        user_id=user.tg_id,
        devices=subscription.devices,
        duration=plan.duration_days,
        price=plan.price_toman,
        plan_id=plan.id,
        volume_gb=subscription.volume_gb,
        config_name=subscription.config_name,
    )
    data.subscription_id = subscription.id
    await state.update_data(subscription_data={
        "state": NavSubscription.PAY.value,
        "is_extend": True,
        "is_change": False,
        "user_id": data.user_id,
        "devices": data.devices,
        "duration": data.duration,
        "price": data.price,
        "plan_id": data.plan_id,
        "volume_gb": data.volume_gb,
        "config_name": data.config_name,
        "subscription_id": data.subscription_id,
    })

    current_expire = _effective_expire_date(subscription)
    base = current_expire if current_expire and current_expire > datetime.now(timezone.utc) else datetime.now(timezone.utc)
    new_expire = base + timedelta(days=plan.duration_days)

    client_data = await services.vpn.get_client_data(user, subscription_id=subscription.id)
    traffic_remaining = client_data.traffic_remaining if client_data else "در دسترس نیست"
    remaining_time = _format_remaining_time(current_expire)

    await callback.answer()
    await callback.message.edit_text(
        "🧾 <b>خلاصه سفارش تمدید</b>\n\n"
        f"📦 <b>سرویس:</b> <code>{subscription.config_name}</code>\n"
        f"💾 <b>حجم کل:</b> {subscription.volume_gb} GB\n"
        f"📊 <b>حجم باقی‌مانده:</b> {traffic_remaining}\n"
        f"⏳ <b>زمان باقی‌مانده:</b> {remaining_time}\n"
        f"📅 <b>مدت تمدید:</b> {plan.duration_days} روز\n"
        f"⏱ <b>انقضای فعلی:</b> {_format_expire(current_expire)}\n"
        f"🆕 <b>انقضای جدید:</b> {_format_expire(new_expire)}\n"
        f"💰 <b>مبلغ:</b> {plan.price_toman:,} تومان\n\n"
        "حجم، سرور و مشخصات سرویس فعلی تغییر نمی‌کند.",
        reply_markup=_summary_keyboard(subscription.id, plan.id),
    )


@router.callback_query(F.data.regexp(r"^renewal:payment_methods:\d+:\d+$"))
async def callback_renewal_payment_methods(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    state: FSMContext,
    gateway_factory: GatewayFactory,
) -> None:
    _, _, subscription_id_text, plan_id_text = callback.data.split(":")
    subscription_id = int(subscription_id_text)
    plan_id = int(plan_id_text)

    data = await state.get_data()
    packed = data.get("subscription_data")
    if not isinstance(packed, dict) or int(packed.get("subscription_id", 0)) != subscription_id or int(packed.get("plan_id", 0)) != plan_id:
        await callback.answer("❌ اطلاعات سفارش تمدید منقضی شده است.", show_alert=True)
        await state.clear()
        return

    subscription = await _get_user_subscription(session, user, subscription_id, services)
    plan = await ServicePurchasePlan.get(session, plan_id)
    if not subscription or not plan or plan.volume_gb != subscription.volume_gb:
        await callback.answer("❌ سرویس یا پلن تمدید دیگر معتبر نیست.", show_alert=True)
        await state.clear()
        return

    packed.update({
        "duration": plan.duration_days,
        "price": plan.price_toman,
        "volume_gb": subscription.volume_gb,
        "config_name": subscription.config_name,
        "devices": subscription.devices,
        "subscription_id": subscription.id,
    })
    await state.update_data(subscription_data=packed)

    await callback.answer()
    await callback.message.edit_text(
        "💳 <b>انتخاب روش پرداخت تمدید</b>\n\n"
        f"📦 <b>سرویس:</b> <code>{subscription.config_name}</code>\n"
        f"💾 <b>حجم:</b> {subscription.volume_gb} GB\n"
        f"📅 <b>مدت:</b> {plan.duration_days} روز\n"
        f"💰 <b>مبلغ:</b> {plan.price_toman:,} تومان\n\n"
        "روش پرداخت را انتخاب کنید:",
        reply_markup=managed_payment_method_keyboard(
            plan.id,
            plan.price_toman,
            gateway_factory.get_gateways(),
        ),
    )
