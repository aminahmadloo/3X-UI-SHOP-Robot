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
            f"Card number:\n<code>{settings.card_number}</code>\n"
            f"🏦 Bank: <b>{settings.bank_name or 'Unknown'}</b>\n"
            f"Card holder:\n<b>{settings.card_holder_name}</b>\n"
            f"Amount: <b>{amount:,} Toman</b>\n"
            "After transferring the amount, press the button below and send the receipt image."
        )
    if language == "ru":
        return (
            f"💳 <b>Оплата переводом</b>\n\n"
            f"Номер карты:\n<code>{settings.card_number}</code>\n"
            f"🏦 Банк: <b>{settings.bank_name or 'Неизвестно'}</b>\n"
            f"Владелец карты:\n<b>{settings.card_holder_name}</b>\n"
            f"Сумма: <b>{amount:,} томан</b>\n"
            "После перевода нажмите кнопку ниже и отправьте фото чека."
        )
    return (
        f"💳 <b>پرداخت کارت به\nکارت</b>\n\n"
        f"شماره کارت:\n<b>{settings.card_number}</b>\n"
        f"🏦 بانک: <b>{settings.bank_name or 'نامشخص'}</b>\n"
        f"به نام:\n<b>{settings.card_holder_name}</b>\n\n"
        f"مبلغ قابل پرداخت: <b>{amount:,} تومان</b>\n\n"
        "ابتدا مبلغ را واریز کنید، سپس روی «پرداخت کردم-رسید می فرستم» بزنید و عکس رسید را ارسال کنید."
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
            "لطفاً مبلغ موردنظر برای شارژ را به تومان وارد کنید.\n\n"
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
