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
            "لطفاً مبلغ را فقط به صورت عدد وارد کنید."
        )
        return

    data = await state.get_data()

    if data.get("plan_mode") == "edit":
        plan = await ServicePurchasePlan.get(
            session,
            int(data["plan_id"]),
        )

        if not plan:
            await state.clear()
            await message.answer("❌ سرویس موردنظر پیدا نشد.")
            return

        plan.volume_gb = int(data["volume_gb"])
        plan.duration_days = int(data["duration_days"])
        plan.price_toman = value

        await session.commit()
        service_type = plan.service_type
        plan_id = plan.id

        await state.clear()

        await message.answer(
            "✅ تغییرات سرویس ذخیره شد."
        )

        plans = await ServicePurchasePlan.list_by_type(
            session,
            service_type,
        )

        title = (
            "📅 <b>مدیریت سرویس‌های یک ماهه</b>"
            if service_type == "one_month"
            else "📅 <b>مدیریت سرویس‌های سه ماهه</b>"
        )

        await message.answer(
            title,
            reply_markup=service_purchase_plan_list_keyboard(
                plans,
                service_type,
            ),
        )
        return

    plan = ServicePurchasePlan(
        service_type=data["service_type"],
        volume_gb=int(data["volume_gb"]),
        duration_days=int(data["duration_days"]),
        price_toman=value,
    )

    session.add(plan)
    await session.commit()

    service_type = plan.service_type
    await state.clear()

    await message.answer("✅ سرویس جدید با موفقیت ساخته شد.")

    plans = await ServicePurchasePlan.list_by_type(
        session,
        service_type,
    )

    title = (
        "📅 <b>مدیریت سرویس‌های یک ماهه</b>"
        if service_type == "one_month"
        else "📅 <b>مدیریت سرویس‌های سه ماهه</b>"
    )

    await message.answer(
        title,
        reply_markup=service_purchase_plan_list_keyboard(
            plans,
            service_type,
        ),
    )


@router.callback_query(F.data == NavAdminTools.CUSTOM_SERVICE_PRICING, IsAdmin())
async def callback_custom_service_pricing(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        text=await _pricing_text(session),
        reply_markup=custom_service_pricing_keyboard(),
    )


@router.callback_query(F.data == "custom_service_pricing:edit", IsAdmin())
async def callback_custom_service_pricing_edit(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    pricing = await CustomServicePricing.get_or_create(session)
    await state.set_state(CustomServicePricingStates.waiting_value)
    await state.update_data(
        base_price_per_day=pricing.base_price_per_day,
        base_price_per_gb=pricing.base_price_per_gb,
        base_price_per_device=pricing.base_price_per_device,
        base_price_per_location=pricing.base_price_per_location,
        pricing_field="base_price_per_day",
    )
    await callback.answer()
    await callback.message.edit_text(
        "✏️ <b>ویرایش مبالغ پایه</b>\n\n"
        "مبلغ جدید «مبلغ پایه به ازاء هر روز» را وارد کنید:\n"
        "فقط عدد وارد کنید (مثلاً 10000)."
    )


@router.message(CustomServicePricingStates.waiting_value, IsAdmin())
async def process_custom_service_pricing_value(
    message: Message,
    state: FSMContext,
) -> None:
    raw_value = (message.text or "").replace(",", "").strip()
    try:
        value = float(raw_value)
        if value < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ مقدار نامعتبر است. لطفاً فقط یک عدد صفر یا مثبت وارد کنید.")
        return

    data = await state.get_data()
    field = data.get("pricing_field")
    await state.update_data(**{field: value})

    sequence = {
        "base_price_per_day": (
            "base_price_per_gb",
            "مبلغ پایه هر گیگ حجم",
        ),
        "base_price_per_gb": (
            "base_price_per_device",
            "مبلغ پایه هر کاربر/دستگاه",
        ),
        "base_price_per_device": (
            "base_price_per_location",
            "مبلغ پایه هر لوکیشن/سرویس",
        ),
    }

    if field in sequence:
        next_field, title = sequence[field]
        await state.update_data(pricing_field=next_field)
        await message.answer(f"مقدار «{title}» را وارد کنید:")
        return

    await state.set_state(None)
    data = await state.get_data()
    await message.answer(
        "✅ هر چهار مقدار دریافت شد.\n\n"
        f"1. مبلغ پایه به ازاء هر روز: {data['base_price_per_day']:,.0f}\n"
        f"2. مبلغ پایه هر گیگ حجم: {data['base_price_per_gb']:,.0f}\n"
        f"3. مبلغ پایه هر کاربر/دستگاه: {data['base_price_per_device']:,.0f}\n"
        f"4. مبلغ پایه هر لوکیشن/سرویس: {data['base_price_per_location']:,.0f}\n\n"
        "برای ثبت دائمی مقادیر، روی «💾 ذخیره» بزنید.",
        reply_markup=custom_service_pricing_edit_keyboard(),
    )


@router.callback_query(F.data == "custom_service_pricing:save", IsAdmin())
async def save_custom_service_pricing(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    required = (
        "base_price_per_day",
        "base_price_per_gb",
        "base_price_per_device",
        "base_price_per_location",
    )
    if any(key not in data for key in required):
        await callback.answer("اطلاعات ویرایش کامل نیست.", show_alert=True)
        return

    pricing = await CustomServicePricing.get_or_create(session)
    pricing.base_price_per_day = float(data["base_price_per_day"])
    pricing.base_price_per_gb = float(data["base_price_per_gb"])
    pricing.base_price_per_device = float(data["base_price_per_device"])
    pricing.base_price_per_location = float(data["base_price_per_location"])
    await session.commit()
    await state.clear()

    await callback.answer("✅ مقادیر با موفقیت ذخیره شد")
    await callback.message.edit_text(
        text=await _pricing_text(session),
        reply_markup=custom_service_pricing_keyboard(),
    )


@router.callback_query(F.data == NavAdminTools.TEST, IsAdmin())
async def callback_admin_tools_test(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    logger.info(f"Admin {user.tg_id} clicked TEST BUTTON.")
    await callback.message.answer(
        "<b>bold</b>\n<i>italic</i>\n<u>underline</u>\n<s>strikethrough</s>\n"
        "<tg-spoiler>spoiler</tg-spoiler>\n\n<code>inline fixed-width code</code>\n"
        "<pre>pre-formatted fixed-width code block</pre>"
    )
