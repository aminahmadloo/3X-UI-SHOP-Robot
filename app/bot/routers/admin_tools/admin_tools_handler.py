import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin, IsDev
from app.bot.services import ServicesContainer
from app.bot.states.custom_service_pricing import CustomServicePricingStates
from app.bot.states.connected_device_settings import ConnectedDeviceSettingsStates
from app.bot.states.service_purchase_plan import ServicePurchasePlanStates
from app.bot.utils.navigation import NavAdminTools
from app.db.models import (
    ConnectedDeviceSettings,
    CustomServicePricing,
    ServicePurchasePlan,
    User,
)

from .keyboard import (
    admin_tools_keyboard,
    custom_service_pricing_edit_keyboard,
    custom_service_pricing_keyboard,
    service_purchase_management_keyboard,
    service_purchase_plan_details_keyboard,
    service_purchase_plan_list_keyboard,
    connected_device_settings_keyboard,
)

logger = logging.getLogger(__name__)
router = Router(name=__name__)


async def _pricing_text(session: AsyncSession) -> str:
    pricing = await CustomServicePricing.get_or_create(session)
    return (
        "⚙️ <b>مدیریت خرید سرویس با مشخصات دلخواه</b>\n\n"
        f"1️⃣ <b>مبلغ پایه به ازاء هر روز:</b> {pricing.base_price_per_day:,.0f}\n"
        f"2️⃣ <b>مبلغ پایه هر گیگ حجم:</b> {pricing.base_price_per_gb:,.0f}\n"
        f"3️⃣ <b>مبلغ پایه هر کاربر/دستگاه:</b> {pricing.base_price_per_device:,.0f}\n"
        f"4️⃣ <b>مبلغ پایه هر لوکیشن/سرویس:</b> {pricing.base_price_per_location:,.0f}\n\n"
        "این مقادیر پایه در مرحله بعد برای محاسبه قیمت «خرید سرویس با مشخصات دلخواه» استفاده خواهند شد."
    )


@router.callback_query(F.data == NavAdminTools.MAIN, IsAdmin())
async def callback_admin_tools(callback: CallbackQuery, user: User) -> None:
    logger.info(f"Admin {user.tg_id} opened admin tools.")
    is_dev = await IsDev()(user_id=user.tg_id)
    markup = admin_tools_keyboard(is_dev)
    markup.inline_keyboard.insert(
        -1,
        [InlineKeyboardButton(text="💰 مدیریت مبالغ کیف پول", callback_data="wallet_amounts")],
    )
    await callback.message.edit_text(text=_("admin_tools:message:main"), reply_markup=markup)


@router.callback_query(F.data == NavAdminTools.SERVICE_PURCHASE_MANAGEMENT, IsAdmin())
async def callback_service_purchase_management(
    callback: CallbackQuery,
) -> None:
    await callback.answer()
    await callback.message.edit_text(
        text="🛒 <b>مدیریت خرید سرویس</b>",
        reply_markup=service_purchase_management_keyboard(),
    )



