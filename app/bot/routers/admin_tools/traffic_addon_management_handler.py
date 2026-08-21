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

router = Router(name=__name__)
PERIODS = {30: ("یکماهه", "traffic_addon_30"), 60: ("دوماهه", "traffic_addon_60"), 90: ("سه‌ماهه", "traffic_addon_90")}
LEGACY_TYPE = "traffic_addon"

class TrafficPeriodPlanState(StatesGroup):
    waiting_volume = State()
    waiting_price = State()
    waiting_edit_volume = State()
    waiting_edit_price = State()


def _back_purchase_management():
    return InlineKeyboardButton(text="🔙 مدیریت خرید سرویس", callback_data=NavAdminTools.SERVICE_PURCHASE_MANAGEMENT)


def _main_menu():
    return InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavAdminTools.MAIN)


def _period_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 مدیریت سرویس‌های یکماهه", callback_data="traffic_admin:period:30")],
        [InlineKeyboardButton(text="📅 مدیریت سرویس‌های دوماهه", callback_data="traffic_admin:period:60")],
        [InlineKeyboardButton(text="📅 مدیریت سرویس‌های سه‌ماهه", callback_data="traffic_admin:period:90")],
        [_back_purchase_management()], [_main_menu()],
    ])


def _plan_list_keyboard(plans, period_days):
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.row(InlineKeyboardButton(text=f"{plan.volume_gb:,} GB | {plan.price_toman:,} تومان", callback_data=f"traffic_admin:plan:{period_days}:{plan.id}"))
    builder.row(InlineKeyboardButton(text="➕ ساخت بسته افزایش حجم", callback_data=f"traffic_admin:create:{period_days}"))
    builder.row(InlineKeyboardButton(text="🔙 دوره‌های افزایش حجم", callback_data="traffic_admin:management"))
    builder.row(_main_menu())
    return builder.as_markup()


def _details_keyboard(plan_id, period_days):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ ویرایش حجم", callback_data=f"traffic_admin:edit_volume:{period_days}:{plan_id}")],
        [InlineKeyboardButton(text="💰 ویرایش قیمت", callback_data=f"traffic_admin:edit_price:{period_days}:{plan_id}")],
        [InlineKeyboardButton(text="🗑 حذف بسته", callback_data=f"traffic_admin:delete:{period_days}:{plan_id}")],
        [InlineKeyboardButton(text="🔙 لیست بسته‌ها", callback_data=f"traffic_admin:period:{period_days}")],
    ])


async def _get_period_plans(session: AsyncSession, period_days: int):
    _, service_type = PERIODS[period_days]
    plans = await ServicePurchasePlan.list_by_type(session, service_type)
    if period_days == 30:
        plans += await ServicePurchasePlan.list_by_type(session, LEGACY_TYPE)
    return sorted([p for p in plans if p.volume_gb > 0 and p.duration_days == 0 and p.price_toman > 0], key=lambda p: (p.volume_gb, p.price_toman, p.id))


def _valid_plan(plan, period_days):
    if not plan or plan.volume_gb <= 0 or plan.duration_days != 0 or plan.price_toman <= 0:
        return False
    expected = PERIODS[period_days][1]
    return plan.service_type == expected or (period_days == 30 and plan.service_type == LEGACY_TYPE)


