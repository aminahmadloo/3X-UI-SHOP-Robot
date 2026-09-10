import logging
from html import escape
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
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
    WelcomeMessageSettings,
)
from app.db.models.welcome_message_settings import DEFAULT_WELCOME_MESSAGE

from .keyboard import (
    admin_tools_keyboard,
    custom_service_pricing_edit_keyboard,
    custom_service_pricing_keyboard,
    service_purchase_plan_details_keyboard,
    service_purchase_plan_list_keyboard,
    connected_device_settings_keyboard,
)

logger = logging.getLogger(__name__)
router = Router(name=__name__)

MAX_WELCOME_MESSAGE_LENGTH = 4000
WELCOME_VARIABLE_PATTERN = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
ALLOWED_WELCOME_VARIABLES = {"first_name"}
WELCOME_SAMPLE_NAME = "Amin"


class WelcomeMessageStates(StatesGroup):
    waiting_message = State()
    waiting_message_confirmation = State()


def _validate_welcome_message(value: str) -> str | None:
    if not value:
        return "متن خالی است. لطفاً متن پیام خوش‌آمدگویی را ارسال کنید."
    if len(value) > MAX_WELCOME_MESSAGE_LENGTH:
        return f"متن بیش از حد طولانی است. حداکثر {MAX_WELCOME_MESSAGE_LENGTH:,} کاراکتر مجاز است."

    variables = set(WELCOME_VARIABLE_PATTERN.findall(value))
    unknown = sorted(variables - ALLOWED_WELCOME_VARIABLES)
    if unknown:
        names = "، ".join(f"{{{name}}}" for name in unknown)
        return (
            f"متغیر ناشناخته در متن وجود دارد: {names}\n\n"
            "تنها متغیر مجاز فعلی: <code>{first_name}</code>"
        )
    if "{first_name}" not in value:
        return "برای نمایش نام کاربر، متغیر <code>{first_name}</code> باید در متن وجود داشته باشد."
    return None


def _render_welcome_for_admin(template: str) -> str:
    return escape(template.replace("{first_name}", WELCOME_SAMPLE_NAME))


def _welcome_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ ویرایش متن", callback_data="welcome_message:edit")],
            [
                InlineKeyboardButton(text="👁 پیش‌نمایش", callback_data="welcome_message:preview"),
                InlineKeyboardButton(text="📤 ارسال نمونه", callback_data="welcome_message:sample"),
            ],
            [InlineKeyboardButton(text="📖 راهنمای متغیرها", callback_data="welcome_message:help")],
            [InlineKeyboardButton(text="🔄 بازگردانی متن پیش‌فرض", callback_data="welcome_message:reset")],
            [InlineKeyboardButton(text="🔄 بازخوانی", callback_data=NavAdminTools.WELCOME_MESSAGE_SETTINGS)],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)],
        ]
    )


async def _welcome_text(session: AsyncSession) -> str:
    settings = await WelcomeMessageSettings.get_or_create(session)
    status = "پیش‌فرض" if settings.message == DEFAULT_WELCOME_MESSAGE else "سفارشی"
    return (
        "📝 <b>مدیریت پیام خوش‌آمدگویی</b>\n\n"
        f"📊 وضعیت: <b>{status}</b>\n"
        f"📏 طول: <b>{len(settings.message):,} / {MAX_WELCOME_MESSAGE_LENGTH:,}</b> کاراکتر\n\n"
        "متن فعلی:\n"
        f"<blockquote>{_render_welcome_for_admin(settings.message)}</blockquote>\n\n"
        "🔤 متغیر مجاز: <code>{first_name}</code>\n"
        "این متغیر هنگام ارسال، با نام کاربر جایگزین می‌شود.\n"
        "ویرایش این متن بدون نیاز به Restart روی پیام‌های بعدی اعمال می‌شود."
    )