@router.callback_query(
    F.data == NavAdminTools.SERVICE_PURCHASE_DEVICES,
    IsAdmin(),
)
async def callback_service_purchase_devices(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()

    settings = await ConnectedDeviceSettings.get_or_create(session)

    await callback.answer()

    await callback.message.edit_text(
        "📱 <b>مدیریت تعداد دستگاه متصل</b>\n\n"
        "تعداد دستگاه‌های مجاز برای اتصال همزمان: "
        f"<b>{settings.max_connected_devices} دستگاه</b>",
        reply_markup=connected_device_settings_keyboard(),
    )


@router.callback_query(
    F.data == "connected_device_settings:edit",
    IsAdmin(),
)
async def callback_connected_device_settings_edit(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    await state.set_state(
        ConnectedDeviceSettingsStates.waiting_max_devices
    )

    await callback.answer()

    await callback.message.edit_text(
        "✏️ <b>ویرایش تعداد دستگاه متصل</b>\n\n"
        "تعداد دستگاه‌های مجاز برای اتصال همزمان را وارد کنید.\n"
        "مثلاً: <code>3</code>"
    )


@router.message(
    ConnectedDeviceSettingsStates.waiting_max_devices,
    IsAdmin(),
)
async def process_connected_device_settings(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    raw = (message.text or "").strip()

    try:
        value = int(raw)
        if value <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ مقدار نامعتبر است.\n"
            "لطفاً تعداد دستگاه را به صورت یک عدد صحیح بزرگ‌تر از صفر وارد کنید."
        )
        return

    settings = await ConnectedDeviceSettings.get_or_create(session)
    settings.max_connected_devices = value

    await session.commit()
    await state.clear()

    await message.answer(
        "✅ <b>تعداد دستگاه با موفقیت ذخیره شد.</b>\n\n"
        f"تعداد دستگاه‌های مجاز برای اتصال همزمان: "
        f"<b>{settings.max_connected_devices} دستگاه</b>",
        reply_markup=connected_device_settings_keyboard(),
    )



@router.callback_query(
    F.data.in_(
        {
            NavAdminTools.SERVICE_PURCHASE_ONE_MONTH,
            NavAdminTools.SERVICE_PURCHASE_THREE_MONTH,
        }
    ),
    IsAdmin(),
)
async def callback_service_purchase_plan_list(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.answer()

    service_type = (
        "one_month"
        if callback.data == NavAdminTools.SERVICE_PURCHASE_ONE_MONTH
        else "three_month"
    )

    plans = await ServicePurchasePlan.list_by_type(session, service_type)

    title = (
        "📅 <b>مدیریت سرویس‌های یک ماهه</b>"
        if service_type == "one_month"
        else "📅 <b>مدیریت سرویس‌های سه ماهه</b>"
    )

    await callback.message.edit_text(
        title,
        reply_markup=service_purchase_plan_list_keyboard(
            plans,
            service_type,
        ),
    )


@router.callback_query(
    F.data.startswith(f"{NavAdminTools.SERVICE_PURCHASE_PLAN}:"),
    IsAdmin(),
)
async def callback_service_purchase_plan_details(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    await callback.answer()

    try:
        plan_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("شناسه سرویس نامعتبر است.", show_alert=True)
        return

    plan = await ServicePurchasePlan.get(session, plan_id)

    if not plan:
        await callback.answer("این سرویس دیگر وجود ندارد.", show_alert=True)
        return

    if plan.service_type == "one_month":
        title = "📅 <b>سرویس یک ماهه</b>"
    else:
        title = "📅 <b>سرویس سه ماهه</b>"

    price = (
        f"{plan.price_toman // 1000:,} هزار تومان"
        if plan.price_toman % 1000 == 0
        else f"{plan.price_toman:,} تومان"
    )

    await callback.message.edit_text(
        f"{title}\n\n"
        f"📦 حجم: <b>{plan.volume_gb} گیگ</b>\n"
        f"📅 مدت: <b>{plan.duration_days} روز</b>\n"
        f"💰 قیمت: <b>{price}</b>",
        reply_markup=service_purchase_plan_details_keyboard(
            plan.id,
            plan.service_type,
        ),
    )


async def _start_plan_creation(
    callback: CallbackQuery,
    state: FSMContext,
    service_type: str,
) -> None:
    await state.clear()
    await state.update_data(
        plan_mode="create",
        service_type=service_type,
    )
    await state.set_state(ServicePurchasePlanStates.waiting_volume)

    title = (
        "یک ماهه"
        if service_type == "one_month"
        else "سه ماهه"
    )

    await callback.answer()
    await callback.message.edit_text(
        f"➕ <b>ساخت سرویس جدید {title}</b>\n\n"
        "حجم سرویس را به گیگ وارد کنید:\n"
        "مثلاً: <code>20</code>"
    )


@router.callback_query(
    F.data.in_(
        {
            NavAdminTools.SERVICE_PURCHASE_CREATE_ONE_MONTH,
            NavAdminTools.SERVICE_PURCHASE_CREATE_THREE_MONTH,
        }
    ),
    IsAdmin(),
)
async def callback_service_purchase_plan_create(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    service_type = (
        "one_month"
        if callback.data == NavAdminTools.SERVICE_PURCHASE_CREATE_ONE_MONTH
        else "three_month"
    )

    await _start_plan_creation(callback, state, service_type)


@router.callback_query(
    F.data.startswith(f"{NavAdminTools.SERVICE_PURCHASE_EDIT}:"),
    IsAdmin(),
)
async def callback_service_purchase_plan_edit(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    try:
        plan_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("شناسه سرویس نامعتبر است.", show_alert=True)
        return

    plan = await ServicePurchasePlan.get(session, plan_id)

    if not plan:
        await callback.answer("سرویس پیدا نشد.", show_alert=True)
        return

    await state.clear()
    await state.update_data(
        plan_mode="edit",
        plan_id=plan.id,
        service_type=plan.service_type,
        volume_gb=plan.volume_gb,
        duration_days=plan.duration_days,
        price_toman=plan.price_toman,
    )

    await state.set_state(ServicePurchasePlanStates.waiting_volume)

    await callback.answer()
    await callback.message.edit_text(
        "✏️ <b>ویرایش سرویس</b>\n\n"
        f"حجم فعلی: <b>{plan.volume_gb} گیگ</b>\n\n"
        "حجم جدید را وارد کنید:"
    )


@router.callback_query(
    F.data.startswith(f"{NavAdminTools.SERVICE_PURCHASE_DELETE}:"),
    IsAdmin(),
)
async def callback_service_purchase_plan_delete(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    try:
        plan_id = int(callback.data.split(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("شناسه سرویس نامعتبر است.", show_alert=True)
        return

    plan = await ServicePurchasePlan.get(session, plan_id)

    if not plan:
        await callback.answer("سرویس قبلاً حذف شده است.", show_alert=True)
        return

    service_type = plan.service_type
    await session.delete(plan)
    await session.commit()

    await callback.answer("✅ سرویس حذف شد")

    plans = await ServicePurchasePlan.list_by_type(
        session,
        service_type,
    )

    title = (
        "📅 <b>مدیریت سرویس‌های یک ماهه</b>"
        if service_type == "one_month"
        else "📅 <b>مدیریت سرویس‌های سه ماهه</b>"
    )

    await callback.message.edit_text(
        title,
        reply_markup=service_purchase_plan_list_keyboard(
            plans,
            service_type,
        ),
    )


@router.message(ServicePurchasePlanStates.waiting_volume, IsAdmin())
async def process_service_purchase_plan_volume(
    message: Message,
    state: FSMContext,
) -> None:
    raw = (message.text or "").strip()

    try:
        value = int(raw)
        if value <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ حجم نامعتبر است.\n"
            "لطفاً یک عدد صحیح بزرگ‌تر از صفر وارد کنید."
        )
        return

    await state.update_data(volume_gb=value)
    await state.set_state(ServicePurchasePlanStates.waiting_duration)

    await message.answer(
        "📅 مدت سرویس را به روز وارد کنید:\n"
        "مثلاً: <code>31</code>"
    )


@router.message(ServicePurchasePlanStates.waiting_duration, IsAdmin())
async def process_service_purchase_plan_duration(
    message: Message,
    state: FSMContext,
) -> None:
    raw = (message.text or "").strip()

    try:
        value = int(raw)
        if value <= 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ مدت نامعتبر است.\n"
            "لطفاً تعداد روز را به صورت عدد صحیح وارد کنید."
        )
        return

    await state.update_data(duration_days=value)
    await state.set_state(ServicePurchasePlanStates.waiting_price)

    await message.answer(
        "💰 قیمت سرویس را به تومان وارد کنید:\n"
        "مثلاً: <code>100000</code>"
    )


@router.message(ServicePurchasePlanStates.waiting_price, IsAdmin())
async def process_service_purchase_plan_price(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    raw = (
        (message.text or "")
        .replace(",", "")
        .replace("٬", "")
        .strip()
    )

    try:
        value = int(raw)
        if value < 0:
            raise ValueError
    except ValueError:
        await message.answer(
            "❌ قیمت نامعتبر است.\n"
            "لطفاً قیمت را به صورت عدد صحیح صفر یا بیشتر وارد کنید."
        )
        return

    data = await state.get_data()
    service_type = data.get("service_type")
    volume_gb = data.get("volume_gb")
    duration_days = data.get("duration_days")
    plan_mode = data.get("plan_mode", "create")
    plan_id = data.get("plan_id")

    if not service_type or volume_gb is None or duration_days is None:
        await state.clear()
        await message.answer("❌ اطلاعات سرویس ناقص است. دوباره تلاش کنید.")
        return

    if plan_mode == "edit" and plan_id:
        plan = await ServicePurchasePlan.get(session, int(plan_id))
        if not plan:
            await state.clear()
            await message.answer("❌ سرویس پیدا نشد.")
            return

        plan.volume_gb = int(volume_gb)
        plan.duration_days = int(duration_days)
        plan.price_toman = int(value)
        await session.commit()
        await state.clear()

        await message.answer(
            "✅ <b>سرویس با موفقیت ویرایش شد.</b>",
            reply_markup=service_purchase_management_keyboard(),
        )
        return

    plan = ServicePurchasePlan(
        service_type=service_type,
        volume_gb=int(volume_gb),
        duration_days=int(duration_days),
        price_toman=int(value),
    )
    session.add(plan)
    await session.commit()
    await state.clear()

    await message.answer(
        "✅ <b>سرویس جدید با موفقیت ایجاد شد.</b>",
        reply_markup=service_purchase_management_keyboard(),
    )


@router.callback_query(
    F.data.startswith("custom_service_pricing:"),
    IsAdmin(),
)
async def callback_custom_service_pricing(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    action = callback.data.split(":", 1)[1]

    if action == "main":
        await state.clear()
        await callback.answer()
        await callback.message.edit_text(
            await _pricing_text(session),
            reply_markup=custom_service_pricing_keyboard(),
        )
        return

    field_map = {
        "day": ("base_price_per_day", "مبلغ پایه به ازاء هر روز"),
        "gb": ("base_price_per_gb", "مبلغ پایه هر گیگ حجم"),
        "device": ("base_price_per_device", "مبلغ پایه هر کاربر/دستگاه"),
        "location": ("base_price_per_location", "مبلغ پایه هر لوکیشن/سرویس"),
    }

    if action == "edit":
        await callback.answer()
        await callback.message.edit_text(
            "✏️ <b>ویرایش مبالغ پایه</b>\n\n"
            "یکی از موارد زیر را انتخاب کنید:",
            reply_markup=custom_service_pricing_edit_keyboard(),
        )
        return

    if action in field_map:
        field, title = field_map[action]
        await state.clear()
        await state.update_data(pricing_field=field)
        await state.set_state(CustomServicePricingStates.waiting_value)
        pricing = await CustomServicePricing.get_or_create(session)
        current = getattr(pricing, field)
        await callback.answer()
        await callback.message.edit_text(
            f"✏️ <b>{title}</b>\n\n"
            f"مقدار فعلی: <b>{current:,.0f}</b>\n\n"
            "مقدار جدید را به تومان وارد کنید:"
        )
        return

    await callback.answer("گزینه نامعتبر است.", show_alert=True)


@router.message(CustomServicePricingStates.waiting_value, IsAdmin())
async def process_custom_service_pricing_value(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    raw = (
        (message.text or "")
        .replace(",", "")
        .replace("٬", "")
        .strip()
    )

    try:
        value = int(raw)
        if value < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ مقدار نامعتبر است. لطفاً یک عدد صحیح صفر یا مثبت وارد کنید.")
        return

    data = await state.get_data()
    field = data.get("pricing_field")
    if not field:
        await state.clear()
        await message.answer("❌ اطلاعات ویرایش ناقص است. دوباره تلاش کنید.")
        return

    pricing = await CustomServicePricing.get_or_create(session)
    setattr(pricing, field, value)
    await session.commit()
    await state.clear()

    await message.answer(
        "✅ <b>مبلغ با موفقیت ذخیره شد.</b>\n\n" + await _pricing_text(session),
        reply_markup=custom_service_pricing_keyboard(),
    )
