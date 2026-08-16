import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import ServicesContainer
from app.db.models import CustomServicePricing

router = Router(name=__name__)


class CustomServiceState(StatesGroup):
    waiting_days = State()
    waiting_gigabytes = State()
    waiting_devices = State()
    waiting_payment = State()


def _normalize_number(value: str) -> str:
    return value.translate(
        str.maketrans(
            "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
            "01234567890123456789",
        )
    ).replace(",", "").replace("٬", "").replace(" ", "").strip()


def _number(value: str) -> int | None:
    normalized = _normalize_number(value)
    if not re.fullmatch(r"\d+", normalized):
        return None
    return int(normalized)


def _days_message(days_price: float) -> str:
    return (
        "📅 <b>تعداد روز مورد نیاز برای سرویس خود را به صورت عددی بین ۷ تا ۳۰ روز ارسال کنید</b>\n\n"
        "📌 نکته: کمترین مقدار برای خرید سرویس <b>۷ روز</b> و بیشترین مقدار <b>۳۰ روز</b> می‌باشد.\n"
        "لطفاً در این بازه یک عدد ارسال کنید.\n\n"
        f"💰 هزینه هر روز برای سرویس: <b>{days_price:,.0f} تومان</b>"
    )


def _gigabytes_message(days: int, gb_price: float) -> str:
    return (
        f"📦 <b>مقدار حجم مورد نیاز برای سرویس {days} روزه خود را بین ۵ تا ۴۰۰ گیگ ارسال کنید</b>\n\n"
        "📌 نکته: کمترین مقدار حجم برای سرویس <b>۵ گیگ</b> و بیشترین مقدار <b>۴۰۰ گیگ</b> می‌باشد.\n"
        "لطفاً در این بازه یک عدد ارسال کنید.\n\n"
        f"💰 هزینه هر گیگ: <b>{gb_price:,.0f} تومان</b>"
    )


def _devices_message(days: int, gigabytes: int, device_price: float) -> str:
    return (
        f"👥 <b>تعداد کاربر مورد نیاز برای سرویس {days} روزه {gigabytes} گیگ خود را بین ۲ تا ۱۰ کاربر ارسال کنید</b>\n\n"
        "📌 نکته: حداقل تعداد کاربر برای سرویس‌ها <b>۲ کاربر</b> و بیشترین <b>۱۰ کاربر</b> می‌باشد.\n"
        "لطفاً در این بازه یک عدد ارسال کنید.\n\n"
        f"💰 هزینه هر کاربر برای سرویس: <b>{device_price:,.0f} تومان</b>"
    )


def _payment_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏦 درگاه بانکی", callback_data="custom_service:payment:gateway")],
            [InlineKeyboardButton(text="💳 کارت به کارت", callback_data="custom_service:payment:card")],
            [InlineKeyboardButton(text="💰 پرداخت از کیف پول", callback_data="custom_service:payment:wallet")],
        ]
    )


