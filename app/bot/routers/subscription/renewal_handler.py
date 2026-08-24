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
from app.bot.routers.subscription.keyboard import managed_payment_method_keyboard_renewal
from app.bot.payment_gateways import GatewayFactory
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import Server, ServicePurchasePlan, Subscription, User
from app.bot.utils.jalali import format_jalali

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
    return format_jalali(value)


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
            "⏳ <b>افزایش زمان سرویس</b>\n\n"
            "شما در حال حاضر سرویس فعالی برای افزایش زمان ندارید.\n\n"
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
        "⏳ <b>افزایش زمان سرویس</b>\n\nسرویسی را که می‌خواهید زمان آن افزایش یابد انتخاب کنید:",
        reply_markup=_service_list_keyboard(items),
    )



@router.callback_query(F.data.regexp(r"^renewal:service:\d+$"))
async def callback_renewal_service_selected(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    state: FSMContext,
) -> None:
    subscription_id = int(callback.data.rsplit(":", 1)[1])

    subscription = await _get_user_subscription(
        session,
        user,
        subscription_id,
        services,
    )

    if not subscription:
        await callback.answer("❌ سرویس پیدا نشد.", show_alert=True)
        return

    plan_result = await session.execute(
        select(ServicePurchasePlan).where(
            ServicePurchasePlan.volume_gb == subscription.volume_gb,
            ServicePurchasePlan.duration_days == subscription.duration_days,
            ServicePurchasePlan.service_type.in_(["one_month", "three_month"]),
        )
    )

    plan = plan_result.scalars().first()

    if not plan:
        await callback.answer(
            "❌ پلن مشابه برای تمدید این سرویس تعریف نشده است.",
            show_alert=True,
        )
        return

    current_expire = _effective_expire_date(subscription)

    remaining_days = 0
    if current_expire:
        remaining_days = max(
            0,
            int(
                (current_expire - datetime.now(timezone.utc))
                .total_seconds()
                // 86400
            ),
        )

    new_volume = subscription.volume_gb + plan.volume_gb
    new_days = remaining_days + plan.duration_days

    await state.update_data(subscription_data={
        "state": NavSubscription.PAY.value,
        "is_extend": True,
        "is_change": False,
        "user_id": user.tg_id,
        "devices": subscription.devices,
        "duration": plan.duration_days,
        "price": plan.price_toman,
        "plan_id": plan.id,
        "volume_gb": plan.volume_gb,
        "config_name": subscription.config_name,
        "subscription_id": subscription.id,
    })

    await callback.answer()

    await callback.message.edit_text(
        "🔄 <b>تمدید سرویس</b>\n\n"
        f"📌 <b>سرویس فعلی:</b>\n"
        f"<code>{subscription.config_name}</code>\n\n"
        f"📦 <b>حجم:</b>\n"
        f"فعلی {subscription.volume_gb}GB + تمدید {plan.volume_gb}GB = {new_volume}GB\n\n"
        f"⏳ <b>اعتبار:</b>\n"
        f"باقی‌مانده {remaining_days} روز + تمدید {plan.duration_days} روز = {new_days} روز\n\n"
        f"💰 <b>هزینه تمدید:</b>\n"
        f"{plan.price_toman:,} تومان",
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
        await callback.answer("❌ اطلاعات سفارش افزایش زمان منقضی شده است.", show_alert=True)
        await state.clear()
        return

    subscription = await _get_user_subscription(session, user, subscription_id, services)
    plan = await ServicePurchasePlan.get(session, plan_id)
    if not subscription or not plan or plan.volume_gb <= 0 or plan.duration_days <= 0:
        await callback.answer("❌ سرویس یا پلن افزایش زمان دیگر معتبر نیست.", show_alert=True)
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
        "💳 <b>انتخاب روش پرداخت افزایش زمان</b>\n\n"
        f"📦 <b>سرویس:</b> <code>{subscription.config_name}</code>\n"
        f"💾 <b>حجم:</b> {subscription.volume_gb} GB\n"
        f"📅 <b>مدت:</b> {plan.duration_days} روز\n"
        f"💰 <b>مبلغ:</b> {plan.price_toman:,} تومان\n\n"
        "روش پرداخت را انتخاب کنید:",
        reply_markup=managed_payment_method_keyboard_renewal(
            plan.id,
            plan.price_toman,
            gateway_factory.get_gateways(),
        ),
    )
