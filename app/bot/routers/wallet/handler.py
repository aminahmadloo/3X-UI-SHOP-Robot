import logging
import secrets
import string

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import ServicesContainer
from app.bot.utils.navigation import NavMain
from app.config import Config
from app.db.models import CardPayment, CardSettings, User, WalletTopupAmount

from ..main_menu.wallet_keyboard import wallet_keyboard

logger = logging.getLogger(__name__)
router = Router(name=__name__)


class CardPaymentState(StatesGroup):
    waiting_amount = State()
    waiting_receipt = State()


def generate_tracking_code(user_tg_id: int) -> str:
    """Generate a human-readable payment tracking code: TelegramID-L-6digits."""
    letter = secrets.choice(string.ascii_uppercase)
    digits = f"{secrets.randbelow(1_000_000):06d}"
    return f"{user_tg_id}-{letter}{digits}"


def wallet_text(language: str, balance: int, has_amounts: bool) -> str:
    balance_text = f"{balance:,}"
    if language == "en":
        options = "Select a top-up amount below:" if has_amounts else "No top-up amounts are currently available."
        return f"💰 <b>Wallet</b>\n\n💳 <b>Balance:</b> {balance_text} Toman\n\n{options}"
    if language == "ru":
        options = "Выберите сумму пополнения ниже:" if has_amounts else "Суммы пополнения пока недоступны."
        return f"💰 <b>Кошелёк</b>\n\n💳 <b>Баланс:</b> {balance_text} томан\n\n{options}"
    options = "مبلغ مورد نظر برای شارژ را انتخاب کنید:" if has_amounts else "در حال حاضر مبلغی برای شارژ کیف پول تعریف نشده است."
    return f"💰 <b>کیف پول</b>\n\n💳 <b>موجودی:</b> {balance_text} تومان\n\n{options}"


def card_text(language: str, settings: CardSettings, amount: int) -> str:
    if not settings.card_number or not settings.card_holder_name or not settings.is_active:
        return "❌ پرداخت کارت به کارت در حال حاضر فعال نیست."
    if language == "en":
        return (
            f"💳 <b>Card-to-card payment</b>\n\n"
            f"Amount: <b>{amount:,} Toman</b>\n\n"
            f"Card number:\n<code>{settings.card_number}</code>\n\n"
            f"Card holder:\n<b>{settings.card_holder_name}</b>\n\n"
            "After transferring the amount, press the button below and send the receipt image."
        )
    if language == "ru":
        return (
            f"💳 <b>Оплата переводом</b>\n\n"
            f"Сумма: <b>{amount:,} томан</b>\n\n"
            f"Номер карты:\n<code>{settings.card_number}</code>\n\n"
            f"Владелец карты:\n<b>{settings.card_holder_name}</b>\n\n"
            "После перевода нажмите кнопку ниже и отправьте фото чека."
        )
    return (
        f"💳 <b>پرداخت کارت به کارت</b>\n\n"
        f"مبلغ قابل پرداخت: <b>{amount:,} تومان</b>\n\n"
        f"شماره کارت:\n<code>{settings.card_number}</code>\n\n"
        f"به نام:\n<b>{settings.card_holder_name}</b>\n\n"
        "ابتدا مبلغ را واریز کنید، سپس روی «پرداخت کردم» بزنید و عکس رسید را ارسال کنید."
    )


def payment_method_text(language: str, amount: int) -> str:
    if language == "en":
        return (
            f"💰 <b>Top-up amount: {amount:,} Toman</b>\n\n"
            "Please choose your payment method:"
        )
    if language == "ru":
        return (
            f"💰 <b>Сумма пополнения: {amount:,} томан</b>\n\n"
            "Выберите способ оплаты:"
        )
    return (
        f"💰 <b>مبلغ شارژ: {amount:,} تومان</b>\n\n"
        "لطفاً روش پرداخت را انتخاب کنید:"
    )


def payment_method_keyboard(language: str, amount: int) -> InlineKeyboardMarkup:
    if language == "en":
        gateway_text = "🏦 Bank gateway"
        card_text_label = "💳 Card-to-card"
        back_text = "🔙 Back"
    elif language == "ru":
        gateway_text = "🏦 Банковский шлюз"
        card_text_label = "💳 Перевод с карты на карту"
        back_text = "🔙 Назад"
    else:
        gateway_text = "🏦 درگاه بانکی"
        card_text_label = "💳 کارت به کارت"
        back_text = "🔙 بازگشت"

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=gateway_text, callback_data=f"wallet:method:gateway:{amount}")],
            [InlineKeyboardButton(text=card_text_label, callback_data=f"wallet:method:card:{amount}")],
            [InlineKeyboardButton(text=back_text, callback_data=NavMain.WALLET)],
        ]
    )


