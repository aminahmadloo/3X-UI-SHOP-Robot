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


class DynamicPeriodStates(StatesGroup):
    waiting_months = State()
    waiting_plan_volume = State()
    waiting_plan_price = State()
    waiting_edit_volume = State()
    waiting_edit_price = State()


def _main_menu_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavAdminTools.MAIN)


def _purchase_management_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text="🔙 مدیریت خرید سرویس", callback_data=NavAdminTools.SERVICE_PURCHASE_MANAGEMENT)


def _period_label(period: ServicePeriod) -> str:
    return period.name


def _period_list_keyboard(periods: list[ServicePeriod]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for period in periods:
        status = "🟢" if period.is_active else "🔴"
        builder.row(
            InlineKeyboardButton(
                text=f"{status} {period.name}",
                callback_data=f"service_period:view:{period.id}",
            )
        )
    builder.row(InlineKeyboardButton(text="➕ ایجاد مدیریت سرویس جدید", callback_data="service_period:create"))
    builder.row(_purchase_management_button())
    builder.row(_main_menu_button())
    return builder.as_markup()


def _period_details_keyboard(period: ServicePeriod) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    toggle_text = "🔴 غیرفعال کردن" if period.is_active else "🟢 فعال کردن"
    builder.row(InlineKeyboardButton(text=toggle_text, callback_data=f"service_period:toggle:{period.id}"))
    builder.row(InlineKeyboardButton(text="⚙️ مدیریت پلن‌ها", callback_data=f"service_period:plans:{period.id}"))
    builder.row(InlineKeyboardButton(text="🗑 حذف / آرشیو دوره", callback_data=f"service_period:archive:{period.id}"))
    builder.row(InlineKeyboardButton(text="🔙 دوره‌های سرویس", callback_data="service_period:management"))
    builder.row(_purchase_management_button())
    return builder.as_markup()


def _plan_list_keyboard(period: ServicePeriod, plans: list[ServicePurchasePlan]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.row(
            InlineKeyboardButton(
                text=f"{plan.volume_gb:,} GB | {plan.price_toman:,} تومان | {plan.duration_days} روز",
                callback_data=f"service_period:plan:{period.id}:{plan.id}",
            )
        )
    builder.row(InlineKeyboardButton(text="➕ ساخت سرویس جدید", callback_data=f"service_period:create_plan:{period.id}"))
    builder.row(InlineKeyboardButton(text="🔙 جزئیات دوره", callback_data=f"service_period:view:{period.id}"))
    builder.row(_purchase_management_button())
    return builder.as_markup()


def _plan_details_keyboard(period: ServicePeriod, plan: ServicePurchasePlan) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ ویرایش", callback_data=f"service_period:edit_plan:{period.id}:{plan.id}")],
            [InlineKeyboardButton(text="🗑 حذف", callback_data=f"service_period:delete_plan:{period.id}:{plan.id}")],
            [InlineKeyboardButton(text="🔙 لیست پلن‌ها", callback_data=f"service_period:plans:{period.id}")],
        ]
    )


async def _show_period_management(callback: CallbackQuery, session: AsyncSession) -> None:
    periods = await ServicePeriod.list_manageable(session)
    await callback.message.edit_text(
        "🛒 <b>مدیریت خرید سرویس</b>\n\n"
        "📅 <b>مدیریت دوره‌های سرویس</b>\n\n"
        "دوره فعال را انتخاب کنید یا برای اضافه‌کردن یک دوره جدید روی «ایجاد مدیریت سرویس جدید» بزنید.",
        reply_markup=_period_list_keyboard(periods),
    )