async def _pricing_text(session: AsyncSession) -> str:
    pricing = await CustomServicePricing.get_or_create(session)
    return (
        "⚙️ <b>تنظیمات خرید سرویس ها با مشخصات دلخواه</b>\n\n"
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

    for row in markup.inline_keyboard:
        for button in row:
            if button.callback_data == NavAdminTools.TEST_ACCOUNT_SETTINGS:
                button.text = "🎁 مدیریت اکانت تست"

    markup.inline_keyboard.insert(-1, [InlineKeyboardButton(text="📣 مدیریت تبلیغات", callback_data="advertising:menu")])
    markup.inline_keyboard.insert(-1, [InlineKeyboardButton(text="📢 مدیریت کانال", callback_data="channel:menu")])
    markup.inline_keyboard.insert(-1, [InlineKeyboardButton(text="🏆 مدیریت تخفیف سطوح مشتری", callback_data=NavAdminTools.CUSTOMER_LEVEL_SETTINGS)])
    markup.inline_keyboard.insert(-1, [InlineKeyboardButton(text="🎁 تنظیمات معرفی به دوستان", callback_data=NavAdminTools.REFERRAL_SETTINGS)])
    markup.inline_keyboard.insert(-1, [InlineKeyboardButton(text="📝 مدیریت پیام خوش‌آمدگویی", callback_data=NavAdminTools.WELCOME_MESSAGE_SETTINGS)])
    markup.inline_keyboard.insert(-1, [InlineKeyboardButton(text="💰 مدیریت مبالغ کیف پول", callback_data="wallet_amounts")])
    markup.inline_keyboard.insert(-1, [InlineKeyboardButton(text="🩺 سلامت سیستم", callback_data="system_health")])
    await callback.message.edit_text(text=_("admin_tools:message:main"), reply_markup=markup)


@router.callback_query(F.data == NavAdminTools.WELCOME_MESSAGE_SETTINGS, IsAdmin())
async def callback_welcome_message_settings(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(await _welcome_text(session), reply_markup=_welcome_keyboard())


@router.callback_query(F.data == "welcome_message:edit", IsAdmin())
async def edit_welcome_message(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    settings = await WelcomeMessageSettings.get_or_create(session)
    await state.set_state(WelcomeMessageStates.waiting_message)
    await callback.answer()
    await callback.message.edit_text(
        "✏️ <b>ویرایش پیام خوش‌آمدگویی</b>\n\n"
        "کل متن را در یک پیام ارسال کنید.\n\n"
        "🔤 برای نمایش نام کاربر از این متغیر استفاده کنید:\n"
        "<code>{first_name}</code>\n\n"
        "⚠️ فقط همین متغیر مجاز است.\n"
        f"📏 حداکثر طول: {MAX_WELCOME_MESSAGE_LENGTH:,} کاراکتر.\n\n"
        f"📝 <b>متن فعلی:</b>\n<blockquote>{escape(settings.message)}</blockquote>"
    )


@router.message(WelcomeMessageStates.waiting_message, IsAdmin())
async def prepare_welcome_message(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    error = _validate_welcome_message(value)
    if error:
        await message.answer(f"❌ {error}")
        return

    await state.update_data(pending_welcome_message=value)
    await state.set_state(WelcomeMessageStates.waiting_message_confirmation)
    await message.answer(
        "👁 <b>پیش‌نمایش متن جدید</b>\n\n"
        f"<blockquote>{_render_welcome_for_admin(value)}</blockquote>\n\n"
        "اگر متن درست است، روی «ذخیره» بزنید.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="💾 ذخیره", callback_data="welcome_message:save")],
                [InlineKeyboardButton(text="❌ انصراف", callback_data="welcome_message:cancel")],
            ]
        ),
    )


@router.callback_query(F.data == "welcome_message:save", IsAdmin())
async def save_welcome_message(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    value = data.get("pending_welcome_message")
    error = _validate_welcome_message(value or "")
    if error:
        await state.clear()
        await callback.answer("متن ذخیره نشد", show_alert=True)
        await callback.message.edit_text(f"❌ {error}", reply_markup=_welcome_keyboard())
        return

    settings = await WelcomeMessageSettings.get_or_create(session)
    settings.message = value
    await session.commit()
    await state.clear()
    await callback.answer("متن با موفقیت ذخیره شد")
    await callback.message.edit_text(
        "✅ <b>پیام خوش‌آمدگویی ذخیره شد.</b>\n\n"
        "از این لحظه پیام‌های جدید با متن جدید ارسال می‌شوند و نیازی به Restart نیست.",
        reply_markup=_welcome_keyboard(),
    )


@router.callback_query(F.data == "welcome_message:cancel", IsAdmin())
async def cancel_welcome_message(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    await state.clear()
    await callback.answer("عملیات لغو شد")
    await callback.message.edit_text(await _welcome_text(session), reply_markup=_welcome_keyboard())


@router.callback_query(F.data == "welcome_message:preview", IsAdmin())
async def preview_welcome_message(callback: CallbackQuery, session: AsyncSession) -> None:
    settings = await WelcomeMessageSettings.get_or_create(session)
    await callback.answer()
    await callback.message.answer(
        "👁 <b>پیش‌نمایش پیام خوش‌آمدگویی</b>\n\n"
        f"{_render_welcome_for_admin(settings.message)}"
    )


@router.callback_query(F.data == "welcome_message:sample", IsAdmin())
async def sample_welcome_message(callback: CallbackQuery, session: AsyncSession) -> None:
    settings = await WelcomeMessageSettings.get_or_create(session)
    await callback.answer("نمونه ارسال شد")
    await callback.message.answer(settings.message.replace("{first_name}", WELCOME_SAMPLE_NAME))


@router.callback_query(F.data == "welcome_message:help", IsAdmin())
async def welcome_message_help(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.answer(
        "📖 <b>راهنمای پیام خوش‌آمدگویی</b>\n\n"
        "🔤 <code>{first_name}</code>\n"
        "در زمان ارسال با نام همان کاربر جایگزین می‌شود.\n\n"
        "مثال:\n"
        "<blockquote>سلام {first_name} عزیز 👋\n\nبه ToonelVPN خوش آمدی.</blockquote>\n\n"
        f"📏 حداکثر طول متن: {MAX_WELCOME_MESSAGE_LENGTH:,} کاراکتر\n"
        "⚠️ متغیرهای ناشناخته اجازه ذخیره شدن ندارند."
    )


@router.callback_query(F.data == "welcome_message:reset", IsAdmin())
async def reset_welcome_message(callback: CallbackQuery, session: AsyncSession) -> None:
    settings = await WelcomeMessageSettings.get_or_create(session)
    settings.message = DEFAULT_WELCOME_MESSAGE
    await session.commit()
    await callback.answer("متن به حالت پیش‌فرض برگشت")
    await callback.message.edit_text(
        "✅ <b>پیام خوش‌آمدگویی به حالت پیش‌فرض بازگردانده شد.</b>",
        reply_markup=_welcome_keyboard(),
    )


@router.callback_query(F.data == NavAdminTools.SERVICE_PURCHASE_DEVICES, IsAdmin())
async def callback_service_purchase_devices(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    settings = await ConnectedDeviceSettings.get_or_create(session)
    await callback.answer()
    await callback.message.edit_text(
        "📱 <b>مدیریت تعداد دستگاه متصل</b>\n\n"
        "تعداد دستگاه‌های مجاز برای اتصال همزمان: "
        f"<b>{settings.max_connected_devices} دستگاه</b>",
        reply_markup=connected_device_settings_keyboard(),
    )


@router.callback_query(F.data == "connected_device_settings:edit", IsAdmin())
async def callback_connected_device_settings_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ConnectedDeviceSettingsStates.waiting_max_devices)
    await callback.answer()
    await callback.message.edit_text(
        "✏️ <b>ویرایش تعداد دستگاه متصل</b>\n\n"
        "تعداد دستگاه‌های مجاز برای اتصال همزمان را وارد کنید.\n"
        "مثلاً: <code>3</code>"
    )


@router.message(ConnectedDeviceSettingsStates.waiting_max_devices, IsAdmin())
async def process_connected_device_settings(message: Message, state: FSMContext, session: AsyncSession) -> None:
    raw = (message.text or "").strip()
    try:
        value = int(raw)
        if value <= 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ مقدار نامعتبر است.\nلطفاً تعداد دستگاه را به صورت یک عدد صحیح بزرگ‌تر از صفر وارد کنید.")
        return
    settings = await ConnectedDeviceSettings.get_or_create(session)
    settings.max_connected_devices = value
    await session.commit()
    await state.clear()
    await message.answer(
        "✅ <b>تعداد دستگاه با موفقیت ذخیره شد.</b>\n\n"
        f"تعداد دستگاه‌های مجاز برای اتصال همزمان: <b>{settings.max_connected_devices} دستگاه</b>",
        reply_markup=connected_device_settings_keyboard(),
    )