@router.callback_query(F.data == "traffic_admin:management", IsAdmin())
async def traffic_addon_management_entry(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("📈 <b>مدیریت افزایش حجم</b>\n\nمدیریت بسته‌های افزایش حجم را بر اساس مدت سرویس انتخاب کنید:", reply_markup=_period_menu_keyboard())




@router.callback_query(F.data.regexp(r"^traffic_admin:period:(30|60|90)$"), IsAdmin())
async def traffic_addon_period_list(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    period_days = int(callback.data.rsplit(":", 1)[1])
    label = PERIODS[period_days][0]
    plans = await _get_period_plans(session, period_days)
    await callback.answer()
    await callback.message.edit_text(f"📈 <b>مدیریت افزایش حجم سرویس‌های {label}</b>\n\nتعداد بسته‌های فعال: <b>{len(plans)}</b>\n\nبرای ویرایش یا حذف یک بسته آن را انتخاب کنید، یا بسته جدید بسازید.", reply_markup=_plan_list_keyboard(plans, period_days))


@router.callback_query(F.data.regexp(r"^traffic_admin:create:(30|60|90)$"), IsAdmin())
async def traffic_addon_create(callback: CallbackQuery, state: FSMContext):
    period_days = int(callback.data.rsplit(":", 1)[1])
    label, service_type = PERIODS[period_days]
    await state.clear(); await state.update_data(period_days=period_days, service_type=service_type); await state.set_state(TrafficPeriodPlanState.waiting_volume)
    await callback.answer(); await callback.message.edit_text(f"➕ <b>ساخت بسته افزایش حجم {label}</b>\n\nحجم بسته را به گیگابایت وارد کنید.\nمثال: <code>10</code>")


@router.message(TrafficPeriodPlanState.waiting_volume, IsAdmin())
async def traffic_addon_volume(message: Message, state: FSMContext):
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ حجم نامعتبر است. یک عدد مثبت وارد کنید."); return
    await state.update_data(volume_gb=int(raw)); await state.set_state(TrafficPeriodPlanState.waiting_price)
    await message.answer("💰 قیمت این بسته را به تومان وارد کنید.\nمثال: <code>150000</code>")


@router.message(TrafficPeriodPlanState.waiting_price, IsAdmin())
async def traffic_addon_price(message: Message, state: FSMContext, session: AsyncSession):
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ قیمت نامعتبر است. یک عدد مثبت وارد کنید."); return
    data = await state.get_data()
    plan = ServicePurchasePlan(service_type=data["service_type"], volume_gb=int(data["volume_gb"]), duration_days=0, price_toman=int(raw))
    session.add(plan); await session.commit(); period_days = int(data["period_days"]); await state.clear()
    await message.answer(f"✅ بسته افزایش حجم {PERIODS[period_days][0]} ساخته شد.\n\n➕ {plan.volume_gb} GB\n💰 {plan.price_toman:,} تومان", reply_markup=_plan_list_keyboard(await _get_period_plans(session, period_days), period_days))


@router.callback_query(F.data.regexp(r"^traffic_admin:plan:(30|60|90):\d+$"), IsAdmin())
async def traffic_addon_details(callback: CallbackQuery, session: AsyncSession):
    _, _, period_text, plan_text = callback.data.split(":")
    period_days = int(period_text); plan = await ServicePurchasePlan.get(session, int(plan_text))
    if not _valid_plan(plan, period_days): await callback.answer("❌ بسته پیدا نشد.", show_alert=True); return
    await callback.answer(); await callback.message.edit_text(f"📈 <b>جزئیات بسته افزایش حجم {PERIODS[period_days][0]}</b>\n\n➕ حجم: <b>{plan.volume_gb} GB</b>\n💰 قیمت: <b>{plan.price_toman:,} تومان</b>\n🆔 شناسه پلن: <code>{plan.id}</code>", reply_markup=_details_keyboard(plan.id, period_days))


@router.callback_query(F.data.regexp(r"^traffic_admin:edit_volume:(30|60|90):\d+$"), IsAdmin())
async def traffic_addon_edit_volume(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    _, _, period_text, plan_text = callback.data.split(":"); period_days = int(period_text); plan = await ServicePurchasePlan.get(session, int(plan_text))
    if not _valid_plan(plan, period_days): await callback.answer("❌ بسته پیدا نشد.", show_alert=True); return
    await state.clear(); await state.update_data(traffic_plan_id=plan.id, period_days=period_days); await state.set_state(TrafficPeriodPlanState.waiting_edit_volume)
    await callback.answer(); await callback.message.edit_text(f"✏️ حجم جدید بسته <code>#{plan.id}</code> ({PERIODS[period_days][0]}) را به GB وارد کنید.\nحجم فعلی: <b>{plan.volume_gb} GB</b>")


@router.message(TrafficPeriodPlanState.waiting_edit_volume, IsAdmin())
async def traffic_addon_save_volume(message: Message, state: FSMContext, session: AsyncSession):
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0: await message.answer("❌ حجم نامعتبر است."); return
    data = await state.get_data(); plan = await ServicePurchasePlan.get(session, int(data["traffic_plan_id"]))
    if not plan or plan.duration_days != 0: await state.clear(); await message.answer("❌ بسته پیدا نشد."); return
    plan.volume_gb = int(raw); await session.commit(); period_days = int(data["period_days"]); await state.clear()
    await message.answer(f"✅ حجم بسته به <b>{plan.volume_gb} GB</b> تغییر کرد.", reply_markup=_plan_list_keyboard(await _get_period_plans(session, period_days), period_days))


@router.callback_query(F.data.regexp(r"^traffic_admin:edit_price:(30|60|90):\d+$"), IsAdmin())
async def traffic_addon_edit_price(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    _, _, period_text, plan_text = callback.data.split(":"); period_days = int(period_text); plan = await ServicePurchasePlan.get(session, int(plan_text))
    if not _valid_plan(plan, period_days): await callback.answer("❌ بسته پیدا نشد.", show_alert=True); return
    await state.clear(); await state.update_data(traffic_plan_id=plan.id, period_days=period_days); await state.set_state(TrafficPeriodPlanState.waiting_edit_price)
    await callback.answer(); await callback.message.edit_text(f"💰 قیمت جدید بسته <code>#{plan.id}</code> ({PERIODS[period_days][0]}) را به تومان وارد کنید.\nقیمت فعلی: <b>{plan.price_toman:,} تومان</b>")


@router.message(TrafficPeriodPlanState.waiting_edit_price, IsAdmin())
async def traffic_addon_save_price(message: Message, state: FSMContext, session: AsyncSession):
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0: await message.answer("❌ قیمت نامعتبر است."); return
    data = await state.get_data(); plan = await ServicePurchasePlan.get(session, int(data["traffic_plan_id"]))
    if not plan or plan.duration_days != 0: await state.clear(); await message.answer("❌ بسته پیدا نشد."); return
    plan.price_toman = int(raw); await session.commit(); period_days = int(data["period_days"]); await state.clear()
    await message.answer(f"✅ قیمت بسته به <b>{plan.price_toman:,} تومان</b> تغییر کرد.", reply_markup=_plan_list_keyboard(await _get_period_plans(session, period_days), period_days))


@router.callback_query(F.data.regexp(r"^traffic_admin:delete:(30|60|90):\d+$"), IsAdmin())
async def traffic_addon_delete(callback: CallbackQuery, session: AsyncSession):
    _, _, period_text, plan_text = callback.data.split(":"); period_days = int(period_text); plan = await ServicePurchasePlan.get(session, int(plan_text))
    if not _valid_plan(plan, period_days): await callback.answer("❌ بسته پیدا نشد.", show_alert=True); return
    await session.delete(plan); await session.commit(); await callback.answer("✅ بسته حذف شد.", show_alert=True)
    plans = await _get_period_plans(session, period_days)
    await callback.message.edit_text(f"📈 <b>مدیریت افزایش حجم سرویس‌های {PERIODS[period_days][0]}</b>\n\nتعداد بسته‌های فعال: <b>{len(plans)}</b>", reply_markup=_plan_list_keyboard(plans, period_days))
