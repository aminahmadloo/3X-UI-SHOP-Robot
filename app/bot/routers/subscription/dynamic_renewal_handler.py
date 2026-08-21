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
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import Server, ServicePurchasePlan, Subscription
from app.db.models.service_period import ServicePeriod

router = Router(name=__name__)


def _main_menu_button():
    return InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)


def _service_list_keyboard(subscriptions):
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


def _plan_list_keyboard(subscription_id: int, plans):
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.row(
            InlineKeyboardButton(
                text=f"📅 {plan.duration_days} روز | {plan.price_toman:,} تومان",
                callback_data=f"renewal:plan:{subscription_id}:{plan.id}",
            )
        )
    builder.row(InlineKeyboardButton(text="🔙 تغییر سرویس", callback_data=NavSubscription.RENEW_SERVICE))
    builder.row(_main_menu_button())
    return builder.as_markup()


async def _get_subscription(session, user, subscription_id, services):
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


async def _period_for_duration(session: AsyncSession, duration_days: int) -> ServicePeriod | None:
    periods = await ServicePeriod.list_active(session)
    if not periods:
        return None
    return min(periods, key=lambda period: abs(period.duration_days - duration_days))


@router.callback_query(F.data == NavSubscription.RENEW_SERVICE)
async def dynamic_renewal_entry(callback: CallbackQuery, user, session: AsyncSession, services: ServicesContainer, state: FSMContext):
    await state.clear()
    result = await session.execute(
        select(Subscription)
        .join(Server, Subscription.server_id == Server.id)
        .options(selectinload(Subscription.server))
        .where(Subscription.user_id == user.id, Subscription.server_id.is_not(None))
        .order_by(Subscription.id.desc())
    )
    items = await _sync_subscriptions_with_xui(session, list(result.scalars().all()), services)
    items = [item for item in items if _status(item)[1] in {"فعال", "رو به اتمام", "منقضی شده"}]
    await callback.answer()
    if not items:
        await callback.message.edit_text(
            "🔄 <b>تمدید سرویس</b>\n\nشما در حال حاضر سرویس قابل تمدیدی ندارید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_main_menu_button()]]),
        )
        return
    await callback.message.edit_text(
        "🔄 <b>تمدید سرویس</b>\n\nسرویسی را که می‌خواهید تمدید کنید انتخاب کنید:",
        reply_markup=_service_list_keyboard(items),
    )


@router.callback_query(F.data.regexp(r"^renewal:service:\d+$"))
async def dynamic_renewal_service_selected(callback: CallbackQuery, user, session: AsyncSession, services: ServicesContainer):
    subscription = await _get_subscription(session, user, int(callback.data.rsplit(":", 1)[1]), services)
    if not subscription:
        await callback.answer("❌ این سرویس دیگر قابل تمدید نیست.", show_alert=True)
        return

    period = await _period_for_duration(session, subscription.duration_days)
    if not period:
        await callback.answer("❌ هیچ دوره فعالی برای این سرویس وجود ندارد.", show_alert=True)
        return

    plans = await ServicePurchasePlan.list_by_type(session, period.service_type)
    plans = [plan for plan in plans if plan.volume_gb == subscription.volume_gb and plan.duration_days > 0]
    plans.sort(key=lambda plan: (plan.duration_days, plan.id))

    await callback.answer()
    if not plans:
        await callback.message.edit_text(
            "🔄 <b>تمدید سرویس</b>\n\n"
            f"برای حجم فعلی این سرویس ({subscription.volume_gb} GB) در دوره {period.name} هنوز پلن تمدید فعالی ثبت نشده است.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 انتخاب سرویس دیگر", callback_data=NavSubscription.RENEW_SERVICE)],
                    [_main_menu_button()],
                ]
            ),
        )
        return

    await callback.message.edit_text(
        f"🔄 <b>انتخاب مدت تمدید {period.name}</b>\n\n"
        f"📦 سرویس: <code>{subscription.config_name}</code>\n"
        f"💾 حجم: <b>{subscription.volume_gb} GB</b>\n\n"
        "مدت تمدید را انتخاب کنید:",
        reply_markup=_plan_list_keyboard(subscription.id, plans),
    )
