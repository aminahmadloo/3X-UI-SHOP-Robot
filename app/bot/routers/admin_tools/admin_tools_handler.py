import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin, IsDev
from app.bot.services import ServicesContainer
from app.bot.states.custom_service_pricing import CustomServicePricingStates
from app.bot.utils.navigation import NavAdminTools
from app.db.models import CustomServicePricing, User

from .keyboard import (
    admin_tools_keyboard,
    custom_service_pricing_edit_keyboard,
    custom_service_pricing_keyboard,
    service_purchase_management_keyboard,
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
    F.data.in_(
        {
            NavAdminTools.SERVICE_PURCHASE_ONE_MONTH,
            NavAdminTools.SERVICE_PURCHASE_THREE_MONTH,
            NavAdminTools.SERVICE_PURCHASE_DEVICES,
        }
    ),
    IsAdmin(),
)
async def callback_service_purchase_management_placeholder(
    callback: CallbackQuery,
) -> None:
    # فعلاً فقط کلیدها ایجاد شده‌اند و منطق آن‌ها در مراحل بعدی اضافه می‌شود.
    await callback.answer()


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
