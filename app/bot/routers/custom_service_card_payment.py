import logging
from datetime import datetime
from types import SimpleNamespace

from aiogram import F, Router
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.models import ServicesContainer, SubscriptionData
from app.bot.payment_gateways._gateway import PaymentGateway
from app.bot.routers.wallet.handler import card_text, generate_tracking_code, has_pending_payment
from app.bot.utils.constants import TransactionStatus
from app.bot.utils.navigation import NavSubscription
from app.config import Config
from app.db.models import CardPayment, CardSettings, Transaction, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)

SERVICE_PAYMENT_TYPE = "service_purchase"


class CustomServiceCardPaymentState(StatesGroup):
    waiting_receipt = State()


def _build_subscription_data(data: dict, user_tg_id: int) -> SubscriptionData | None:
    stored = data.get("custom_service_subscription")
    if stored:
        try:
            subscription_data = SubscriptionData.deserialize(stored)
        except Exception:
            return None
        if subscription_data.user_id != user_tg_id:
            return None
        return subscription_data

    try:
        days = int(data["custom_service_days"])
        gigabytes = int(data["custom_service_gigabytes"])
        devices = int(data["custom_service_devices"])
        total = int(round(float(data["custom_service_total"])))
    except (KeyError, TypeError, ValueError):
        return None

    if not (7 <= days <= 90 and 5 <= gigabytes <= 400 and 2 <= devices <= 10 and total > 0):
        return None

    config_name = data.get("custom_service_config_name") or f"{gigabytes}GB-{days}D-tg{user_tg_id}-sub101-custom"
    return SubscriptionData(
        state=NavSubscription.CONFIG_NAME,
        is_extend=data.get("custom_service_is_extend", False),
        is_change=data.get("custom_service_is_change", False),
        user_id=data.get("custom_service_user_id", user_tg_id),
        devices=devices,
        duration=days,
        price=total,
        plan_id=data.get("custom_service_plan_id", 0),
        volume_gb=gigabytes,
        config_name=config_name,
    )


def _service_card_keyboard(card_number: str, amount: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 کپی شماره کارت", copy_text=CopyTextButton(text=card_number))],
            [InlineKeyboardButton(text="📋 کپی مبلغ", copy_text=CopyTextButton(text=str(amount)))],
            [InlineKeyboardButton(text="✅ پرداخت کردم", callback_data="custom_service:card:paid")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="custom_service:back")],
        ]
    )


@router.callback_query(F.data == "custom_service:payment:card")
async def custom_service_payment_card(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    config: Config,
) -> None:
    data = await state.get_data()
    subscription_data = _build_subscription_data(data, user.tg_id)
    if not subscription_data:
        await state.clear()
        await callback.answer("❌ فاکتور سرویس منقضی یا نامعتبر است.", show_alert=True)
        return

    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً منتظر بمانید.", show_alert=True)
        return

    settings = await CardSettings.get_or_create(
        session,
        card_number=config.shop.CARD_NUMBER or "",
    )
    if not settings.is_active or not settings.card_number or not settings.card_holder_name:
        await callback.answer("❌ پرداخت کارت به کارت در حال حاضر فعال نیست.", show_alert=True)
        return

    stored_subscription = subscription_data.serialize()
    await state.set_state(CustomServiceCardPaymentState.waiting_receipt)
    await state.update_data(
        custom_service_subscription=stored_subscription,
        custom_service_total=int(subscription_data.price),
    )
    await callback.answer()
    await callback.message.edit_text(
        card_text(user.language_code, settings, int(subscription_data.price)),
        reply_markup=_service_card_keyboard(settings.card_number, int(subscription_data.price)),
    )


@router.callback_query(F.data == "custom_service:card:paid")
async def custom_service_card_paid(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    stored_subscription = data.get("custom_service_subscription")
    if not stored_subscription:
        await state.clear()
        await callback.answer("❌ درخواست پرداخت منقضی شده است.", show_alert=True)
        return

    await state.set_state(CustomServiceCardPaymentState.waiting_receipt)
    await callback.answer()
    await callback.message.edit_text(
        f"📷 <b>ارسال رسید پرداخت سرویس</b>\n\n"
        f"مبلغ: <b>{int(data.get('custom_service_total', 0)):,} تومان</b>\n\n"
        "لطفاً عکس واضح رسید واریز را همینجا ارسال کنید.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 انصراف", callback_data="custom_service:back")]
            ]
        ),
    )


