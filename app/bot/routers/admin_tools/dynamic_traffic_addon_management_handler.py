from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools
from app.db.models import ServicePurchasePlan
from app.db.models.service_period import ServicePeriod

router = Router(name=__name__)


class DynamicTrafficStates(StatesGroup):
    waiting_volume = State()
    waiting_price = State()
    waiting_edit_volume = State()
    waiting_edit_price = State()


def _main():
    return InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavAdminTools.MAIN)


def _purchase():
    return InlineKeyboardButton(text="🔙 مدیریت خرید سرویس", callback_data=NavAdminTools.SERVICE_PURCHASE_MANAGEMENT)


def _periods_keyboard(periods):
    builder = InlineKeyboardBuilder()
    for period in periods:
        status = "🟢" if period.is_active else "🔴"
        builder.row(InlineKeyboardButton(text=f"{status} {period.name}", callback_data=f"traffic_dynamic:period:{period.id}"))
    builder.row(_purchase())
    builder.row(_main())
    return builder.as_markup()


def _plans_keyboard(period, plans):
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.row(InlineKeyboardButton(text=f"{plan.volume_gb:,} GB | {plan.price_toman:,} تومان", callback_data=f"traffic_dynamic:plan:{period.id}:{plan.id}"))
    builder.row(InlineKeyboardButton(text="➕ ساخت بسته افزایش حجم", callback_data=f"traffic_dynamic:create:{period.id}"))
    builder.row(InlineKeyboardButton(text="🔙 دوره‌های افزایش حجم", callback_data="traffic_dynamic:management"))
    builder.row(_main())
    return builder.as_markup()


def _details_keyboard(period, plan):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ ویرایش حجم", callback_data=f"traffic_dynamic:edit_volume:{period.id}:{plan.id}")],
        [InlineKeyboardButton(text="💰 ویرایش قیمت", callback_data=f"traffic_dynamic:edit_price:{period.id}:{plan.id}")],
        [InlineKeyboardButton(text="🗑 حذف بسته", callback_data=f"traffic_dynamic:delete:{period.id}:{plan.id}")],
        [InlineKeyboardButton(text="🔙 لیست بسته‌ها", callback_data=f"traffic_dynamic:period:{period.id}")],
    ])


async def _plans(session, period):
    result = await ServicePurchasePlan.list_by_type(session, period.traffic_addon_service_type)
    return sorted([p for p in result if p.volume_gb > 0 and p.duration_days == 0 and p.price_toman > 0], key=lambda p: (p.volume_gb, p.price_toman, p.id))


async def _show_management(callback, session):
    periods = await ServicePeriod.list_manageable(session)
    await callback.message.edit_text(
        "📈 <b>مدیریت افزایش حجم</b>\n\nمدیریت بسته‌های افزایش حجم را بر اساس مدت سرویس انتخاب کنید:",
        reply_markup=_periods_keyboard(periods),
    )