async def has_pending_payment(session: AsyncSession, user_tg_id: int) -> bool:
    pending = await CardPayment.get_pending(session)
    return any(p.user_tg_id == user_tg_id for p in pending)


@router.callback_query(F.data == NavMain.WALLET)
async def callback_wallet(callback: CallbackQuery, user: User, services: ServicesContainer, session: AsyncSession) -> None:
    await callback.answer()
    balance = await services.wallet.get_balance(user.tg_id)
    amounts = await WalletTopupAmount.get_all(session)
    await callback.message.edit_text(
        text=wallet_text(user.language_code, balance, bool(amounts)),
        reply_markup=wallet_keyboard(amounts, user.language_code),
    )


@router.callback_query(F.data.regexp(r"^wallet:topup:\d+$"))
async def callback_wallet_topup(callback: CallbackQuery, user: User, session: AsyncSession, config: Config, state: FSMContext) -> None:
    amount_id = int(callback.data.rsplit(":", 1)[1])
    item = await WalletTopupAmount.get(session, amount_id)
    if not item or not item.is_active:
        await callback.answer("❌ این مبلغ دیگر فعال نیست.", show_alert=True)
        return

    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً منتظر بمانید.", show_alert=True)
        return

    await state.clear()
    await state.update_data(card_payment_amount=item.amount)
    await callback.answer()
    await callback.message.edit_text(
        payment_method_text(user.language_code, item.amount),
        reply_markup=payment_method_keyboard(user.language_code, item.amount),
    )


@router.callback_query(F.data == "wallet:custom")
async def callback_wallet_custom(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً منتظر بمانید.", show_alert=True)
        return

    await state.set_state(CardPaymentState.waiting_amount)
    await callback.answer()

    if user.language_code == "en":
        text = (
            "💰 <b>Custom amount</b>\n\n"
            "Please enter the amount you want to add to your wallet in Toman.\n\n"
            "Example: <code>350,000 Toman</code>"
        )
    elif user.language_code == "ru":
        text = (
            "💰 <b>Своя сумма</b>\n\n"
            "Введите сумму, которую хотите добавить в кошелёк, в томанах.\n\n"
            "Пример: <code>350 000 томан</code>"
        )
    else:
        text = (
            "💰 <b>مبلغ دلخواه</b>\n\n"
            "لطفاً مبلغ موردنظر برای شارژ کیف پول را به تومان وارد کنید.\n\n"
            "مثال: <code>۳۵۰٬۰۰۰ تومان</code>"
        )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 انصراف", callback_data=NavMain.WALLET)]
            ]
        ),
    )


@router.message(CardPaymentState.waiting_amount)
async def handle_custom_amount(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    raw = (message.text or "").strip()
    raw = raw.translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789"))
    raw = raw.replace(",", "").replace("٬", "").replace(" ", "")

    if raw.lower().endswith("toman"):
        raw = raw[:-5].strip()
    elif raw.lower().endswith("تومان"):
        raw = raw[:-5].strip()
    elif raw.lower().endswith("томан"):
        raw = raw[:-5].strip()

    if not raw.isdigit():
        await message.answer(
            "❌ <b>مبلغ نامعتبر است.</b>\n\n"
            "لطفاً مبلغ را به صورت عددی وارد کنید.\n"
            "مثال: <code>۳۵۰٬۰۰۰ تومان</code>"
        )
        return

    amount = int(raw)
    if amount <= 0:
        await message.answer("❌ مبلغ باید بیشتر از صفر باشد.")
        return
    if amount < 1000:
        await message.answer("❌ حداقل مبلغ شارژ کیف پول <b>۱٬۰۰۰ تومان</b> است.")
        return

    if await has_pending_payment(session, user.tg_id):
        await state.clear()
        await message.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً منتظر بمانید.")
        return

    await state.update_data(card_payment_amount=amount)
    await message.answer(
        payment_method_text(user.language_code, amount),
        reply_markup=payment_method_keyboard(user.language_code, amount),
    )


@router.callback_query(F.data.regexp(r"^wallet:method:gateway:\d+$"))
async def callback_payment_gateway(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext) -> None:
    amount = int(callback.data.rsplit(":", 1)[1])
    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً منتظر بمانید.", show_alert=True)
        return
    await callback.answer("🏦 درگاه بانکی به‌زودی فعال می‌شود.", show_alert=True)


@router.callback_query(F.data.regexp(r"^wallet:method:card:\d+$"))
async def callback_payment_card(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    config: Config,
) -> None:
    amount = int(callback.data.rsplit(":", 1)[1])

    if amount <= 0:
        await state.clear()
        await callback.answer("❌ مبلغ پرداخت معتبر نیست.", show_alert=True)
        return

    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً منتظر بمانید.", show_alert=True)
        return

    settings = await CardSettings.get_or_create(session, card_number=config.shop.CARD_NUMBER or "")
    if not settings.is_active or not settings.card_number or not settings.card_holder_name:
        await callback.answer("❌ پرداخت کارت به کارت در حال حاضر فعال نیست.", show_alert=True)
        return

    await state.set_state(CardPaymentState.waiting_receipt)
    await state.update_data(card_payment_amount=amount)
    await callback.answer()
    await callback.message.edit_text(
        card_text(user.language_code, settings, amount),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📋 کپی شماره کارت", copy_text=CopyTextButton(text=settings.card_number))],
                [InlineKeyboardButton(text="📋 کپی مبلغ", copy_text=CopyTextButton(text=str(amount)))],
                [InlineKeyboardButton(text="✅ پرداخت کردم", callback_data="wallet:custom:paid")],
                [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavMain.WALLET)],
            ]
        ),
    )