@router.callback_query(F.data == "custom_service:buy")
async def callback_custom_service_buy(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    pricing = await CustomServicePricing.get_or_create(session)
    await state.clear()
    await state.set_state(CustomServiceState.waiting_days)
    await callback.answer()
    await callback.message.edit_text(_days_message(pricing.base_price_per_day))


@router.message(CustomServiceState.waiting_days)
async def handle_custom_service_days(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    value = _number(message.text or "")
    if value is None or not 7 <= value <= 30:
        pricing = await CustomServicePricing.get_or_create(session)
        await message.answer(
            "❌ مقدار واردشده نامعتبر است.\n\n" + _days_message(pricing.base_price_per_day)
        )
        return

    pricing = await CustomServicePricing.get_or_create(session)
    await state.update_data(custom_service_days=value)
    await state.set_state(CustomServiceState.waiting_gigabytes)
    await message.answer(_gigabytes_message(value, pricing.base_price_per_gb))


@router.message(CustomServiceState.waiting_gigabytes)
async def handle_custom_service_gigabytes(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    value = _number(message.text or "")
    if value is None or not 5 <= value <= 400:
        data = await state.get_data()
        days = int(data.get("custom_service_days", 15))
        pricing = await CustomServicePricing.get_or_create(session)
        await message.answer(
            "❌ مقدار واردشده نامعتبر است.\n\n" + _gigabytes_message(days, pricing.base_price_per_gb)
        )
        return

    data = await state.get_data()
    days = int(data["custom_service_days"])
    pricing = await CustomServicePricing.get_or_create(session)
    await state.update_data(custom_service_gigabytes=value)
    await state.set_state(CustomServiceState.waiting_devices)
    await message.answer(_devices_message(days, value, pricing.base_price_per_device))


@router.message(CustomServiceState.waiting_devices)
async def handle_custom_service_devices(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    value = _number(message.text or "")
    if value is None or not 2 <= value <= 10:
        data = await state.get_data()
        days = int(data.get("custom_service_days", 15))
        gigabytes = int(data.get("custom_service_gigabytes", 5))
        pricing = await CustomServicePricing.get_or_create(session)
        await message.answer(
            "❌ مقدار واردشده نامعتبر است.\n\n" + _devices_message(days, gigabytes, pricing.base_price_per_device)
        )
        return

    data = await state.get_data()
    days = int(data["custom_service_days"])
    gigabytes = int(data["custom_service_gigabytes"])
    pricing = await CustomServicePricing.get_or_create(session)

    days_cost = days * pricing.base_price_per_day
    gigabytes_cost = gigabytes * pricing.base_price_per_gb
    devices_cost = value * pricing.base_price_per_device
    total = days_cost + gigabytes_cost + devices_cost

    await state.update_data(
        custom_service_devices=value,
        custom_service_total=total,
    )
    await state.set_state(CustomServiceState.waiting_payment)

    text = (
        "🧾 <b>فاکتور سرویس انتخابی شما صادر گردید:</b>\n\n"
        "🔐 <b>نام سرویس:</b> سرویس پرسرعت v2ray\n"
        f"📦 <b>پلن انتخابی:</b> {days} روزه {gigabytes} گیگ - {value} کاربره\n"
        "📍 <b>لوکیشن:</b> دبی\n"
        f"💳 <b>قیمت سرویس:</b> {total:,.0f} تومان\n\n"
        f"💰 جهت خرید سرویس نیاز هست کیف پول خودتون رو به اندازه هزینه سرویس یعنی <b>{total:,.0f} تومان</b> شارژ کنید.\n"
        "یا اگر شارژ دارید، بر روی دکمه <b>«پرداخت از کیف پول»</b> کلیک کنید.\n\n"
        "👇 <b>روش پرداخت مورد نظر خود را انتخاب کنید:</b>"
    )
    await message.answer(text, reply_markup=_payment_keyboard())


@router.callback_query(F.data == "custom_service:payment:gateway")
async def custom_service_payment_gateway(callback: CallbackQuery) -> None:
    await callback.answer("🏦 درگاه بانکی در مرحله بعد به این فاکتور متصل می‌شود.", show_alert=True)


@router.callback_query(F.data == "custom_service:payment:card")
async def custom_service_payment_card(callback: CallbackQuery) -> None:
    await callback.answer("💳 پرداخت کارت به کارت در مرحله بعد به این فاکتور متصل می‌شود.", show_alert=True)


@router.callback_query(F.data == "custom_service:payment:wallet")
async def custom_service_payment_wallet(
    callback: CallbackQuery,
    user: object,
    services: ServicesContainer,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    total = int(data.get("custom_service_total", 0))
    if total <= 0:
        await state.clear()
        await callback.answer("❌ فاکتور سرویس منقضی شده است.", show_alert=True)
        return

    balance = await services.wallet.get_balance(user.tg_id)  # type: ignore[attr-defined]
    if balance < total:
        await callback.answer(
            f"❌ موجودی کیف پول شما کافی نیست. موجودی: {balance:,.0f} تومان",
            show_alert=True,
        )
        return

    await callback.answer(
        "💰 موجودی کافی است. پرداخت از کیف پول در مرحله بعد نهایی و سرویس فعال می‌شود.",
        show_alert=True,
    )