@router.callback_query(F.data == "traffic_admin:management", IsAdmin())
async def dynamic_traffic_management(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    await _show_management(callback, session)


@router.callback_query(F.data == NavAdminTools.SERVICE_PURCHASE_MANAGEMENT, IsAdmin())
async def dynamic_traffic_from_purchase(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    await _show_management(callback, session)


@router.callback_query(F.data.regexp(r"^traffic_dynamic:period:\d+$"), IsAdmin())
async def dynamic_traffic_period(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    period = await ServicePeriod.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not period or period.is_archived:
        await callback.answer("❌ دوره پیدا نشد.", show_alert=True)
        return
    plans = await _plans(session, period)
    await callback.answer()
    await callback.message.edit_text(
        f"📈 <b>مدیریت افزایش حجم {period.name}</b>\n\nتعداد بسته‌های فعال: <b>{len(plans)}</b>",
        reply_markup=_plans_keyboard(period, plans),
    )


@router.callback_query(F.data.regexp(r"^traffic_dynamic:create:\d+$"), IsAdmin())
async def dynamic_traffic_create(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    period = await ServicePeriod.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not period or period.is_archived:
        await callback.answer("❌ دوره پیدا نشد.", show_alert=True)
        return
    await state.clear()
    await state.update_data(period_id=period.id)
    await state.set_state(DynamicTrafficStates.waiting_volume)
    await callback.answer()
    await callback.message.edit_text(f"➕ <b>ساخت بسته افزایش حجم {period.name}</b>\n\nحجم بسته را به GB وارد کنید.\nمثلاً: <code>10</code>")


@router.message(DynamicTrafficStates.waiting_volume, IsAdmin())
async def dynamic_traffic_volume(message: Message, state: FSMContext):
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ حجم نامعتبر است.")
        return
    await state.update_data(volume_gb=int(raw))
    await state.set_state(DynamicTrafficStates.waiting_price)
    await message.answer("💰 قیمت بسته را به تومان وارد کنید:")


@router.message(DynamicTrafficStates.waiting_price, IsAdmin())
async def dynamic_traffic_price(message: Message, state: FSMContext, session: AsyncSession):
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ قیمت نامعتبر است.")
        return
    data = await state.get_data()
    period = await ServicePeriod.get(session, int(data["period_id"]))
    if not period or period.is_archived:
        await state.clear()
        await message.answer("❌ دوره پیدا نشد.")
        return
    plan = ServicePurchasePlan(service_type=period.traffic_addon_service_type, volume_gb=int(data["volume_gb"]), duration_days=0, price_toman=int(raw))
    session.add(plan)
    await session.commit()
    await state.clear()
    await message.answer("✅ بسته افزایش حجم ساخته شد.", reply_markup=_plans_keyboard(period, await _plans(session, period)))


@router.callback_query(F.data.regexp(r"^traffic_dynamic:plan:\d+:\d+$"), IsAdmin())
async def dynamic_traffic_plan(callback: CallbackQuery, session: AsyncSession):
    _, _, period_text, plan_text = callback.data.split(":")
    period = await ServicePeriod.get(session, int(period_text))
    plan = await ServicePurchasePlan.get(session, int(plan_text))
    if not period or not plan or plan.service_type != period.traffic_addon_service_type or plan.duration_days != 0:
        await callback.answer("❌ بسته پیدا نشد.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        f"📈 <b>جزئیات بسته افزایش حجم {period.name}</b>\n\n➕ حجم: <b>{plan.volume_gb} GB</b>\n💰 قیمت: <b>{plan.price_toman:,} تومان</b>",
        reply_markup=_details_keyboard(period, plan),
    )


@router.callback_query(F.data.regexp(r"^traffic_dynamic:edit_volume:\d+:\d+$"), IsAdmin())
async def dynamic_traffic_edit_volume(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    _, _, period_text, plan_text = callback.data.split(":")
    period = await ServicePeriod.get(session, int(period_text)); plan = await ServicePurchasePlan.get(session, int(plan_text))
    if not period or not plan or plan.service_type != period.traffic_addon_service_type:
        await callback.answer("❌ بسته پیدا نشد.", show_alert=True); return
    await state.clear(); await state.update_data(period_id=period.id, plan_id=plan.id); await state.set_state(DynamicTrafficStates.waiting_edit_volume)
    await callback.answer(); await callback.message.edit_text(f"✏️ حجم فعلی: <b>{plan.volume_gb} GB</b>\n\nحجم جدید را وارد کنید:")


@router.message(DynamicTrafficStates.waiting_edit_volume, IsAdmin())
async def dynamic_traffic_save_volume(message: Message, state: FSMContext, session: AsyncSession):
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ حجم نامعتبر است."); return
    data = await state.get_data(); period = await ServicePeriod.get(session, int(data["period_id"])); plan = await ServicePurchasePlan.get(session, int(data["plan_id"]))
    if not period or not plan or plan.service_type != period.traffic_addon_service_type:
        await state.clear(); await message.answer("❌ بسته پیدا نشد."); return
    plan.volume_gb = int(raw); await session.commit(); await state.clear()
    await message.answer("✅ حجم بسته تغییر کرد.", reply_markup=_plans_keyboard(period, await _plans(session, period)))


@router.callback_query(F.data.regexp(r"^traffic_dynamic:edit_price:\d+:\d+$"), IsAdmin())
async def dynamic_traffic_edit_price(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    _, _, period_text, plan_text = callback.data.split(":")
    period = await ServicePeriod.get(session, int(period_text)); plan = await ServicePurchasePlan.get(session, int(plan_text))
    if not period or not plan or plan.service_type != period.traffic_addon_service_type:
        await callback.answer("❌ بسته پیدا نشد.", show_alert=True); return
    await state.clear(); await state.update_data(period_id=period.id, plan_id=plan.id); await state.set_state(DynamicTrafficStates.waiting_edit_price)
    await callback.answer(); await callback.message.edit_text(f"💰 قیمت فعلی: <b>{plan.price_toman:,} تومان</b>\n\nقیمت جدید را وارد کنید:")


@router.message(DynamicTrafficStates.waiting_edit_price, IsAdmin())
async def dynamic_traffic_save_price(message: Message, state: FSMContext, session: AsyncSession):
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ قیمت نامعتبر است."); return
    data = await state.get_data(); period = await ServicePeriod.get(session, int(data["period_id"])); plan = await ServicePurchasePlan.get(session, int(data["plan_id"]))
    if not period or not plan or plan.service_type != period.traffic_addon_service_type:
        await state.clear(); await message.answer("❌ بسته پیدا نشد."); return
    plan.price_toman = int(raw); await session.commit(); await state.clear()
    await message.answer("✅ قیمت بسته تغییر کرد.", reply_markup=_plans_keyboard(period, await _plans(session, period)))


@router.callback_query(F.data.regexp(r"^traffic_dynamic:delete:\d+:\d+$"), IsAdmin())
async def dynamic_traffic_delete(callback: CallbackQuery, session: AsyncSession):
    _, _, period_text, plan_text = callback.data.split(":")
    period = await ServicePeriod.get(session, int(period_text)); plan = await ServicePurchasePlan.get(session, int(plan_text))
    if not period or not plan or plan.service_type != period.traffic_addon_service_type:
        await callback.answer("❌ بسته پیدا نشد.", show_alert=True); return
    await session.delete(plan); await session.commit(); await callback.answer("✅ بسته حذف شد")
    await callback.message.edit_text(f"📈 <b>مدیریت افزایش حجم {period.name}</b>\n\nتعداد بسته‌های فعال: <b>{len(await _plans(session, period))}</b>", reply_markup=_plans_keyboard(period, await _plans(session, period)))
