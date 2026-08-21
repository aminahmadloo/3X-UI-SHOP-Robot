from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.routers.subscription.keyboard import service_purchase_plan_keyboard
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import ConnectedDeviceSettings, ServicePurchasePlan
from app.db.models.service_period import ServicePeriod

router = Router(name=__name__)


def _main_menu_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)


def _period_keyboard(periods: list[ServicePeriod], devices: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    user_text = "کاربر نامحدود" if devices == 0 else f"{devices} کاربره"
    for period in periods:
        builder.row(
            InlineKeyboardButton(
                text=f"🚀 {period.name.replace('سرویس‌های ', '')} | {user_text}",
                callback_data=f"service_purchase:period:{period.id}",
            )
        )
    builder.row(_main_menu_button())
    return builder.as_markup()


async def _show_purchase_periods(callback: CallbackQuery, session: AsyncSession, user_id: int) -> None:
    settings = await ConnectedDeviceSettings.get_or_create(session)
    periods = await ServicePeriod.list_active(session)
    periods_with_plans = []
    for period in periods:
        plans = await ServicePurchasePlan.list_by_type(session, period.service_type)
        if plans:
            periods_with_plans.append(period)

    if not periods_with_plans:
        await callback.message.edit_text(
            "🛒 <b>خرید سرویس جدید</b>\n\n"
            "در حال حاضر هیچ دوره فعالی با پلن فروش ثبت‌شده وجود ندارد.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[_main_menu_button()]]),
        )
        return

    await callback.message.edit_text(
        "🛒 <b>خرید سرویس جدید</b>\n\n"
        "مدت سرویس مورد نظر را انتخاب کنید:",
        reply_markup=_period_keyboard(periods_with_plans, settings.max_connected_devices),
    )


@router.callback_query(F.data == NavSubscription.BUY)
async def dynamic_purchase_entry(callback: CallbackQuery, session: AsyncSession, user, state: FSMContext):
    await state.clear()
    await callback.answer()
    await _show_purchase_periods(callback, session, user.tg_id)


@router.callback_query(F.data.regexp(r"^service_purchase:period:\d+$"))
async def dynamic_purchase_period_selected(callback: CallbackQuery, session: AsyncSession, user):
    period_id = int(callback.data.rsplit(":", 1)[1])
    period = await ServicePeriod.get(session, period_id)
    if not period or not period.is_active or period.is_archived:
        await callback.answer("❌ این دوره دیگر فعال نیست.", show_alert=True)
        return

    plans = await ServicePurchasePlan.list_by_type(session, period.service_type)
    if not plans:
        await callback.answer("برای این دوره هنوز پلنی ثبت نشده است.", show_alert=True)
        return

    settings = await ConnectedDeviceSettings.get_or_create(session)
    data = SubscriptionData(
        state=NavSubscription.PLAN,
        user_id=user.tg_id,
        devices=settings.max_connected_devices,
    )
    await callback.answer()
    await callback.message.edit_text(
        f"📅 <b>پلن‌های {period.name}</b>\n\n"
        f"مدت پایه این دوره: <b>{period.duration_days} روز</b>\n\n"
        "لطفاً پلن مورد نظر را انتخاب کنید:",
        reply_markup=service_purchase_plan_keyboard(plans, data),
    )


@router.callback_query(F.data.regexp(r"^subscription_back_plan:\d+$"))
async def dynamic_purchase_back_to_plan(callback: CallbackQuery, session: AsyncSession, user):
    plan = await ServicePurchasePlan.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not plan:
        await callback.answer("این پلن دیگر وجود ندارد.", show_alert=True)
        return
    periods = await ServicePeriod.list_active(session)
    period = next((item for item in periods if item.service_type == plan.service_type), None)
    if not period:
        await callback.answer("این دوره دیگر فعال نیست.", show_alert=True)
        return
    plans = await ServicePurchasePlan.list_by_type(session, period.service_type)
    settings = await ConnectedDeviceSettings.get_or_create(session)
    data = SubscriptionData(state=NavSubscription.PLAN, user_id=user.tg_id, devices=settings.max_connected_devices)
    await callback.answer()
    await callback.message.edit_text(
        f"📅 <b>پلن‌های {period.name}</b>\n\nلطفاً پلن مورد نظر را انتخاب کنید:",
        reply_markup=service_purchase_plan_keyboard(plans, data),
    )
