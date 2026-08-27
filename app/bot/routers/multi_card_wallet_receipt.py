import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.routers.wallet.handler import CardPaymentState, generate_tracking_code, has_pending_payment
from app.config import Config
from app.db.models import CardPayment, CardSettings, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


@router.message(CardPaymentState.waiting_receipt, F.photo)
async def receive_selected_wallet_receipt(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    config: Config,
    bot,
) -> None:
    data = await state.get_data()
    amount = int(data.get("card_payment_amount", 0))
    card_id = int(data.get("card_payment_card_id", 0))

    if amount <= 0 or card_id <= 0:
        await state.clear()
        await message.answer("❌ درخواست پرداخت منقضی شده است.")
        return

    if await has_pending_payment(session, user.tg_id):
        await state.clear()
        await message.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً منتظر بمانید.")
        return

    card = await session.get(CardSettings, card_id)
    if not card:
        await state.clear()
        await message.answer("❌ کارت انتخاب‌شده دیگر موجود نیست. لطفاً دوباره پرداخت را شروع کنید.")
        return

    for _ in range(5):
        tracking_code = generate_tracking_code(user.tg_id)
        result = await session.execute(
            select(CardPayment.id).where(CardPayment.tracking_code == tracking_code)
        )
        if result.scalar_one_or_none() is None:
            break
    else:
        await state.clear()
        await message.answer("❌ خطا در ایجاد کد پیگیری. لطفاً دوباره تلاش کنید.")
        return

    payment = await CardPayment.create(
        session,
        user.tg_id,
        amount,
        message.photo[-1].file_id,
        tracking_code,
    )
    await state.clear()

    await message.answer(
        "✅ <b>درخواست پرداخت شما ثبت شد.</b>\n\n"
        f"🆔 کد پیگیری: <code>{payment.tracking_code}</code>\n"
        f"💰 مبلغ پرداختی: <b>{amount:,} تومان</b>\n\n"
        "📌 پس از تأیید توسط پشتیبانی، کیف پول شما شارژ می‌شود.\n\n"
        "🙏 از صبر و شکیبایی شما متشکریم."
    )

    admin_text = (
        "💳 <b>درخواست جدید کارت به کارت</b>\n\n"
        f"🆔 کد پیگیری: <code>{payment.tracking_code}</code>\n"
        f"🆔 آیدی تلگرام پرداخت‌کننده: <code>{user.tg_id}</code>\n"
        f"💳 کارت مقصد: <code>{card.card_number}</code>\n"
        f"🏦 بانک: <b>{card.bank_name or 'ثبت نشده'}</b>\n"
        f"👤 بنام: <b>{card.card_holder_name}</b>\n"
        f"💰 مبلغ: <b>{amount:,} تومان</b>\n"
        f"🧾 شماره درخواست داخلی: <code>#{payment.id}</code>"
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ تأیید و شارژ کیف پول", callback_data=f"cardpay:approve:{payment.id}")],
            [InlineKeyboardButton(text="❌ رد پرداخت", callback_data=f"cardpay:reject:{payment.id}")],
            [InlineKeyboardButton(text="👤 مشاهده کاربر", callback_data=f"cardpay:user:{user.tg_id}")],
        ]
    )

    for admin_id in config.bot.ADMINS:
        try:
            await bot.send_photo(
                admin_id,
                message.photo[-1].file_id,
                caption=admin_text,
                reply_markup=markup,
            )
        except Exception:
            logger.exception(
                "Failed to notify admin %s about card payment %s",
                admin_id,
                payment.id,
            )


@router.message(CardPaymentState.waiting_receipt)
async def invalid_selected_wallet_receipt(message: Message) -> None:
    await message.answer("📷 لطفاً رسید را به صورت <b>عکس</b> ارسال کنید.")
