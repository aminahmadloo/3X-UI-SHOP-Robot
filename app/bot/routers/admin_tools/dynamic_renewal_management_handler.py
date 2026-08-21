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


class RenewalPlanStates(StatesGroup):
    volume = State()
    price = State()
    edit_volume = State()
    edit_price = State()


def _home() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavAdminTools.MAIN)


def _back() -> InlineKeyboardButton:
    return InlineKeyboardButton(
        text="🔙 مدیریت خرید سرویس",
        callback_data=NavAdminTools.SERVICE_PURCHASE_MANAGEMENT,
    )


def _periods_kb(periods: list[ServicePeriod]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for p in periods:
        b.row(
            InlineKeyboardButton(
                text=f"{'🟢' if p.is_active else '🔴'} تمدید {p.months} ماهه",
                callback_data=f"srp:view:{p.id}",
            )
        )
    b.row(
        InlineKeyboardButton(
            text="➕ ایجاد دوره جدید",
            callback_data="sp:create",
        )
    )
    b.row(_back())
    b.row(_home())
    return b.as_markup()


def _details_kb(p: ServicePeriod) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(
            text="⚙️ مدیریت پلن‌های تمدید",
            callback_data=f"srp:plans:{p.id}",
        )
    )
    b.row(
        InlineKeyboardButton(
            text="🔙 دوره‌های تمدید",
            callback_data="srp:management",
        )
    )
    b.row(_back())
    return b.as_markup()


def _plans_kb(p: ServicePeriod, plans: list[ServicePurchasePlan]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for x in plans:
        b.row(
            InlineKeyboardButton(
                text=f"{x.volume_gb:,} GB | {x.duration_days} روز | {x.price_toman:,} تومان",
                callback_data=f"srp:plan:{p.id}:{x.id}",
            )
        )
    b.row(
        InlineKeyboardButton(
            text="➕ ساخت پلن تمدید جدید",
            callback_data=f"srp:create_plan:{p.id}",
        )
    )
    b.row(InlineKeyboardButton(text="🔙 جزئیات دوره", callback_data=f"srp:view:{p.id}"))
    b.row(_back())
    return b.as_markup()


def _plan_details_kb(p: ServicePeriod, x: ServicePurchasePlan) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ ویرایش", callback_data=f"srp:edit:{p.id}:{x.id}")],
            [InlineKeyboardButton(text="🗑 حذف", callback_data=f"srp:delete:{p.id}:{x.id}")],
            [InlineKeyboardButton(text="🔙 لیست پلن‌ها", callback_data=f"srp:plans:{p.id}")],
        ]
    )


async def _show(callback: CallbackQuery, session: AsyncSession) -> None:
    periods = await ServicePeriod.list_manageable(session)
    await callback.message.edit_text(
        "🔄 <b>مدیریت تمدید زمانی سرویس</b>\n\n"
        "دوره تمدید موردنظر را انتخاب کنید:",
        reply_markup=_periods_kb(periods),
    )


