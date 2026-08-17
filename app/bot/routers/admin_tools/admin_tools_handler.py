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