@router.message(CustomServiceCardPaymentState.waiting_receipt, F.photo)
async def receive_custom_service_receipt(
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

    if not stored_subscription or amount <= 0:
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

    await message.answer(
        "✅ <b>درخواست خرید سرویس ثبت شد.</b>\n\n"
        f"🆔 کد پیگیری: <code>{payment.tracking_code}</code>\n"
        f"📦 سرویس: <b>{subscription_data.volume_gb} گیگ | {subscription_data.duration} روز | {subscription_data.devices} کاربر</b>\n"
        f"💰 مبلغ: <b>{amount:,} تومان</b>\n\n"
        "📌 پس از تأیید پرداخت توسط مدیریت، <b>همین سرویس مستقیماً ساخته و تحویل شما می‌شود</b>."
    )

    settings = await CardSettings.get_or_create(
        session,
        card_number=config.shop.CARD_NUMBER or "",
    )
    admin_text = (
        "🛒 <b>درخواست جدید خرید سرویس با کارت به کارت</b>\n\n"
        f"🆔 کد پیگیری: <code>{payment.tracking_code}</code>\n"
        f"👤 آیدی تلگرام: <code>{user.tg_id}</code>\n"
        f"📦 سرویس: <b>{subscription_data.volume_gb} گیگ | {subscription_data.duration} روز | {subscription_data.devices} کاربر</b>\n"
        f"💰 مبلغ: <b>{amount:,} تومان</b>\n"
        f"🧾 شماره درخواست: <code>#{payment.id}</code>\n"
        f"💳 کارت مقصد: <code>{settings.card_number}</code>"
    )
    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔎 مشاهده سفارش", callback_data=f"cardpay:view:{payment.id}")],
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
            logger.exception("Failed to notify admin %s about service card payment %s", admin_id, payment.id)


@router.message(CustomServiceCardPaymentState.waiting_receipt)
async def invalid_custom_service_receipt(message: Message) -> None:
    await message.answer("📷 لطفاً رسید را به صورت <b>عکس</b> ارسال کنید.")


async def _get_service_payment(session: AsyncSession, callback_data: str) -> CardPayment | None:
    payment_id = int(callback_data.rsplit(":", 1)[1])
    payment = await CardPayment.get(session, payment_id)
    if not payment or payment.payment_type != SERVICE_PAYMENT_TYPE or not payment.order_data:
        return None
    return payment


@router.callback_query(F.data.regexp(r"^cardpay:view:\d+$"), IsAdmin())
async def service_card_payment_view(callback: CallbackQuery, session: AsyncSession) -> object:
    payment = await _get_service_payment(session, callback.data or "")
    if not payment:
        return UNHANDLED

    try:
        subscription_data = SubscriptionData.deserialize(payment.order_data or "")
    except Exception:
        await callback.answer("❌ اطلاعات سفارش سرویس خراب یا نامعتبر است.", show_alert=True)
        return None

    await callback.answer()
    await callback.message.bot.send_photo(
        callback.from_user.id,
        payment.receipt_file_id,
        caption=(
            "🛒 <b>درخواست خرید سرویس با کارت به کارت</b>\n\n"
            f"🆔 کد پیگیری: <code>{payment.tracking_code or f'#{payment.id}'}</code>\n"
            f"👤 آیدی تلگرام: <code>{payment.user_tg_id}</code>\n"
            f"📦 سرویس: <b>{subscription_data.volume_gb} گیگ | {subscription_data.duration} روز | {subscription_data.devices} کاربر</b>\n"
            f"💰 مبلغ: <b>{payment.amount:,} تومان</b>\n"
            f"🧾 شماره درخواست: <code>#{payment.id}</code>\n"
            f"📌 وضعیت: <b>{payment.status}</b>"
        ),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ تأیید و ایجاد سرویس", callback_data=f"cardpay:approve:{payment.id}")],
                [InlineKeyboardButton(text="❌ رد پرداخت", callback_data=f"cardpay:reject:{payment.id}")],
            ]
        ),
    )
    return None


@router.callback_query(F.data.regexp(r"^cardpay:approve:\d+$"), IsAdmin())
async def service_card_payment_approve(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    db,
    bot,
    config: Config,
    storage,
    i18n,
    services: ServicesContainer,
) -> object:
    payment_id = int((callback.data or "").rsplit(":", 1)[1])
    locked_result = await session.execute(
        select(CardPayment).where(CardPayment.id == payment_id).with_for_update()
    )
    payment = locked_result.scalar_one_or_none()
    if not payment or payment.payment_type != SERVICE_PAYMENT_TYPE or not payment.order_data:
        return UNHANDLED

    if payment.status != "pending":
        await callback.answer("⚠️ این درخواست قبلاً بررسی شده است.", show_alert=True)
        return None

    try:
        subscription_data = SubscriptionData.deserialize(payment.order_data)
    except Exception:
        await callback.answer("❌ اطلاعات سفارش سرویس نامعتبر است.", show_alert=True)
        return None

    if subscription_data.user_id != payment.user_tg_id or int(subscription_data.price) != payment.amount:
        await callback.answer("❌ مبلغ یا مالک سفارش با درخواست پرداخت مطابقت ندارد.", show_alert=True)
        return None

    payment.status = "processing"
    payment.admin_tg_id = user.tg_id

    payment_id = f"card_payment:{payment.id}"
    try:
        async with db.session() as transaction_session:
            transaction = await Transaction.create(
                session=transaction_session,
                tg_id=payment.user_tg_id,
                subscription=subscription_data.serialize(),
                payment_id=payment_id,
                status=TransactionStatus.PENDING,
            )
            if transaction is None:
                transaction = await Transaction.get_by_id(
                    session=transaction_session,
                    payment_id=payment_id,
                )
            if transaction is None:
                raise RuntimeError("Unable to create or recover service transaction")

        context = SimpleNamespace(
            session=db.session,
            config=config,
            services=services,
            bot=bot,
            i18n=i18n,
            storage=storage,
        )
        await PaymentGateway._on_payment_succeeded(context, payment_id=payment_id)

        payment.status = "approved"
        payment.reviewed_at = datetime.now()
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.exception("Failed to fulfill custom service card payment %s: %s", payment_id, exc)
        await callback.answer("❌ ساخت یا تحویل سرویس انجام نشد؛ درخواست به حالت بررسی برگشت.", show_alert=True)
        return None

    await callback.answer("✅ پرداخت تأیید و سرویس مستقیماً ساخته و تحویل شد.", show_alert=True)
    if callback.message and callback.message.photo:
        await callback.message.edit_caption(
            caption=(callback.message.caption or "")
            + f"\n\n✅ <b>تأیید و سرویس ایجاد شد</b> توسط <code>{user.tg_id}</code>"
        )
    return None


@router.callback_query(F.data == "custom_service:back")
async def custom_service_card_back(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer()
    await callback.message.edit_text(
        "🛒 <b>خرید سرویس اختصاصی</b>\n\nبرای ادامه، دوباره مشخصات سرویس را وارد کنید."
    )
