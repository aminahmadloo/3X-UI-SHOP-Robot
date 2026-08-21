from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.routers.misc.keyboard import back_button, back_to_main_menu_button
from app.db.models import ServicePurchasePlan

router = Router(name=__name__)

PERIODS = {
    30: ("یک‌ماهه", "renewal_30"),
    60: ("دوماهه", "renewal_60"),
    90: ("سه‌ماهه", "renewal_90"),
}


class RenewalPricingState(StatesGroup):
    waiting_price = State()
    waiting_edit_price = State()


def _management_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for days, (label, _) in PERIODS.items():
        builder.row(
            InlineKeyboardButton(
                text=f"📅 مبلغ تمدید {label}",
                callback_data=f"renewal_admin:period:{days}",
            )
        )
    builder.row(back_button("admin_tools:service_purchase_management"))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def _details_keyboard(days: int, plan_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✏️ ویرایش مبلغ",
            callback_data=f"renewal_admin:edit:{days}:{plan_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🗑 حذف مبلغ",
            callback_data=f"renewal_admin:delete:{days}:{plan_id}",
        )
    )
    builder.row(InlineKeyboardButton(text="🔙 مبالغ تمدید", callback_data="renewal_admin:management"))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


async def _get_plan(session: AsyncSession, days: int) -> ServicePurchasePlan | None:
    _, service_type = PERIODS[days]
    plans = await ServicePurchasePlan.list_by_type(session, service_type)
    return plans[0] if plans else None


@router.callback_query(F.data == "renewal_admin:management", IsAdmin())
async def renewal_pricing_management(callback: CallbackQuery, session: AsyncSession) -> None:
    lines = ["🔄 <b>مدیریت مبالغ تمدید سرویس</b>", "", "مبلغ هر مدت تمدید را مستقل از حجم سرویس تعیین کنید:"]
    for days, (label, _) in PERIODS.items():
        plan = await _get_plan(session, days)
        price = f"{plan.price_toman:,} تومان" if plan else "❌ تعیین نشده"
        lines.append(f"📅 <b>{label}:</b> {price}")

    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=_management_keyboard())


@router.callback_query(F.data.regexp(r"^renewal_admin:period:(30|60|90)$"), IsAdmin())
async def renewal_pricing_period(callback: CallbackQuery, session: AsyncSession) -> None:
    days = int(callback.data.rsplit(":", 1)[1])
    label, _ = PERIODS[days]
    plan = await _get_plan(session, days)
    await callback.answer()

    if not plan:
        await callback.message.edit_text(
            f"➕ <b>مبلغ تمدید {label}</b>\n\n"
            "مبلغ تمدید این دوره هنوز تعیین نشده است.\n\n"
            "مبلغ را به تومان وارد کنید.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 مبالغ تمدید", callback_data="renewal_admin:management")],
                    [back_to_main_menu_button()],
                ]
            ),
        )
        return

    await callback.message.edit_text(
        f"🔄 <b>مبلغ تمدید {label}</b>\n\n"
        f"📅 مدت: <b>{days} روز</b>\n"
        f"💰 مبلغ فعلی: <b>{plan.price_toman:,} تومان</b>",
        reply_markup=_details_keyboard(days, plan.id),
    )


@router.callback_query(F.data.regexp(r"^renewal_admin:edit:(30|60|90):\d+$"), IsAdmin())
async def renewal_pricing_edit(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    _, _, days_text, plan_text = callback.data.split(":")
    days = int(days_text)
    plan = await ServicePurchasePlan.get(session, int(plan_text))
    if not plan or plan.service_type != PERIODS[days][1]:
        await callback.answer("❌ مبلغ تمدید پیدا نشد.", show_alert=True)
        return

    await state.clear()
    await state.update_data(plan_id=plan.id, days=days)
    await state.set_state(RenewalPricingState.waiting_edit_price)
    await callback.answer()
    await callback.message.edit_text(
        f"✏️ <b>ویرایش مبلغ تمدید {PERIODS[days][0]}</b>\n\n"
        f"مبلغ فعلی: <b>{plan.price_toman:,} تومان</b>\n\n"
        "مبلغ جدید را به تومان وارد کنید."
    )


@router.callback_query(F.data.regexp(r"^renewal_admin:delete:(30|60|90):\d+$"), IsAdmin())
async def renewal_pricing_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, days_text, plan_text = callback.data.split(":")
    days = int(days_text)
    plan = await ServicePurchasePlan.get(session, int(plan_text))
    if not plan or plan.service_type != PERIODS[days][1]:
        await callback.answer("❌ مبلغ تمدید پیدا نشد.", show_alert=True)
        return

    await session.delete(plan)
    await session.commit()
    await callback.answer("✅ مبلغ تمدید حذف شد.", show_alert=True)
    await callback.message.edit_text(
        "🔄 <b>مدیریت مبالغ تمدید سرویس</b>\n\n"
        "مبلغ حذف شد. برای تعیین مبلغ جدید، دوره مورد نظر را انتخاب کنید.",
        reply_markup=_management_keyboard(),
    )


@router.message(RenewalPricingState.waiting_edit_price, IsAdmin())
async def renewal_pricing_save_edit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ مبلغ نامعتبر است. یک عدد مثبت به تومان وارد کنید.")
        return

    data = await state.get_data()
    days = int(data["days"])
    plan = await ServicePurchasePlan.get(session, int(data["plan_id"]))
    if not plan or plan.service_type != PERIODS[days][1]:
        await state.clear()
        await message.answer("❌ مبلغ تمدید پیدا نشد.")
        return

    plan.price_toman = int(raw)
    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ مبلغ تمدید {PERIODS[days][0]} به <b>{plan.price_toman:,} تومان</b> تغییر کرد.",
        reply_markup=_management_keyboard(),
    )


@router.callback_query(F.data.regexp(r"^renewal_admin:period:(30|60|90)$"), IsAdmin())
async def renewal_pricing_period_create(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    days = int(callback.data.rsplit(":", 1)[1])
    plan = await _get_plan(session, days)
    if plan:
        return

    await state.clear()
    await state.update_data(days=days)
    await state.set_state(RenewalPricingState.waiting_price)
    await callback.answer()
    await callback.message.edit_text(
        f"➕ <b>تعیین مبلغ تمدید {PERIODS[days][0]}</b>\n\n"
        "مبلغ تمدید را به تومان وارد کنید.\n"
        "مثال: <code>150000</code>"
    )


@router.message(RenewalPricingState.waiting_price, IsAdmin())
async def renewal_pricing_save(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ مبلغ نامعتبر است. یک عدد مثبت به تومان وارد کنید.")
        return

    data = await state.get_data()
    days = int(data["days"])
    _, service_type = PERIODS[days]
    existing = await _get_plan(session, days)
    if existing:
        existing.price_toman = int(raw)
        plan = existing
    else:
        plan = ServicePurchasePlan(
            service_type=service_type,
            volume_gb=0,
            duration_days=days,
            price_toman=int(raw),
        )
        session.add(plan)

    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ مبلغ تمدید {PERIODS[days][0]} ذخیره شد: <b>{plan.price_toman:,} تومان</b>",
        reply_markup=_management_keyboard(),
    )
