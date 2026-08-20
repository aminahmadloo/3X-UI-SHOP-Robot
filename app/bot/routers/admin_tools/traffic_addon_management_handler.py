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

PERIODS = {
    30: ("یکماهه", "traffic_addon_30"),
    60: ("دوماهه", "traffic_addon_60"),
    90: ("سه‌ماهه", "traffic_addon_90"),
}
LEGACY_TYPE = "traffic_addon"


class TrafficPeriodPlanState(StatesGroup):
    waiting_volume = State()
    waiting_price = State()
    waiting_edit_volume = State()
    waiting_edit_price = State()


def _back_purchase_management() -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text="🔙 مدیریت خرید سرویس",
        callback_data=NavAdminTools.SERVICE_PURCHASE_MANAGEMENT,
    )


def _main_menu() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavAdminTools.MAIN)


def _period_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📅 مدیریت سرویس‌های یکماهه", callback_data="traffic_admin:period:30")],
            [InlineKeyboardButton(text="📅 مدیریت سرویس‌های دوماهه", callback_data="traffic_admin:period:60")],
            [InlineKeyboardButton(text="📅 مدیریت سرویس‌های سه‌ماهه", callback_data="traffic_admin:period:90")],
            [_back_purchase_management()],
            [_main_menu()],
        ]
    )


def _plan_list_keyboard(plans: list[ServicePurchasePlan], period_days: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.row(
            InlineKeyboardButton(
                text=f"{plan.volume_gb:,} GB | {plan.price_toman:,} تومان",
                callback_data=f"traffic_admin:plan:{period_days}:{plan.id}",
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="➕ ساخت بسته افزایش حجم",
            callback_data=f"traffic_admin:create:{period_days}",
        )
    )
    builder.row(
        InlineKeyboardButton(text="🔙 دوره‌های افزایش حجم", callback_data="traffic_admin:management")
    )
    builder.row(_main_menu())
    return builder.as_markup()


def _details_keyboard(plan_id: int, period_days: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ ویرایش حجم", callback_data=f"traffic_admin:edit_volume:{period_days}:{plan_id}")],
            [InlineKeyboardButton(text="💰 ویرایش قیمت", callback_data=f"traffic_admin:edit_price:{period_days}:{plan_id}")],
            [InlineKeyboardButton(text="🗑 حذف بسته", callback_data=f"traffic_admin:delete:{period_days}:{plan_id}")],
            [InlineKeyboardButton(text="🔙 لیست بسته‌ها", callback_data=f"traffic_admin:period:{period_days}")],
        ]
    )


async def _get_period_plans(session: AsyncSession, period_days: int) -> list[ServicePurchasePlan]:
    _label, service_type = PERIODS[period_days]
    plans = await ServicePurchasePlan.list_by_type(session, service_type)

    # Preserve the packages created by the previous traffic_addon implementation.
    # They are treated as one-month packages until the admin edits/recreates them.
    if period_days == 30:
        plans += await ServicePurchasePlan.list_by_type(session, LEGACY_TYPE)

    plans = [p for p in plans if p.volume_gb > 0 and p.duration_days == 0 and p.price_toman > 0]
    plans.sort(key=lambda p: (p.volume_gb, p.price_toman, p.id))
    return plans


@router.callback_query(F.data == "traffic_admin:management", IsAdmin())
async def traffic_addon_management_entry(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "📈 <b>مدیریت افزایش حجم</b>\n\n"
        "مدیریت بسته‌های افزایش حجم را بر اساس مدت سرویس انتخاب کنید:",
        reply_markup=_period_menu_keyboard(),
    )


@router.callback_query(F.data == NavAdminTools.SERVICE_PURCHASE_MANAGEMENT, IsAdmin())
async def traffic_addon_management_from_purchase_menu(callback: CallbackQuery) -> None:
    # This handler is imported before admin_tools_handler, so the traffic-management
    # submenu becomes the first screen after entering Service Purchase Management.
    await callback.answer()
    await callback.message.edit_text(
        "🛒 <b>مدیریت خرید سرویس</b>\n\n"
        "لطفاً بخش مورد نظر را انتخاب کنید:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📅 مدیریت سرویس‌های یک ماهه", callback_data=NavAdminTools.SERVICE_PURCHASE_ONE_MONTH)],
                [InlineKeyboardButton(text="📅 مدیریت سرویس‌های سه ماهه", callback_data=NavAdminTools.SERVICE_PURCHASE_THREE_MONTH)],
                [InlineKeyboardButton(text="📈 مدیریت افزایش حجم", callback_data="traffic_admin:management")],
                [InlineKeyboardButton(text="📱 مدیریت تعداد دستگاه متصل", callback_data=NavAdminTools.SERVICE_PURCHASE_DEVICES)],
                [_back_purchase_management()],
                [_main_menu()],
            ]
        ),
    )