@router.callback_query(F.data == NavAdminTools.SERVICE_PURCHASE_MANAGEMENT, IsAdmin())
async def dynamic_service_period_management(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    await callback.answer()
    await _show_period_management(callback, session)


@router.callback_query(F.data == "service_period:management", IsAdmin())
async def dynamic_service_period_management_back(callback: CallbackQuery, session: AsyncSession, state: FSMContext):
    await state.clear()
    await callback.answer()
    await _show_period_management(callback, session)


@router.callback_query(F.data == "service_period:create", IsAdmin())
async def dynamic_service_period_create(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(DynamicPeriodStates.waiting_months)
    await callback.answer()
    await callback.message.edit_text(
        "➕ <b>ایجاد مدیریت سرویس جدید</b>\n\n"
        "تعداد ماه دوره جدید را وارد کنید.\n"
        "مثلاً: <code>2</code> برای سرویس دوماهه\n\n"
        "سیستم نام، مدت روز، نوع سرویس و نوع بسته‌های افزایش حجم این دوره را به‌صورت خودکار ایجاد می‌کند."
    )


@router.message(DynamicPeriodStates.waiting_months, IsAdmin())
async def dynamic_service_period_save(message: Message, state: FSMContext, session: AsyncSession):
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    try:
        months = int(raw)
        if months <= 0 or months > 120:
            raise ValueError
    except ValueError:
        await message.answer("❌ مدت نامعتبر است. یک عدد صحیح بین 1 تا 120 ماه وارد کنید.")
        return

    existing = await ServicePeriod.get_by_months(session, months)
    if existing:
        await message.answer("❌ این دوره قبلاً ایجاد شده است.")
        return

    if months == 1:
        service_type = "one_month"
        traffic_type = "traffic_addon_30"
    elif months == 3:
        service_type = "three_month"
        traffic_type = "traffic_addon_90"
    else:
        service_type = f"period_{months}m"
        traffic_type = f"traffic_addon_{months}m"

    period = ServicePeriod(
        name=f"سرویس‌های {months}ماهه",
        months=months,
        duration_days=months * 30,
        service_type=service_type,
        traffic_addon_service_type=traffic_type,
        is_active=True,
        is_archived=False,
        sort_order=months,
    )
    session.add(period)
    await session.commit()
    await state.clear()

    await message.answer(
        "✅ <b>مدیریت سرویس جدید ایجاد شد.</b>\n\n"
        f"📅 دوره: <b>{period.name}</b>\n"
        f"⏱ مدت پایه: <b>{period.duration_days} روز</b>\n"
        "🟢 وضعیت: <b>فعال</b>\n\n"
        "حالا می‌توانید پلن‌های این دوره و بسته‌های افزایش حجم آن را مدیریت کنید.",
        reply_markup=_period_details_keyboard(period),
    )


@router.callback_query(F.data.regexp(r"^service_period:view:\d+$"), IsAdmin())
async def dynamic_service_period_view(callback: CallbackQuery, session: AsyncSession):
    period = await ServicePeriod.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not period or period.is_archived:
        await callback.answer("❌ این دوره دیگر وجود ندارد.", show_alert=True)
        return
    plans = await ServicePurchasePlan.list_by_type(session, period.service_type)
    await callback.answer()
    await callback.message.edit_text(
        "📅 <b>مدیریت دوره سرویس</b>\n\n"
        f"📌 نام: <b>{period.name}</b>\n"
        f"⏱ مدت: <b>{period.duration_days} روز</b>\n"
        f"📦 تعداد پلن‌ها: <b>{len(plans)}</b>\n"
        f"{'🟢 فعال' if period.is_active else '🔴 غیرفعال'}",
        reply_markup=_period_details_keyboard(period),
    )


@router.callback_query(F.data.regexp(r"^service_period:toggle:\d+$"), IsAdmin())
async def dynamic_service_period_toggle(callback: CallbackQuery, session: AsyncSession):
    period = await ServicePeriod.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not period or period.is_archived:
        await callback.answer("❌ دوره پیدا نشد.", show_alert=True)
        return
    period.is_active = not period.is_active
    await session.commit()
    await callback.answer("✅ وضعیت دوره تغییر کرد")
    await callback.message.edit_text(
        "📅 <b>مدیریت دوره سرویس</b>\n\n"
        f"📌 نام: <b>{period.name}</b>\n"
        f"⏱ مدت: <b>{period.duration_days} روز</b>\n"
        f"{'🟢 فعال' if period.is_active else '🔴 غیرفعال'}",
        reply_markup=_period_details_keyboard(period),
    )


@router.callback_query(F.data.regexp(r"^service_period:archive:\d+$"), IsAdmin())
async def dynamic_service_period_archive(callback: CallbackQuery, session: AsyncSession):
    period = await ServicePeriod.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not period:
        await callback.answer("❌ دوره پیدا نشد.", show_alert=True)
        return
    period.is_active = False
    period.is_archived = True
    await session.commit()
    await callback.answer("✅ دوره آرشیو شد")
    await _show_period_management(callback, session)


@router.callback_query(F.data.regexp(r"^service_period:plans:\d+$"), IsAdmin())
async def dynamic_service_period_plans(callback: CallbackQuery, session: AsyncSession):
    period = await ServicePeriod.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not period or period.is_archived:
        await callback.answer("❌ دوره پیدا نشد.", show_alert=True)
        return
    plans = await ServicePurchasePlan.list_by_type(session, period.service_type)
    await callback.answer()
    await callback.message.edit_text(
        f"📦 <b>مدیریت پلن‌های {period.name}</b>\n\n"
        f"تعداد پلن‌ها: <b>{len(plans)}</b>\n\n"
        "پلن مورد نظر را انتخاب کنید یا یک پلن جدید بسازید.",
        reply_markup=_plan_list_keyboard(period, plans),
    )


@router.callback_query(F.data.regexp(r"^service_period:create_plan:\d+$"), IsAdmin())
async def dynamic_service_period_create_plan(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    period = await ServicePeriod.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not period or period.is_archived:
        await callback.answer("❌ دوره پیدا نشد.", show_alert=True)
        return
    await state.clear()
    await state.update_data(period_id=period.id, plan_mode="create")
    await state.set_state(DynamicPeriodStates.waiting_plan_volume)
    await callback.answer()
    await callback.message.edit_text(
        f"➕ <b>ساخت پلن برای {period.name}</b>\n\n"
        f"مدت این پلن به‌صورت خودکار <b>{period.duration_days} روز</b> خواهد بود.\n\n"
        "حجم پلن را به گیگابایت وارد کنید:\nمثلاً: <code>20</code>"
    )


@router.message(DynamicPeriodStates.waiting_plan_volume, IsAdmin())
async def dynamic_service_period_plan_volume(message: Message, state: FSMContext):
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    try:
        volume = int(raw)
        if volume <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ حجم نامعتبر است. یک عدد صحیح بزرگ‌تر از صفر وارد کنید.")
        return
    await state.update_data(volume_gb=volume)
    await state.set_state(DynamicPeriodStates.waiting_plan_price)
    await message.answer("💰 قیمت پلن را به تومان وارد کنید:\nمثلاً: <code>150000</code>")


@router.message(DynamicPeriodStates.waiting_plan_price, IsAdmin())
async def dynamic_service_period_plan_price(message: Message, state: FSMContext, session: AsyncSession):
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    try:
        price = int(raw)
        if price < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ قیمت نامعتبر است. مبلغ را فقط به‌صورت عدد وارد کنید.")
        return
    data = await state.get_data()
    period = await ServicePeriod.get(session, int(data["period_id"]))
    if not period or period.is_archived:
        await state.clear()
        await message.answer("❌ دوره پیدا نشد.")
        return
    plan = ServicePurchasePlan(
        service_type=period.service_type,
        volume_gb=int(data["volume_gb"]),
        duration_days=period.duration_days,
        price_toman=price,
    )
    session.add(plan)
    await session.commit()
    await state.clear()
    plans = await ServicePurchasePlan.list_by_type(session, period.service_type)
    await message.answer(
        f"✅ پلن <b>{plan.volume_gb} GB</b> با قیمت <b>{plan.price_toman:,} تومان</b> ساخته شد.",
        reply_markup=_plan_list_keyboard(period, plans),
    )


@router.callback_query(F.data.regexp(r"^service_period:plan:\d+:\d+$"), IsAdmin())
async def dynamic_service_period_plan_details(callback: CallbackQuery, session: AsyncSession):
    _, _, period_text, plan_text = callback.data.split(":")
    period = await ServicePeriod.get(session, int(period_text))
    plan = await ServicePurchasePlan.get(session, int(plan_text))
    if not period or period.is_archived or not plan or plan.service_type != period.service_type:
        await callback.answer("❌ پلن پیدا نشد.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        f"📦 <b>جزئیات پلن {period.name}</b>\n\n"
        f"➕ حجم: <b>{plan.volume_gb} GB</b>\n"
        f"⏱ مدت: <b>{plan.duration_days} روز</b>\n"
        f"💰 قیمت: <b>{plan.price_toman:,} تومان</b>",
        reply_markup=_plan_details_keyboard(period, plan),
    )


@router.callback_query(F.data.regexp(r"^service_period:edit_plan:\d+:\d+$"), IsAdmin())
async def dynamic_service_period_edit_plan(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    _, _, period_text, plan_text = callback.data.split(":")
    period = await ServicePeriod.get(session, int(period_text))
    plan = await ServicePurchasePlan.get(session, int(plan_text))
    if not period or period.is_archived or not plan or plan.service_type != period.service_type:
        await callback.answer("❌ پلن پیدا نشد.", show_alert=True)
        return
    await state.clear()
    await state.update_data(period_id=period.id, plan_id=plan.id, volume_gb=plan.volume_gb)
    await state.set_state(DynamicPeriodStates.waiting_edit_volume)
    await callback.answer()
    await callback.message.edit_text(
        f"✏️ <b>ویرایش پلن {period.name}</b>\n\n"
        f"حجم فعلی: <b>{plan.volume_gb} GB</b>\n\n"
        "حجم جدید را وارد کنید:"
    )


@router.message(DynamicPeriodStates.waiting_edit_volume, IsAdmin())
async def dynamic_service_period_edit_volume(message: Message, state: FSMContext):
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    try:
        volume = int(raw)
        if volume <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ حجم نامعتبر است.")
        return
    await state.update_data(volume_gb=volume)
    await state.set_state(DynamicPeriodStates.waiting_edit_price)
    await message.answer("💰 قیمت جدید را به تومان وارد کنید:")


@router.message(DynamicPeriodStates.waiting_edit_price, IsAdmin())
async def dynamic_service_period_edit_price(message: Message, state: FSMContext, session: AsyncSession):
    raw = (message.text or "").strip().replace(",", "").replace("٬", "")
    try:
        price = int(raw)
        if price < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ قیمت نامعتبر است.")
        return
    data = await state.get_data()
    period = await ServicePeriod.get(session, int(data["period_id"]))
    plan = await ServicePurchasePlan.get(session, int(data["plan_id"]))
    if not period or not plan or plan.service_type != period.service_type:
        await state.clear()
        await message.answer("❌ پلن پیدا نشد.")
        return
    plan.volume_gb = int(data["volume_gb"])
    plan.duration_days = period.duration_days
    plan.price_toman = price
    await session.commit()
    await state.clear()
    await message.answer("✅ پلن با موفقیت ویرایش شد.", reply_markup=_plan_details_keyboard(period, plan))


@router.callback_query(F.data.regexp(r"^service_period:delete_plan:\d+:\d+$"), IsAdmin())
async def dynamic_service_period_delete_plan(callback: CallbackQuery, session: AsyncSession):
    _, _, period_text, plan_text = callback.data.split(":")
    period = await ServicePeriod.get(session, int(period_text))
    plan = await ServicePurchasePlan.get(session, int(plan_text))
    if not period or not plan or plan.service_type != period.service_type:
        await callback.answer("❌ پلن پیدا نشد.", show_alert=True)
        return
    await session.delete(plan)
    await session.commit()
    plans = await ServicePurchasePlan.list_by_type(session, period.service_type)
    await callback.answer("✅ پلن حذف شد")
    await callback.message.edit_text(
        f"📦 <b>مدیریت پلن‌های {period.name}</b>\n\nتعداد پلن‌ها: <b>{len(plans)}</b>",
        reply_markup=_plan_list_keyboard(period, plans),
    )
