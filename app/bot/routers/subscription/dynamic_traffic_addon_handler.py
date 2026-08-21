from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.models import ServicesContainer
from app.bot.routers.my_services.handler import _status, _sync_subscriptions_with_xui
from app.bot.routers.subscription.keyboard import managed_payment_method_keyboard
from app.bot.payment_gateways import GatewayFactory
from app.bot.services.renewal import is_traffic_addon_type
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import Server, ServicePurchasePlan, Subscription
from app.db.models.service_period import ServicePeriod

router = Router(name=__name__)


def _main_menu_button():
    return InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)


def _active_service_list_keyboard(subscriptions):
    builder = InlineKeyboardBuilder()
    for subscription in subscriptions[:8]:
        icon, status_text = _status(subscription)
        builder.row(InlineKeyboardButton(text=f"{icon} {subscription.config_name} | {subscription.volume_gb}GB | {status_text}", callback_data=f"traffic:add:{subscription.id}"))
    builder.row(_main_menu_button())
    return builder.as_markup()


def _plan_keyboard(subscription_id, plans):
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.row(InlineKeyboardButton(text=f"➕ {plan.volume_gb:,} GB | {plan.price_toman:,} تومان", callback_data=f"traffic:plan:{subscription_id}:{plan.id}"))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت به سرویس", callback_data=f"my_services:view:{subscription_id}"))
    builder.row(_main_menu_button())
    return builder.as_markup()


def _summary_keyboard(subscription_id, plan_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 انتخاب روش پرداخت", callback_data=f"traffic:payment:{subscription_id}:{plan_id}")],
        [InlineKeyboardButton(text="🔙 تغییر حجم", callback_data=f"traffic:add:{subscription_id}")],
        [_main_menu_button()],
    ])


async def _get_subscription(session, user, subscription_id, services):
    result = await session.execute(
        select(Subscription)
        .join(Server, Subscription.server_id == Server.id)
        .options(selectinload(Subscription.server))
        .where(Subscription.id == subscription_id, Subscription.user_id == user.id, Subscription.server_id.is_not(None))
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        return None
    synced = await _sync_subscriptions_with_xui(session, [subscription], services)
    return synced[0] if synced else None


async def _period_for_subscription(session: AsyncSession, duration_days: int) -> ServicePeriod | None:
    periods = await ServicePeriod.list_active(session)
    if not periods:
        return None
    return min(periods, key=lambda period: abs(period.duration_days - duration_days))


async def _get_period_plans(session: AsyncSession, period: ServicePeriod):
    plans = await ServicePurchasePlan.list_by_type(session, period.traffic_addon_service_type)
    return sorted(
        [p for p in plans if is_traffic_addon_type(p.service_type) and p.volume_gb > 0 and p.duration_days == 0 and p.price_toman > 0],
        key=lambda p: (p.volume_gb, p.price_toman, p.id),
    )


@router.callback_query(F.data == NavSubscription.ADD_TRAFFIC)
async def dynamic_add_traffic_entry(callback: CallbackQuery, user, session: AsyncSession, services: ServicesContainer):
    result = await session.execute(
        select(Subscription)
        .join(Server, Subscription.server_id == Server.id)
        .options(selectinload(Subscription.server))
        .where(Subscription.user_id == user.id, Subscription.server_id.is_not(None))
        .order_by(Subscription.id.desc())
    )
    subscriptions = await _sync_subscriptions_with_xui(session, list(result.scalars().all()), services)
    subscriptions = [s for s in subscriptions if s.status == "active" and _status(s)[1] in {"فعال", "رو به اتمام"}]
    await callback.answer()
    if not subscriptions:
        await callback.message.edit_text(
            "📈 <b>افزایش حجم</b>\n\nشما در حال حاضر هیچ سرویس فعالی برای افزایش حجم ندارید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_main_menu_button()]]),
        )
        return

    price_lines = []
    for period in await ServicePeriod.list_active(session):
        plans = await _get_period_plans(session, period)
        if plans:
            per_gb = min(plan.price_toman / plan.volume_gb for plan in plans)
            price_lines.append(f"💰 مبلغ هر گیگابایت حجم {period.name.replace('سرویس‌های ', '')}: <b>{per_gb:,.0f} تومان/GB</b>")
        else:
            price_lines.append(f"💰 مبلغ هر گیگابایت حجم {period.name.replace('سرویس‌های ', '')}: <b>فعال نیست</b>")

    await callback.message.edit_text(
        "📈 <b>افزایش حجم سرویس</b>\n\n"
        + "\n".join(price_lines)
        + "\n\nسرویسی را که می‌خواهید حجم آن را افزایش دهید انتخاب کنید:",
        reply_markup=_active_service_list_keyboard(subscriptions),
    )


@router.callback_query(F.data.regexp(r"^traffic:add:\d+$"))
async def dynamic_add_traffic_service(callback: CallbackQuery, user, session: AsyncSession, services: ServicesContainer):
    subscription = await _get_subscription(session, user, int(callback.data.rsplit(":", 1)[1]), services)
    if not subscription:
        await callback.answer("❌ سرویس پیدا نشد یا دیگر در 3X-UI وجود ندارد.", show_alert=True)
        return
    if _status(subscription)[1] == "منقضی شده" or subscription.status != "active":
        await callback.answer("❌ این سرویس فعال نیست و امکان افزایش حجم ندارد.", show_alert=True)
        return

    period = await _period_for_subscription(session, subscription.duration_days)
    if not period:
        await callback.answer("❌ دوره این سرویس دیگر فعال نیست.", show_alert=True)
        return
    plans = await _get_period_plans(session, period)
    await callback.answer()
    if not plans:
        await callback.message.edit_text(
            f"📈 <b>افزایش حجم {period.name}</b>\n\nدر حال حاضر هیچ بسته افزایش حجمی برای فروش برای این دوره فعال نشده است.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت به سرویس", callback_data=f"my_services:view:{subscription.id}")], [_main_menu_button()]]),
        )
        return

    client_data = await services.vpn.get_client_data(user, subscription_id=subscription.id)
    total = client_data.traffic_total_formatted if client_data else f"{subscription.volume_gb} GB"
    remaining = client_data.traffic_remaining_formatted if client_data else "در دسترس نیست"
    await callback.message.edit_text(
        f"📈 <b>افزایش حجم سرویس {period.name.replace('سرویس‌های ', '')}</b>\n\n"
        f"📦 <b>سرویس:</b> <code>{subscription.config_name}</code>\n"
        f"💾 <b>حجم کل فعلی:</b> {total}\n"
        f"📊 <b>حجم باقی‌مانده:</b> {remaining}\n\n"
        "مقدار حجمی که می‌خواهید به همین سرویس اضافه شود را انتخاب کنید:",
        reply_markup=_plan_keyboard(subscription.id, plans),
    )