@router.callback_query(F.data.regexp(r"^traffic_admin:period:(30|60|90)$"), IsAdmin())
async def traffic_addon_period_list(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    period_days = int(callback.data.rsplit(":", 1)[1])
    label, _ = PERIODS[period_days]
    plans = await _get_period_plans(session, period_days)
    await callback.answer()
    await callback.message.edit_text(
        f"📈 <b>مدیریت افزایش حجم سرویس‌های {label}</b>\n\n"
        f"تعداد بسته‌های فعال: <b>{len(plans)}</b>\n\n"
        "برای ویرایش یا حذف یک بسته آن را انتخاب کنید، یا بسته جدید بسازید.",
        reply_markup=_plan_list_keyboard(plans, period_days),
    )


@router.callback_query(F.data.regexp(r"^traffic_admin:create:(30|60|90)$"), IsAdmin())
async def traffic_addon_create(callback: CallbackQuery, state: FSMContext) -> None:
    period_days = int(callback.data.rsplit(":", 1)[1])
    label, service_type = PERIODS[period_days]
    await state.clear()
    await state.update_data(period_days=period_days, service_type=service_type)
    await state.set_state(TrafficPeriodPlanState.waiting_volume)
    await callback.answer()
    await callback.message.edit_text(
        f"➕ <b>ساخت بسته افزایش حجم {label}</b>\n\n"
        "حجم بسته را به گیگابایت وارد کنید.\nمثال: <code>10</code>"
    )


@router.message(TrafficPeriodPlanState.waiting_volume, IsAdmin())
async def traffic_addon_volume(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ حجم نامعتبر است. یک عدد مثبت وارد کنید.")
        return
    await state.update_data(volume_gb=int(raw))
    await state.set_state(TrafficPeriodPlanState.waiting_price)
    await message.answer("💰 قیمت این بسته را به تومان وارد کنید.\nمثال: <code>150000</code>")


@router.message(TrafficPeriodPlanState.waiting_price, IsAdmin())
async def traffic_addon_price(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ قیمت نامعتبر است. یک عدد مثبت وارد کنید.")
        return
    data = await state.get_data()
    plan = ServicePurchasePlan(
        service_type=data["service_type"],
        volume_gb=int(data["volume_gb"]),
        duration_days=0,
        price_toman=int(raw),
    )
    session.add(plan)
    await session.commit()
    period_days = int(data["period_days"])
    await state.clear()
    await message.answer(
        f"✅ بسته افزایش حجم {PERIODS[period_days][0]} ساخته شد.\n\n"
        f"➕ {plan.volume_gb} GB\n💰 {plan.price_toman:,} تومان",
        reply_markup=_plan_list_keyboard(await _get_period_plans(session, period_days), period_days),
    )


@router.callback_query(F.data.regexp(r"^traffic_admin:plan:(30|60|90):\d+$"), IsAdmin())
async def traffic_addon_details(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, _, period_text, plan_text = callback.data.split(":")
    period_days = int(period_text)
    plan = await ServicePurchasePlan.get(session, int(plan_text))
    label, expected_type = PERIODS[period_days]
    valid = plan and plan.volume_gb > 0 and plan.duration_days == 0 and plan.price_toman > 0 and (
        plan.service_type == expected_type or (period_days == 30 and plan.service_type == LEGACY_TYPE)
    )
    if not valid:
        await callback.answer("❌ بسته پیدا نشد.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        f"📈 <b>جزئیات بسته افزایش حجم {label}</b>\n\n"
        f"➕ حجم: <b>{plan.volume_gb} GB</b>\n"
        f"💰 قیمت: <b>{plan.price_toman:,} تومان</b>\n"
        f"🆔 شناسه پلن: <code>{plan.id}</code>",
        reply_markup=_details_keyboard(plan.id, period_days),
    )


@router.callback_query(F.data.regexp(r"^traffic_admin:edit_volume:(30|60|90):\d+$"), IsAdmin())
async def traffic_addon_edit_volume(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    _, _, _, period_text, plan_text = callback.data.split(":")
    period_days = int(period_text)
    plan = await ServicePurchasePlan.get(session, int(plan_text))
    label, expected_type = PERIODS[period_days]
    if not plan or plan.duration_days != 0 or plan.service_type not in {expected_type, LEGACY_TYPE if period_days == 30 else expected_type}:
        await callback.answer("❌ بسته پیدا نشد.", show_alert=True)
        return
    await state.clear()
    await state.update_data(traffic_plan_id=plan.id, period_days=period_days)
    await state.set_state(TrafficPeriodPlanState.waiting_edit_volume)
    await callback.answer()
    await callback.message.edit_text(
        f"✏️ حجم جدید بسته <code>#{plan.id}</code> ({label}) را به GB وارد کنید.\n"
        f"حجم فعلی: <b>{plan.volume_gb} GB</b>"
    )


@router.message(TrafficPeriodPlanState.waiting_edit_volume, IsAdmin())
async def traffic_addon_save_volume(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ حجم نامعتبر است.")
        return
    data = await state.get_data()
    plan = await ServicePurchasePlan.get(session, int(data["traffic_plan_id"]))
    if not plan or plan.duration_days != 0:
        await state.clear()
        await message.answer("❌ بسته پیدا نشد.")
        return
    plan.volume_gb = int(raw)
    await session.commit()
    period_days = int(data["period_days"])
    await state.clear()
    await message.answer(
        f"✅ حجم بسته به <b>{plan.volume_gb} GB</b> تغییر کرد.",
        reply_markup=_plan_list_keyboard(await _get_period_plans(session, period_days), period_days),
    )


@router.callback_query(F.data.regexp(r"^traffic_admin:edit_price:(30|60|90):\d+$"), IsAdmin())
async def traffic_addon_edit_price(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    _, _, _, period_text, plan_text = callback.data.split(":")
    period_days = int(period_text)
    plan = await ServicePurchasePlan.get(session, int(plan_text))
    label, expected_type = PERIODS[period_days]
    if not plan or plan.duration_days != 0 or plan.service_type not in {expected_type, LEGACY_TYPE if period_days == 30 else expected_type}:
        await callback.answer("❌ بسته پیدا نشد.", show_alert=True)
        return
    await state.clear()
    await state.update_data(traffic_plan_id=plan.id, period_days=period_days)
    await state.set_state(TrafficPeriodPlanState.waiting_edit_price)
    await callback.answer()
    await callback.message.edit_text(
        f"💰 قیمت جدید بسته <code>#{plan.id}</code> ({label}) را به تومان وارد کنید.\n"
        f"قیمت فعلی: <b>{plan.price_toman:,} تومان</b>"
    )


@router.message(TrafficPeriodPlanState.waiting_edit_price, IsAdmin())
async def traffic_addon_save_price(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ قیمت نامعتبر است.")
        return
    data = await state.get_data()
    plan = await ServicePurchasePlan.get(session, int(data["traffic_plan_id"]))
    if not plan or plan.duration_days != 0:
        await state.clear()
        await message.answer("❌ بسته پیدا نشد.")
        return
    plan.price_toman = int(raw)
    await session.commit()
    period_days = int(data["period_days"])
    await state.clear()
    await message.answer(
        f"✅ قیمت بسته به <b>{plan.price_toman:,} تومان</b> تغییر کرد.",
        reply_markup=_plan_list_keyboard(await _get_period_plans(session, period_days), period_days),
    )


@router.callback_query(F.data.regexp(r"^traffic_admin:delete:(30|60|90):\d+$"), IsAdmin())
async def traffic_addon_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, _, period_text, plan_text = callback.data.split(":")
    period_days = int(period_text)
    plan = await ServicePurchasePlan.get(session, int(plan_text))
    label, expected_type = PERIODS[period_days]
    if not plan or plan.duration_days != 0 or plan.service_type not in {expected_type, LEGACY_TYPE if period_days == 30 else expected_type}:
        await callback.answer("❌ بسته پیدا نشد.", show_alert=True)
        return
    await session.delete(plan)
    await session.commit()
    await callback.answer("✅ بسته حذف شد.", show_alert=True)
    await callback.message.edit_text(
        f"📈 <b>مدیریت افزایش حجم سرویس‌های {label}</b>\n\n"
        f"تعداد بسته‌های فعال: <b>{len(await _get_period_plans(session, period_days))}</b>",
        reply_markup=_plan_list_keyboard(await _get_period_plans(session, period_days), period_days),
    )