@router.callback_query(F.data == NavAdminTools.SERVICE_PURCHASE_RENEWAL_MANAGEMENT, IsAdmin())
async def entry(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await _show(callback, session)


@router.callback_query(F.data == "srp:management", IsAdmin())
async def management(callback: CallbackQuery, session: AsyncSession) -> None:
    await callback.answer()
    await _show(callback, session)


@router.callback_query(F.data.regexp(r"^srp:view:\d+$"), IsAdmin())
async def view(callback: CallbackQuery, session: AsyncSession) -> None:
    p = await ServicePeriod.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not p or p.is_archived:
        await callback.answer("❌ دوره پیدا نشد.", show_alert=True)
        return
    plans = await ServicePurchasePlan.list_by_type(session, p.service_type, plan_kind="renewal")
    await callback.answer()
    await callback.message.edit_text(
        f"🔄 <b>تمدید {p.months} ماهه</b>\n\n"
        f"⏱ مدت تمدید: <b>{p.duration_days} روز</b>\n"
        f"📦 تعداد پلن‌های تمدید: <b>{len(plans)}</b>\n"
        f"{'🟢 فعال' if p.is_active else '🔴 غیرفعال'}",
        reply_markup=_details_kb(p),
    )


@router.callback_query(F.data.regexp(r"^srp:plans:\d+$"), IsAdmin())
async def plans(callback: CallbackQuery, session: AsyncSession) -> None:
    p = await ServicePeriod.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not p or p.is_archived:
        await callback.answer("❌ دوره پیدا نشد.", show_alert=True)
        return
    xs = await ServicePurchasePlan.list_by_type(session, p.service_type, plan_kind="renewal")
    await callback.answer()
    await callback.message.edit_text(
        f"📦 <b>مدیریت پلن‌های تمدید {p.months} ماهه</b>\n\n"
        f"تعداد: <b>{len(xs)}</b>",
        reply_markup=_plans_kb(p, xs),
    )


@router.callback_query(F.data.regexp(r"^srp:create_plan:\d+$"), IsAdmin())
async def create_plan(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    p = await ServicePeriod.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not p or p.is_archived:
        await callback.answer("❌ دوره پیدا نشد.", show_alert=True)
        return
    await state.clear()
    await state.update_data(period_id=p.id)
    await state.set_state(RenewalPlanStates.volume)
    await callback.answer()
    await callback.message.edit_text(
        f"➕ <b>ساخت پلن تمدید {p.months} ماهه</b>\n\n"
        f"مدت تمدید به‌صورت خودکار <b>{p.duration_days} روز</b> است.\n"
        "حجم سرویس را به GB وارد کنید:"
    )


@router.message(RenewalPlanStates.volume, IsAdmin())
async def plan_volume(message: Message, state: FSMContext) -> None:
    try:
        value = int((message.text or "").replace(",", "").replace("٬", ""))
        if value <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ حجم نامعتبر است.")
        return
    await state.update_data(volume=value)
    await state.set_state(RenewalPlanStates.price)
    await message.answer("💰 قیمت تمدید را به تومان وارد کنید:")


@router.message(RenewalPlanStates.price, IsAdmin())
async def plan_price(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        price = int((message.text or "").replace(",", "").replace("٬", ""))
        if price < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ قیمت نامعتبر است.")
        return
    data = await state.get_data()
    p = await ServicePeriod.get(session, int(data["period_id"]))
    if not p or p.is_archived:
        await state.clear()
        await message.answer("❌ دوره پیدا نشد.")
        return
    x = ServicePurchasePlan(
        service_type=p.service_type,
        volume_gb=int(data["volume"]),
        duration_days=p.duration_days,
        price_toman=price,
        plan_kind="renewal",
    )
    session.add(x)
    await session.commit()
    await state.clear()
    await message.answer(
        "✅ پلن تمدید ساخته شد.",
        reply_markup=_plans_kb(
            p,
            await ServicePurchasePlan.list_by_type(session, p.service_type, plan_kind="renewal"),
        ),
    )


@router.callback_query(F.data.regexp(r"^srp:plan:\d+:\d+$"), IsAdmin())
async def plan_details(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, pid, xid = callback.data.split(":")
    p = await ServicePeriod.get(session, int(pid))
    x = await ServicePurchasePlan.get(session, int(xid))
    if not p or not x or x.service_type != p.service_type or x.plan_kind != "renewal":
        await callback.answer("❌ پلن تمدید پیدا نشد.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        f"🔄 <b>پلن تمدید {p.months} ماهه</b>\n\n"
        f"💾 حجم: <b>{x.volume_gb} GB</b>\n"
        f"⏱ مدت: <b>{x.duration_days} روز</b>\n"
        f"💰 قیمت: <b>{x.price_toman:,} تومان</b>",
        reply_markup=_plan_details_kb(p, x),
    )


@router.callback_query(F.data.regexp(r"^srp:edit:\d+:\d+$"), IsAdmin())
async def edit(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    _, _, pid, xid = callback.data.split(":")
    p = await ServicePeriod.get(session, int(pid))
    x = await ServicePurchasePlan.get(session, int(xid))
    if not p or not x or x.service_type != p.service_type or x.plan_kind != "renewal":
        await callback.answer("❌ پلن تمدید پیدا نشد.", show_alert=True)
        return
    await state.clear()
    await state.update_data(period_id=p.id, plan_id=x.id)
    await state.set_state(RenewalPlanStates.edit_volume)
    await callback.answer()
    await callback.message.edit_text(
        f"✏️ حجم فعلی: <b>{x.volume_gb} GB</b>\n\n"
        "حجم جدید را وارد کنید:"
    )


@router.message(RenewalPlanStates.edit_volume, IsAdmin())
async def edit_volume(message: Message, state: FSMContext) -> None:
    try:
        value = int((message.text or "").replace(",", "").replace("٬", ""))
        if value <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ حجم نامعتبر است.")
        return
    await state.update_data(volume=value)
    await state.set_state(RenewalPlanStates.edit_price)
    await message.answer("💰 قیمت جدید را به تومان وارد کنید:")


@router.message(RenewalPlanStates.edit_price, IsAdmin())
async def edit_price(message: Message, state: FSMContext, session: AsyncSession) -> None:
    try:
        price = int((message.text or "").replace(",", "").replace("٬", ""))
        if price < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ قیمت نامعتبر است.")
        return
    data = await state.get_data()
    p = await ServicePeriod.get(session, int(data["period_id"]))
    x = await ServicePurchasePlan.get(session, int(data["plan_id"]))
    if not p or not x or x.service_type != p.service_type or x.plan_kind != "renewal":
        await state.clear()
        await message.answer("❌ پلن تمدید پیدا نشد.")
        return
    x.volume_gb = int(data["volume"])
    x.price_toman = price
    x.duration_days = p.duration_days
    await session.commit()
    await state.clear()
    await message.answer("✅ پلن تمدید ویرایش شد.", reply_markup=_plan_details_kb(p, x))


@router.callback_query(F.data.regexp(r"^srp:delete:\d+:\d+$"), IsAdmin())
async def delete_plan(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, pid, xid = callback.data.split(":")
    p = await ServicePeriod.get(session, int(pid))
    x = await ServicePurchasePlan.get(session, int(xid))
    if not p or not x or x.service_type != p.service_type or x.plan_kind != "renewal":
        await callback.answer("❌ پلن تمدید پیدا نشد.", show_alert=True)
        return
    await session.delete(x)
    await session.commit()
    await callback.answer("✅ پلن تمدید حذف شد")
    await callback.message.edit_text(
        f"📦 <b>مدیریت پلن‌های تمدید {p.months} ماهه</b>",
        reply_markup=_plans_kb(
            p,
            await ServicePurchasePlan.list_by_type(session, p.service_type, plan_kind="renewal"),
        ),
    )