@router.callback_query(F.data == "wallet:custom:paid")
async def callback_custom_card_paid(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    amount = int(data.get("card_payment_amount", 0))

    if amount <= 0:
        await state.clear()
        await callback.answer("❌ درخواست پرداخت منقضی شده است.", show_alert=True)
        return

    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً منتظر بمانید.", show_alert=True)
        return

    await state.set_state(CardPaymentState.waiting_receipt)
    await callback.answer()
    await callback.message.edit_text(
        f"📷 <b>ارسال رسید پرداخت</b>\n\n"
        f"مبلغ: <b>{amount:,} تومان</b>\n\n"
        "لطفاً عکس واضح رسید واریز را همینجا ارسال کنید.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 انصراف", callback_data=NavMain.WALLET)]
            ]
        ),
    )


@router.message(CardPaymentState.waiting_receipt, F.photo)
async def receive_card_receipt(message: Message, user: User, session: AsyncSession, state: FSMContext, config: Config, bot) -> None:
    data = await state.get_data()
    amount = int(data.get("card_payment_amount", 0))
    if amount <= 0:
        await state.clear()
        await message.answer("❌ درخواست پرداخت منقضی شده است.")
        return

    if await has_pending_payment(session, user.tg_id):
        await state.clear()
        await message.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً منتظر بمانید.")
        return

    for _ in range(5):
        tracking_code = generate_tracking_code(user.tg_id)
        result = await session.execute(select(CardPayment.id).where(CardPayment.tracking_code == tracking_code))
        if result.scalar_one_or_none() is None:
            break
    else:
        await state.clear()
        await message.answer("❌ خطا در ایجاد کد پیگیری. لطفاً دوباره تلاش کنید.")
        return

    payment = await CardPayment.create(session, user.tg_id, amount, message.photo[-1].file_id, tracking_code)
    await state.clear()

    user_text = (
        "✅ <b>درخواست پرداخت شما ثبت شد.</b>\n\n"
        f"🆔 کد پیگیری: <code>{payment.tracking_code}</code>\n"
        f"💰 مبلغ پرداختی: <b>{amount:,} تومان</b>\n\n"
        "📌 پیام: پس از تأیید توسط پشتیبانی، کیف پول شما شارژ می‌شود.\n\n"
        "🙏 از صبر و شکیبایی شما متشکریم."
    )
    await message.answer(user_text)

    settings = await CardSettings.get_or_create(
        session,
        card_number=config.shop.CARD_NUMBER or "",
    )

    admin_text = (
        "💳 <b>درخواست جدید کارت به کارت</b>\n\n"
        f"🆔 کد پیگیری: <code>{payment.tracking_code}</code>\n"
        f"🆔 آیدی تلگرام پرداخت‌کننده: <code>{user.tg_id}</code>\n"
        f"💳 کارت مقصد: <code>{settings.card_number}</code>\n"
        f"💰 مبلغ: <b>{amount:,} تومان</b>\n"
        f"🧾 شماره درخواست داخلی: <code>#{payment.id}</code>"
    )
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ تأیید و شارژ کیف پول", callback_data=f"cardpay:approve:{payment.id}")],
        [InlineKeyboardButton(text="❌ رد پرداخت", callback_data=f"cardpay:reject:{payment.id}")],
        [InlineKeyboardButton(
            text="👤 مشاهده کاربر",
            callback_data=f"cardpay:user:{user.tg_id}",
        )],
    ])
    for admin_id in config.bot.ADMINS:
        try:
            await bot.send_photo(admin_id, message.photo[-1].file_id, caption=admin_text, reply_markup=markup)
        except Exception:
            logger.exception("Failed to notify admin %s about card payment %s", admin_id, payment.id)


@router.message(CardPaymentState.waiting_receipt)
async def invalid_card_receipt(message: Message) -> None:
    await message.answer("📷 لطفاً رسید را به صورت <b>عکس</b> ارسال کنید.")
