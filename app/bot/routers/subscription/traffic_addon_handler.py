from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.models import ServicesContainer, SubscriptionData
from app.bot.routers.my_services.handler import (
    _status,
    _sync_subscriptions_with_xui,
)
from app.bot.routers.subscription.keyboard import managed_payment_method_keyboard
from app.bot.payment_gateways import GatewayFactory
from app.bot.utils.navigation import NavMain
from app.db.models import Server, ServicePurchasePlan, Subscription, User

router = Router(name=__name__)
TRAFFIC_ADDON_TYPE = "traffic_addon"


def _main_menu_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)


def _plan_keyboard(subscription_id: int, plans: list[ServicePurchasePlan]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.row(
            InlineKeyboardButton(
                text=f"➕ {plan.volume_gb:,} GB | {plan.price_toman:,} تومان",
                callback_data=f"traffic:plan:{subscription_id}:{plan.id}",
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="🔙 بازگشت به سرویس",
            callback_data=f"my_services:view:{subscription_id}",
        )
    )
    builder.row(_main_menu_button())
    return builder.as_markup()


def _summary_keyboard(subscription_id: int, plan_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 انتخاب روش پرداخت", callback_data=f"traffic:payment:{subscription_id}:{plan_id}")],
            [InlineKeyboardButton(text="🔙 تغییر حجم", callback_data=f"traffic:add:{subscription_id}")],
            [_main_menu_button()],
        ]
    )


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
    if not subscription:
        return None
    synced = await _sync_subscriptions_with_xui(session, [subscription], services)
    return synced[0] if synced else None


@router.callback_query(F.data.regexp(r"^traffic:add:\d+$"))
async def callback_add_traffic(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    subscription_id = int(callback.data.rsplit(":", 1)[1])
    subscription = await _get_subscription(session, user, subscription_id, services)
    if not subscription:
        await callback.answer("❌ سرویس پیدا نشد یا دیگر در 3X-UI وجود ندارد.", show_alert=True)
        return

    _icon, status_text = _status(subscription)
    if status_text == "منقضی شده":
        await callback.answer("❌ این سرویس منقضی شده است. ابتدا آن را تمدید کنید.", show_alert=True)
        return
    if subscription.status != "active":
        await callback.answer("❌ این سرویس فعال نیست و امکان افزایش حجم ندارد.", show_alert=True)
        return

    plans = await ServicePurchasePlan.list_by_type(session, TRAFFIC_ADDON_TYPE)
    plans = [plan for plan in plans if plan.volume_gb > 0 and plan.duration_days == 0 and plan.price_toman > 0]
    plans.sort(key=lambda plan: (plan.volume_gb, plan.price_toman, plan.id))

    await callback.answer()
    if not plans:
        await callback.message.edit_text(
            "📈 <b>افزایش حجم</b>\n\n"
            "در حال حاضر هیچ بسته افزایش حجمی برای فروش فعال نشده است.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 بازگشت به سرویس", callback_data=f"my_services:view:{subscription.id}")],
                    [_main_menu_button()],
                ]
            ),
        )
        return

    client_data = await services.vpn.get_client_data(user, subscription_id=subscription.id)
    total = client_data.traffic_total_formatted if client_data else f"{subscription.volume_gb} GB"
    remaining = client_data.traffic_remaining_formatted if client_data else "در دسترس نیست"

    await callback.message.edit_text(
        "📈 <b>افزایش حجم سرویس</b>\n\n"
        f"📦 <b>سرویس:</b> <code>{subscription.config_name}</code>\n"
        f"💾 <b>حجم کل فعلی:</b> {total}\n"
        f"📊 <b>حجم باقی‌مانده:</b> {remaining}\n\n"
        "مقدار حجمی که می‌خواهید به همین سرویس اضافه شود را انتخاب کنید:",
        reply_markup=_plan_keyboard(subscription.id, plans),
    )


@router.callback_query(F.data.regexp(r"^traffic:plan:\d+:\d+$"))
async def callback_traffic_plan(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    state: FSMContext,
) -> None:
    _, _, subscription_id_text, plan_id_text = callback.data.split(":")
    subscription_id = int(subscription_id_text)
    plan_id = int(plan_id_text)

    subscription = await _get_subscription(session, user, subscription_id, services)
    plan = await ServicePurchasePlan.get(session, plan_id)
    if not subscription or not plan or plan.service_type != TRAFFIC_ADDON_TYPE or plan.volume_gb <= 0 or plan.duration_days != 0 or plan.price_toman <= 0:
        await callback.answer("❌ اطلاعات بسته افزایش حجم نامعتبر یا منقضی شده است.", show_alert=True)
        return

    if subscription.status != "active" or _status(subscription)[1] == "منقضی شده":
        await callback.answer("❌ این سرویس دیگر فعال نیست.", show_alert=True)
        return

    data = SubscriptionData(
        state="config_name",
        is_extend=True,
        is_change=False,
        user_id=user.tg_id,
        devices=subscription.devices,
        duration=0,
        price=plan.price_toman,
        plan_id=plan.id,
        volume_gb=plan.volume_gb,
        config_name=subscription.config_name,
    )
    data.subscription_id = subscription.id

    await state.update_data(
        subscription_data={
            "state": "config_name",
            "is_extend": True,
            "is_change": False,
            "user_id": user.tg_id,
            "devices": subscription.devices,
            "duration": 0,
            "price": plan.price_toman,
            "plan_id": plan.id,
            "volume_gb": plan.volume_gb,
            "config_name": subscription.config_name,
            "subscription_id": subscription.id,
        }
    )

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
async def callback_traffic_payment_methods(
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

    packed = (await state.get_data()).get("subscription_data")
    if not isinstance(packed, dict) or int(packed.get("subscription_id", 0)) != subscription_id or int(packed.get("plan_id", 0)) != plan_id:
        await state.clear()
        await callback.answer("❌ اطلاعات سفارش افزایش حجم منقضی شده است.", show_alert=True)
        return

    subscription = await _get_subscription(session, user, subscription_id, services)
    plan = await ServicePurchasePlan.get(session, plan_id)
    if not subscription or not plan or plan.service_type != TRAFFIC_ADDON_TYPE or plan.duration_days != 0:
        await state.clear()
        await callback.answer("❌ سرویس یا بسته افزایش حجم دیگر معتبر نیست.", show_alert=True)
        return

    packed.update(
        {
            "price": plan.price_toman,
            "volume_gb": plan.volume_gb,
            "duration": 0,
            "config_name": subscription.config_name,
            "devices": subscription.devices,
            "subscription_id": subscription.id,
        }
    )
    await state.update_data(subscription_data=packed)

    await callback.answer()
    await callback.message.edit_text(
        "💳 <b>انتخاب روش پرداخت افزایش حجم</b>\n\n"
        f"📦 <b>سرویس:</b> <code>{subscription.config_name}</code>\n"
        f"➕ <b>حجم افزوده:</b> {plan.volume_gb} GB\n"
        f"💰 <b>مبلغ:</b> {plan.price_toman:,} تومان\n\n"
        "روش پرداخت را انتخاب کنید:",
        reply_markup=managed_payment_method_keyboard(
            plan.id,
            plan.price_toman,
            gateway_factory.get_gateways(),
        ),
    )
