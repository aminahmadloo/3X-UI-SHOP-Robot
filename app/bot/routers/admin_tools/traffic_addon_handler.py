from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools
from app.db.models import ServicePurchasePlan

router = Router(name=__name__)
TRAFFIC_ADDON_TYPE = "traffic_addon"


class TrafficPlanState(StatesGroup):
    waiting_volume = State()
    waiting_price = State()
    waiting_edit_volume = State()
    waiting_edit_price = State()


def _back_main() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="🔙 مدیریت خرید سرویس", callback_data=NavAdminTools.SERVICE_PURCHASE_MANAGEMENT)


def _traffic_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ ساخت بسته افزایش حجم", callback_data="traffic_admin:create")],
            [_back_main()],
            [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavAdminTools.MAIN)],
        ]
    )


def _plan_list_keyboard(plans: list[ServicePurchasePlan]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.row(
            InlineKeyboardButton(
                text=f"{plan.volume_gb} GB | {plan.price_toman:,} تومان",
                callback_data=f"traffic_admin:plan:{plan.id}",
            )
        )
    builder.row(InlineKeyboardButton(text="➕ ساخت بسته افزایش حجم", callback_data="traffic_admin:create"))
    builder.row(_back_main())
    builder.row(InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavAdminTools.MAIN))
    return builder.as_markup()


def _plan_details_keyboard(plan_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ ویرایش حجم", callback_data=f"traffic_admin:edit_volume:{plan_id}")],
            [InlineKeyboardButton(text="💰 ویرایش قیمت", callback_data=f"traffic_admin:edit_price:{plan_id}")],
            [InlineKeyboardButton(text="🗑 حذف بسته", callback_data=f"traffic_admin:delete:{plan_id}")],
            [InlineKeyboardButton(text="🔙 لیست بسته‌ها", callback_data="traffic_admin:list")],
        ]
    )


async def _show_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    plans = await ServicePurchasePlan.list_by_type(session, TRAFFIC_ADDON_TYPE)
    plans = [p for p in plans if p.volume_gb > 0 and p.duration_days == 0]
    plans.sort(key=lambda p: (p.volume_gb, p.price_toman, p.id))
    await callback.message.edit_text(
        "📈 <b>مدیریت افزایش حجم</b>\n\n"
        f"تعداد بسته‌های فعال: <b>{len(plans)}</b>\n\n"
        "از لیست زیر یک بسته را برای ویرایش یا حذف انتخاب کنید، یا بسته جدید بسازید.",
        reply_markup=_plan_list_keyboard(plans),
    )




