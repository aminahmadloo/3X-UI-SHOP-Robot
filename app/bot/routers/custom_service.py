import asyncio
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import ServicesContainer
from app.db.models import CustomServicePricing

router = Router(name=__name__)


async def _delete_after(message: Message | None, delay: float = 5.0) -> None:
    """Delete a custom-service prompt after a short delay."""
    if message is None:
        return

    await asyncio.sleep(delay)

    try:
        await message.delete()
    except Exception:
        # Message may already have been deleted by Telegram/user flow.
        pass


def _schedule_delete(message: Message | None, delay: float = 5.0) -> None:
    if message is not None:
        asyncio.create_task(_delete_after(message, delay))


async def _delete_message_by_id(
    bot,
    chat_id: int,
    message_id: int | None,
    delay: float = 5.0,
) -> None:
    """Delete a stored bot prompt after the requested delay."""
    if message_id is None:
        return

    await asyncio.sleep(delay)

    try:
        await bot.delete_message(
            chat_id=chat_id,
            message_id=message_id,
        )
    except Exception:
        # Message may already have been deleted by Telegram/user flow.
        pass


def _schedule_prompt_delete(
    bot,
    chat_id: int,
    message_id: int | None,
    delay: float = 5.0,
) -> None:
    if message_id is not None:
        asyncio.create_task(
            _delete_message_by_id(
                bot,
                chat_id,
                message_id,
                delay,
            )
        )



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
        "📅 <b>تعداد روز مورد نیاز برای سرویس خود را به صورت عددی بین ۷ تا ۹۰ روز ارسال کنید</b>\n\n"
        "📌 نکته: کمترین مقدار برای خرید سرویس <b>۷ روز</b> و بیشترین مقدار <b>۹۰ روز</b> می‌باشد.\n"
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
        "📌 نکته: حداقل تعداد کاربر برای سرویس‌ها <b>۲ کاربر</b> و بیشترین ۱۰ کاربر می‌باشد.\n"
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


def _payment_invoice_text(days: int, gigabytes: int, devices: int, total: int) -> str:
    return (
        "🧾 <b>فاکتور سرویس انتخابی شما صادر گردید:</b>\n\n"
        "🔐 <b>نام سرویس:</b> سرویس پرسرعت v2ray\n"
        f"📦 <b>پلن انتخابی:</b> {days} روزه {gigabytes} گیگ - {devices} کاربره\n"
        f"💳 <b>قیمت سرویس:</b> {total:,.0f} تومان\n\n"
        f"💰 جهت خرید سرویس نیاز هست کیف پول خودتون رو به اندازه هزینه سرویس یعنی <b>{total:,.0f} تومان</b> شارژ کنید.\n"
        "یا اگر شارژ دارید، بر روی دکمه <b>«پرداخت از کیف پول»</b> کلیک کنید.\n\n"
        "👇 <b>روش پرداخت مورد نظر خود را انتخاب کنید:</b>"
    )


@router.callback_query(F.data == "custom_service:buy")
async def callback_custom_service_buy(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    pricing = await CustomServicePricing.get_or_create(session)

    if not pricing.show_custom_service_button:
        await callback.answer(
            "❌ خرید سرویس با مشخصات دلخواه در حال حاضر غیرفعال است.",
            show_alert=True,
        )
        return

    await state.clear()
    await state.set_state(CustomServiceState.waiting_days)
    await callback.answer()

    prompt = await callback.message.edit_text(
        _days_message(pricing.base_price_per_day)
    )

    await state.update_data(
        custom_service_days_prompt_message_id=prompt.message_id,
    )


@router.message(CustomServiceState.waiting_days)
async def handle_custom_service_days(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    value = _number(message.text or "")
    if value is None or not 7 <= value <= 90:
        pricing = await CustomServicePricing.get_or_create(session)
        invalid_prompt = await message.answer(
            "❌ مقدار واردشده نامعتبر است.\n\n" + _days_message(pricing.base_price_per_day)
        )
        _schedule_delete(invalid_prompt, 5.0)
        return

    pricing = await CustomServicePricing.get_or_create(session)

    data = await state.get_data()

    # The days prompt is deleted 5 seconds AFTER the valid days value
    # has been received, not 5 seconds after the prompt was displayed.
    _schedule_prompt_delete(
        message.bot,
        message.chat.id,
        data.get("custom_service_days_prompt_message_id"),
        5.0,
    )

    await state.update_data(custom_service_days=value)
    await state.set_state(CustomServiceState.waiting_gigabytes)

    prompt = await message.answer(
        _gigabytes_message(value, pricing.base_price_per_gb)
    )

    await state.update_data(
        custom_service_gigabytes_prompt_message_id=prompt.message_id,
    )


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

    # The GB prompt is deleted 5 seconds AFTER the valid GB value
    # has been received.
    _schedule_prompt_delete(
        message.bot,
        message.chat.id,
        data.get("custom_service_gigabytes_prompt_message_id"),
        5.0,
    )

    await state.update_data(custom_service_gigabytes=value)
    await state.set_state(CustomServiceState.waiting_devices)

    prompt = await message.answer(
        _devices_message(days, value, pricing.base_price_per_device)
    )

    await state.update_data(
        custom_service_devices_prompt_message_id=prompt.message_id,
    )


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

    # The devices prompt is deleted 5 seconds AFTER the valid
    # number of users/devices has been received.
    _schedule_prompt_delete(
        message.bot,
        message.chat.id,
        data.get("custom_service_devices_prompt_message_id"),
        5.0,
    )

    days_cost = days * pricing.base_price_per_day
    gigabytes_cost = gigabytes * pricing.base_price_per_gb
    devices_cost = value * pricing.base_price_per_device
    total = days_cost + gigabytes_cost + devices_cost

    await state.update_data(
        custom_service_devices=value,
        custom_service_total=total,
    )
    await state.set_state(CustomServiceState.waiting_payment)

    prompt = await message.answer(
        _payment_invoice_text(days, gigabytes, value, int(total)),
        reply_markup=_payment_keyboard(),
    )

    # Final custom-service invoice/prompt is cleaned up automatically.
    _schedule_delete(prompt, 5.0)


@router.callback_query(F.data == "custom_service:back")
async def custom_service_payment_back(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()

    try:
        days = int(data["custom_service_days"])
        gigabytes = int(data["custom_service_gigabytes"])
        devices = int(data["custom_service_devices"])
        total = int(round(float(data["custom_service_total"])))
    except (KeyError, TypeError, ValueError):
        await state.clear()
        await callback.answer("❌ فاکتور سرویس منقضی شده است.", show_alert=True)
        return

    if not (7 <= days <= 90 and 5 <= gigabytes <= 400 and 2 <= devices <= 10 and total > 0):
        await state.clear()
        await callback.answer("❌ اطلاعات فاکتور نامعتبر یا منقضی شده است.", show_alert=True)
        return

    await state.set_state(CustomServiceState.waiting_payment)
    await callback.answer()
    await callback.message.edit_text(
        _payment_invoice_text(days, gigabytes, devices, total),
        reply_markup=_payment_keyboard(),
    )


@router.callback_query(F.data == "custom_service:payment:gateway")
async def custom_service_payment_gateway(callback: CallbackQuery) -> None:
    await callback.answer("🏦 درگاه بانکی در مرحله بعد به این فاکتور متصل می‌شود.", show_alert=True)


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
