import logging

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.routers.custom_service_card_payment import CustomServiceCardPaymentState, SERVICE_PAYMENT_TYPE
from app.bot.routers.wallet.handler import generate_tracking_code, has_pending_payment
from app.config import Config
from app.db.models import CardPayment, CardSettings, User

logger = logging.getLogger(__name__)

from aiogram import Router
router = Router(name=__name__)


@router.message(CustomServiceCardPaymentState.waiting_receipt, F.photo)
async def receive_selected_service_receipt(
    message: Message,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    config: Config,
    bot,
) -> None:
    data = await state.get_data()
    stored_subscription = data.get("custom_service_subscription")
    amount = int(data.get("custom_service_total", 0))
    card_id = int(data.get("card_payment_card_id", 0))

    if not stored_subscription or amount <= 0 or card_id <= 0:
        await state.clear()
        await message.answer("❌ درخواست پرداخت منقضی شده است.")
        return

    try:
        subscription_data = SubscriptionData.deserialize(stored_subscription)
    except Exception:
        await state.clear()
        await message.answer("❌ اطلاعات سفارش سرویس نامعتبر است. لطفاً دوباره سفارش دهید.")
        return

    if subscription_data.user_id != user.tg_id or int(subscription_data.price) != amount:
        await state.clear()
        await message.answer("❌ اطلاعات سفارش با کاربر یا مبلغ پرداخت مطابقت ندارد.")
        return

    if await has_pending_payment(session, user.tg_id):
        await state.clear()
        await message.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً منتظر بمانید.")
        return

    card = await session.get(CardSettings, card_id)
    if not card:
        await state.clear()
        await message.answer("❌ کارت انتخاب‌شده دیگر موجود نیست. لطفاً دوباره سفارش دهید.")
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
        payment_type=SERVICE_PAYMENT_TYPE,
        order_data=stored_subscription,
    )
    await state.clear()

    action_text = "تمدید سرویس" if subscription_data.is_extend else "خرید سرویس"
    await message.answer(
        f"✅ <b>درخواست {action_text} ثبت شد.</b>\n\n"
        f"🆔 کد پیگیری: <code>{payment.tracking_code}</code>\n"
        f"📦 سرویس: <b>{subscription_data.volume_gb} گیگ | {subscription_data.duration} روز | {subscription_data.devices} کاربر</b>\n"
        f"💰 مبلغ: <b>{amount:,} تومان</b>\n\n"
        "📌 پس از تأیید پرداخت توسط مدیریت، درخواست شما پردازش می‌شود."
    )

    admin_action = "تمدید سرویس" if subscription_data.is_extend else "خرید سرویس"
    admin_text = (
        f"🛒 <b>درخواست جدید {admin_action} با کارت به کارت</b>\n\n"
        f"🆔 کد پیگیری: <code>{payment.tracking_code}</code>\n"
        f"👤 آیدی تلگرام: <code>{user.tg_id}</code>\n"
        f"📦 سرویس: <b>{subscription_data.volume_gb} گیگ | {subscription_data.duration} روز | {subscription_data.devices} کاربر</b>\n"
        f"💰 مبلغ: <b>{amount:,} تومان</b>\n"
        f"🧾 شماره درخواست: <code>#{payment.id}</code>\n"
        f"💳 کارت مقصد: <code>{card.card_number}</code>\n"
        f"🏦 بانک: <b>{card.bank_name or 'ثبت نشده'}</b>\n"
        f"👤 بنام: <b>{card.card_holder_name}</b>"
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔎 مشاهده سفارش", callback_data=f"service_cardpay:view:{payment.id}")],
            [InlineKeyboardButton(text="❌ رد پرداخت", callback_data=f"service_cardpay:reject:{payment.id}")],
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
                "Failed to notify admin %s about service card payment %s",
                admin_id,
                payment.id,
            )


@router.message(CustomServiceCardPaymentState.waiting_receipt)
async def invalid_selected_service_receipt(message: Message) -> None:
    await message.answer("📷 لطفاً رسید را به صورت <b>عکس</b> ارسال کنید.")