@router.callback_query(F.data.regexp(r"^traffic:plan:\d+:\d+$"))
async def dynamic_traffic_plan_selected(callback: CallbackQuery, user, session: AsyncSession, services: ServicesContainer, state: FSMContext):
    _, _, subscription_id_text, plan_id_text = callback.data.split(":")
    subscription_id = int(subscription_id_text)
    plan_id = int(plan_id_text)
    subscription = await _get_subscription(session, user, subscription_id, services)
    plan = await ServicePurchasePlan.get(session, plan_id)
    period = await _period_for_subscription(session, subscription.duration_days) if subscription else None
    if not subscription or not period or not plan or plan.service_type != period.traffic_addon_service_type or plan.duration_days != 0:
        await callback.answer("❌ اطلاعات بسته افزایش حجم نامعتبر یا منقضی شده است.", show_alert=True)
        return

    await state.update_data(subscription_data={"state": "config_name", "is_extend": True, "is_change": False, "user_id": user.tg_id, "devices": subscription.devices, "duration": 0, "price": plan.price_toman, "plan_id": plan.id, "volume_gb": plan.volume_gb, "config_name": subscription.config_name, "subscription_id": subscription.id})
    client_data = await services.vpn.get_client_data(user, subscription_id=subscription.id)
    current_total = client_data.traffic_total if client_data else subscription.volume_gb * 1024**3
    current_total_text = client_data.traffic_total_formatted if client_data else f"{subscription.volume_gb} GB"
    new_total_text = f"{current_total / 1024**3 + plan.volume_gb:g} GB"
    remaining_text = client_data.traffic_remaining_formatted if client_data else "در دسترس نیست"
    await callback.answer()
    await callback.message.edit_text(
        "🧾 <b>خلاصه سفارش افزایش حجم</b>\n\n"
        f"📦 <b>سرویس:</b> <code>{subscription.config_name}</code>\n"
        f"💾 <b>حجم کل فعلی:</b> {current_total_text}\n"
        f"📊 <b>حجم باقی‌مانده:</b> {remaining_text}\n"
        f"➕ <b>حجم افزوده‌شده:</b> {plan.volume_gb} GB\n"
        f"🆕 <b>حجم کل جدید:</b> {new_total_text}\n"
        f"💰 <b>مبلغ:</b> {plan.price_toman:,} تومان\n\n"
        "زمان انقضا، سرور و مشخصات اتصال این سرویس تغییر نمی‌کند.",
        reply_markup=_summary_keyboard(subscription.id, plan.id),
    )


@router.callback_query(F.data.regexp(r"^traffic:payment:\d+:\d+$"))
async def dynamic_traffic_payment_methods(callback: CallbackQuery, user, session: AsyncSession, services: ServicesContainer, state: FSMContext, gateway_factory: GatewayFactory):
    _, _, subscription_id_text, plan_id_text = callback.data.split(":")
    subscription_id = int(subscription_id_text)
    plan_id = int(plan_id_text)
    packed = (await state.get_data()).get("subscription_data")
    if not isinstance(packed, dict) or int(packed.get("subscription_id", 0)) != subscription_id or int(packed.get("plan_id", 0)) != plan_id:
        await state.clear()
        await callback.answer("❌ اطلاعات سفارش افزایش حجم منقضی شده است.", show_alert=True)
        return
    subscription = await _get_subscription(session, user, subscription_id, services)
    plan = await ServicePurchasePlan.get(session, plan_id)
    period = await _period_for_subscription(session, subscription.duration_days) if subscription else None
    if not subscription or not period or not plan or plan.service_type != period.traffic_addon_service_type:
        await state.clear()
        await callback.answer("❌ سرویس یا بسته افزایش حجم دیگر معتبر نیست.", show_alert=True)
        return
    packed.update({"price": plan.price_toman, "volume_gb": plan.volume_gb, "duration": 0, "config_name": subscription.config_name, "devices": subscription.devices, "subscription_id": subscription.id})
    await state.update_data(subscription_data=packed)
    await callback.answer()
    await callback.message.edit_text(
        "💳 <b>انتخاب روش پرداخت افزایش حجم</b>\n\n"
        f"📦 <b>سرویس:</b> <code>{subscription.config_name}</code>\n"
        f"➕ <b>حجم افزوده:</b> {plan.volume_gb} GB\n"
        f"💰 <b>مبلغ:</b> {plan.price_toman:,} تومان\n\nروش پرداخت را انتخاب کنید:",
        reply_markup=managed_payment_method_keyboard(plan.id, plan.price_toman, gateway_factory.get_gateways()),
    )
