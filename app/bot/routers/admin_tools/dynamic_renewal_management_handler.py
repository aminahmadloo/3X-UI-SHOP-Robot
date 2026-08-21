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
from app.db.models.service_period import ServicePeriod

router = Router(name=__name__)



class RenewalPricingState(StatesGroup):
    waiting_price = State()
    waiting_edit_price = State()


async def _management_keyboard(session: AsyncSession) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    periods = await ServicePeriod.list_manageable(session)

    for p in periods:
        builder.row(
            InlineKeyboardButton(
                text=f"📅 مبلغ افزایش زمان {p.name.replace('سرویس‌های ', '')}",
                callback_data=f"renewal_admin:period:{p.id}",
            )
        )
    builder.row(back_button("admin_tools:service_purchase_management"))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def _details_keyboard(period_id: int, plan_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✏️ ویرایش مبلغ",
            callback_data=f"renewal_admin:edit:{period_id}:{plan_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🗑 حذف مبلغ",
            callback_data=f"renewal_admin:delete:{period_id}:{plan_id}",
        )
    )
    builder.row(InlineKeyboardButton(text="🔙 مبالغ افزایش زمان", callback_data="renewal_admin:management"))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


async def _get_period(session: AsyncSession, period_id: int):
    return await ServicePeriod.get(session, period_id)


async def _get_plan(session: AsyncSession, period_id: int) -> ServicePurchasePlan | None:
    period = await _get_period(session, period_id)
    if not period:
        return None
    plans = await ServicePurchasePlan.list_by_type(session, period.service_type)
    plans = [x for x in plans if x.volume_gb == 0 and x.duration_days > 0]
    return plans[0] if plans else None


@router.callback_query(F.data == "renewal_admin:management", IsAdmin())
async def renewal_pricing_management(callback: CallbackQuery, session: AsyncSession) -> None:
    lines = ["⏳ <b>تنظیمات افزایش زمان سرویس</b>", "", "مبلغ هر مدت افزایش زمان سرویس را مستقل از حجم سرویس تعیین کنید:"]
    periods = await ServicePeriod.list_manageable(session)

    for p in periods:
        plan = await _get_plan(session, p.id)
        price = f"{plan.price_toman:,} تومان" if plan else "❌ تعیین نشده"
        lines.append(f"📅 <b>{p.name.replace('سرویس‌های ','')}:</b> {price}")

    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=await _management_keyboard(session))


@router.callback_query(F.data.regexp(r"^renewal_admin:period:\d+$"), IsAdmin())
async def renewal_pricing_period(callback: CallbackQuery, session: AsyncSession) -> None:
    period_id = int(callback.data.rsplit(":", 1)[1])
    period = await ServicePeriod.get(session, period_id)
    if not period:
        await callback.answer("❌ دوره پیدا نشد.", show_alert=True)
        return

    label = period.name.replace("سرویس‌های ","")
    plan = await _get_plan(session, period_id)
    await callback.answer()

    if not plan:
        await callback.message.edit_text(
            f"➕ <b>مبلغ افزایش زمان {label}</b>\n\n"
            "مبلغ افزایش زمان این دوره هنوز تعیین نشده است.\n\n"
            "مبلغ را به تومان وارد کنید.",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 مبالغ افزایش زمان", callback_data="renewal_admin:management")],
                    [back_to_main_menu_button()],
                ]
            ),
        )
        return

    await callback.message.edit_text(
        f"⏳ <b>مبلغ افزایش زمان {label}</b>\n\n"
        f"📅 مدت: <b>{period.duration_days} روز</b>\n"
        f"💰 مبلغ فعلی: <b>{plan.price_toman:,} تومان</b>",
        reply_markup=_details_keyboard(period_id, plan.id),
    )


@router.callback_query(F.data.regexp(r"^renewal_admin:edit:\d+:\d+$"), IsAdmin())
async def renewal_pricing_edit(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    _, _, period_text, plan_text = callback.data.split(":")
    period_id = int(period_text)
    plan = await ServicePurchasePlan.get(session, int(plan_text))
    if not plan or plan.service_type != await _get_period(session, period_id).service_type:
        await callback.answer("❌ مبلغ افزایش زمان پیدا نشد.", show_alert=True)
        return

    await state.clear()
    await state.update_data(plan_id=plan.id, period_id=period_id)
    await state.set_state(RenewalPricingState.waiting_edit_price)
    await callback.answer()
    await callback.message.edit_text(
        f"✏️ <b>ویرایش مبلغ افزایش زمان {period.name.replace('سرویس‌های ','')}</b>\n\n"
        f"مبلغ فعلی: <b>{plan.price_toman:,} تومان</b>\n\n"
        "مبلغ جدید را به تومان وارد کنید."
    )


@router.callback_query(F.data.regexp(r"^renewal_admin:delete:\d+:\d+$"), IsAdmin())
async def renewal_pricing_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, period_text, plan_text = callback.data.split(":")
    period_id = int(period_text)
    plan = await ServicePurchasePlan.get(session, int(plan_text))
    if not plan or plan.service_type != await _get_period(session, period_id).service_type:
        await callback.answer("❌ مبلغ افزایش زمان پیدا نشد.", show_alert=True)
        return

    await session.delete(plan)
    await session.commit()
    await callback.answer("✅ مبلغ افزایش زمان حذف شد.", show_alert=True)
    await callback.message.edit_text(
        "⏳ <b>تنظیمات افزایش زمان سرویس</b>\n\n"
        "مبلغ حذف شد. برای تعیین مبلغ جدید، دوره مورد نظر را انتخاب کنید.",
        reply_markup=await _management_keyboard(session),
    )


@router.message(RenewalPricingState.waiting_edit_price, IsAdmin())
async def renewal_pricing_save_edit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ مبلغ نامعتبر است. یک عدد مثبت به تومان وارد کنید.")
        return

    data = await state.get_data()
    period_id = int(data["period_id"])
    period = await ServicePeriod.get(session, period_id)
    plan = await ServicePurchasePlan.get(session, int(data["plan_id"]))
    if not plan or plan.service_type != await _get_period(session, period_id).service_type:
        await state.clear()
        await message.answer("❌ مبلغ افزایش زمان پیدا نشد.")
        return

    plan.price_toman = int(raw)
    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ مبلغ افزایش زمان {period.name.replace('سرویس‌های ','')} به <b>{plan.price_toman:,} تومان</b> تغییر کرد.",
        reply_markup=await _management_keyboard(session),
    )


@router.message(RenewalPricingState.waiting_price, IsAdmin())
async def renewal_pricing_save(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    if not raw.isdigit() or int(raw) <= 0:
        await message.answer("❌ مبلغ نامعتبر است. یک عدد مثبت به تومان وارد کنید.")
        return

    data = await state.get_data()
    period_id = int(data["period_id"])
    period = await ServicePeriod.get(session, period_id)
    service_type = period.service_type
    existing = await _get_plan(session, period_id)
    if existing:
        existing.price_toman = int(raw)
        plan = existing
    else:
        plan = ServicePurchasePlan(
            service_type=service_type,
            volume_gb=0,
            duration_days=period.duration_days,
            price_toman=int(raw),
        )
        session.add(plan)

    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ مبلغ افزایش زمان {period.name.replace('سرویس‌های ','')} ذخیره شد: <b>{plan.price_toman:,} تومان</b>",
        reply_markup=await _management_keyboard(session),
    )