@router.callback_query(F.data == "traffic_admin:list", IsAdmin())
async def traffic_addon_list(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _show_menu(callback, session)


@router.callback_query(F.data.regexp(r"^traffic_admin:plan:\d+$"), IsAdmin())
async def traffic_addon_details(callback: CallbackQuery, session: AsyncSession) -> None:
    plan = await ServicePurchasePlan.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not plan or plan.service_type != TRAFFIC_ADDON_TYPE:
        await callback.answer("❌ بسته پیدا نشد.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "📈 <b>جزئیات بسته افزایش حجم</b>\n\n"
        f"➕ حجم: <b>{plan.volume_gb} GB</b>\n"
        f"💰 قیمت: <b>{plan.price_toman:,} تومان</b>\n"
        f"🆔 شناسه پلن: <code>{plan.id}</code>",
        reply_markup=_plan_details_keyboard(plan.id),
    )


@router.callback_query(F.data == "traffic_admin:create", IsAdmin())
async def traffic_addon_create(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(TrafficPlanState.waiting_volume)
    await callback.answer()
    await callback.message.edit_text(
        "➕ <b>ساخت بسته افزایش حجم</b>\n\n"
        "حجم بسته را به گیگابایت وارد کنید.\nمثال: <code>10</code>"
    )


@router.message(TrafficPlanState.waiting_volume, IsAdmin())
async def traffic_addon_volume(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ حجم نامعتبر است. یک عدد مثبت وارد کنید.")
        return
    await state.update_data(traffic_volume=int(raw))
    await state.set_state(TrafficPlanState.waiting_price)
    await message.answer("💰 قیمت این بسته را به تومان وارد کنید.\nمثال: <code>150000</code>")


@router.message(TrafficPlanState.waiting_price, IsAdmin())
async def traffic_addon_price(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ قیمت نامعتبر است. یک عدد مثبت وارد کنید.")
        return
    data = await state.get_data()
    volume = int(data["traffic_volume"])
    price = int(raw)
    plan = ServicePurchasePlan(
        service_type=TRAFFIC_ADDON_TYPE,
        volume_gb=volume,
        duration_days=0,
        price_toman=price,
    )
    session.add(plan)
    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ بسته افزایش حجم ساخته شد.\n\n➕ {volume} GB\n💰 {price:,} تومان"
    )


@router.callback_query(F.data.regexp(r"^traffic_admin:edit_volume:\d+$"), IsAdmin())
async def traffic_addon_edit_volume(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    plan_id = int(callback.data.rsplit(":", 1)[1])
    plan = await ServicePurchasePlan.get(session, plan_id)
    if not plan or plan.service_type != TRAFFIC_ADDON_TYPE:
        await callback.answer("❌ بسته پیدا نشد.", show_alert=True)
        return
    await state.clear()
    await state.update_data(traffic_plan_id=plan.id)
    await state.set_state(TrafficPlanState.waiting_edit_volume)
    await callback.answer()
    await callback.message.edit_text(f"✏️ حجم جدید بسته <code>#{plan.id}</code> را به GB وارد کنید.\nحجم فعلی: <b>{plan.volume_gb} GB</b>")


@router.message(TrafficPlanState.waiting_edit_volume, IsAdmin())
async def traffic_addon_save_volume(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ حجم نامعتبر است.")
        return
    data = await state.get_data()
    plan = await ServicePurchasePlan.get(session, int(data["traffic_plan_id"]))
    if not plan or plan.service_type != TRAFFIC_ADDON_TYPE:
        await state.clear()
        await message.answer("❌ بسته پیدا نشد.")
        return
    plan.volume_gb = int(raw)
    await session.commit()
    await state.clear()
    await message.answer(f"✅ حجم بسته به <b>{plan.volume_gb} GB</b> تغییر کرد.")


@router.callback_query(F.data.regexp(r"^traffic_admin:edit_price:\d+$"), IsAdmin())
async def traffic_addon_edit_price(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    plan_id = int(callback.data.rsplit(":", 1)[1])
    plan = await ServicePurchasePlan.get(session, plan_id)
    if not plan or plan.service_type != TRAFFIC_ADDON_TYPE:
        await callback.answer("❌ بسته پیدا نشد.", show_alert=True)
        return
    await state.clear()
    await state.update_data(traffic_plan_id=plan.id)
    await state.set_state(TrafficPlanState.waiting_edit_price)
    await callback.answer()
    await callback.message.edit_text(f"💰 قیمت جدید بسته <code>#{plan.id}</code> را به تومان وارد کنید.\nقیمت فعلی: <b>{plan.price_toman:,} تومان</b>")


@router.message(TrafficPlanState.waiting_edit_price, IsAdmin())
async def traffic_addon_save_price(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ قیمت نامعتبر است.")
        return
    data = await state.get_data()
    plan = await ServicePurchasePlan.get(session, int(data["traffic_plan_id"]))
    if not plan or plan.service_type != TRAFFIC_ADDON_TYPE:
        await state.clear()
        await message.answer("❌ بسته پیدا نشد.")
        return
    plan.price_toman = int(raw)
    await session.commit()
    await state.clear()
    await message.answer(f"✅ قیمت بسته به <b>{plan.price_toman:,} تومان</b> تغییر کرد.")


@router.callback_query(F.data.regexp(r"^traffic_admin:delete:\d+$"), IsAdmin())
async def traffic_addon_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    plan = await ServicePurchasePlan.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not plan or plan.service_type != TRAFFIC_ADDON_TYPE:
        await callback.answer("❌ بسته پیدا نشد.", show_alert=True)
        return
    await session.delete(plan)
    await session.commit()
    await callback.answer("✅ بسته حذف شد.", show_alert=True)
    await _show_menu(callback, session)
