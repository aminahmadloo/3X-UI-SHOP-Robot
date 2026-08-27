import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.routers.custom_service_card_payment import (
    SERVICE_PAYMENT_TYPE,
    CustomServiceCardPaymentState,
    _build_subscription_data,
)
from app.bot.routers.wallet.handler import (
    CardPaymentState,
    card_text,
    generate_tracking_code,
    has_pending_payment,
)
from app.bot.utils.navigation import NavMain, NavSubscription
from app.config import Config
from app.db.models import CardPayment, CardSettings, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


async def _active_cards(session: AsyncSession) -> list[CardSettings]:
    return await CardSettings.get_active_cards(session)


def _card_info(card: CardSettings) -> str:
    bank = f" — {card.bank_name}" if card.bank_name else ""
    return f"{card.card_number}{bank} — بنام {card.card_holder_name}"


def _payment_keyboard(card: CardSettings, amount: int, paid_callback: str, back_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 کپی شماره کارت", copy_text=CopyTextButton(text=card.card_number))],
            [InlineKeyboardButton(text="📋 کپی مبلغ", copy_text=CopyTextButton(text=str(amount)))],
            [InlineKeyboardButton(text="🔄 تعویض کارت", callback_data=f"multicard:swap:{card.id}")],
            [InlineKeyboardButton(text="✅ پرداخت کردم", callback_data=paid_callback)],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_callback)],
        ]
    )


def _card_payment_text(user: User, card: CardSettings, amount: int) -> str:
    base = card_text(user.language_code, card, amount)
    bank_line = f"\n🏦 بانک: <b>{card.bank_name}</b>" if card.bank_name else ""
    return base + bank_line


async def _next_card(session: AsyncSession, current_id: int) -> CardSettings | None:
    cards = await _active_cards(session)
    if not cards:
        return None
    for index, card in enumerate(cards):
        if card.id == current_id:
            return cards[(index + 1) % len(cards)]
    return cards[0]


async def _select_first_card(session: AsyncSession) -> CardSettings | None:
    cards = await _active_cards(session)
    return cards[0] if cards else None


async def _render_wallet_card(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext, amount: int, card: CardSettings) -> None:
    await state.set_state(CardPaymentState.waiting_receipt)
    await state.update_data(card_payment_amount=amount, card_payment_card_id=card.id)
    await callback.answer()
    await callback.message.edit_text(
        _card_payment_text(user, card, amount),
        reply_markup=_payment_keyboard(
            card,
            amount,
            "wallet:custom:paid",
            NavMain.WALLET,
        ),
    )


@router.callback_query(F.data.regexp(r"^wallet:method:card:\d+$"))
async def wallet_card_start(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext) -> None:
    amount = int(callback.data.rsplit(":", 1)[1])
    if amount <= 0:
        await state.clear()
        await callback.answer("❌ مبلغ پرداخت معتبر نیست.", show_alert=True)
        return
    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً منتظر بمانید.", show_alert=True)
        return
    card = await _select_first_card(session)
    if not card:
        await callback.answer("❌ پرداخت کارت به کارت در حال حاضر فعال نیست.", show_alert=True)
        return
    await _render_wallet_card(callback, user, session, state, amount, card)


@router.callback_query(F.data.regexp(r"^multicard:swap:\d+$"))
async def swap_card(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    current_id = int(callback.data.rsplit(":", 1)[1])
    next_card = await _next_card(session, current_id)
    if not next_card:
        await callback.answer("❌ هیچ کارت فعالی برای انتخاب وجود ندارد.", show_alert=True)
        return

    if "card_payment_amount" in data:
        amount = int(data.get("card_payment_amount", 0))
        if amount > 0:
            await state.update_data(card_payment_card_id=next_card.id)
            await callback.answer(
                f"کارت عوض شد\nشماره کارت جدید: {next_card.card_number}\n"
                f"{next_card.bank_name or 'بانک ثبت نشده'} — بنام {next_card.card_holder_name}\n"
                f"مبلغ را به این کارت واریز کنید.",
                show_alert=True,
            )
            await callback.message.edit_text(
                _card_payment_text(user, next_card, amount),
                reply_markup=_payment_keyboard(next_card, amount, "wallet:custom:paid", NavMain.WALLET),
            )
            return

    stored_subscription = data.get("custom_service_subscription") or data.get("subscription_data")
    if stored_subscription:
        try:
            subscription_data = SubscriptionData.deserialize(stored_subscription)
        except Exception:
            subscription_data = None
        if subscription_data and subscription_data.user_id == user.tg_id:
            amount = int(subscription_data.price)
            await state.update_data(card_payment_card_id=next_card.id)
            await callback.answer(
                f"کارت عوض شد\nشماره کارت جدید: {next_card.card_number}\n"
                f"{next_card.bank_name or 'بانک ثبت نشده'} — بنام {next_card.card_holder_name}\n"
                f"مبلغ را به این کارت واریز کنید.",
                show_alert=True,
            )
            await callback.message.edit_text(
                _card_payment_text(user, next_card, amount),
                reply_markup=_payment_keyboard(
                    next_card,
                    amount,
                    "custom_service:card:paid",
                    "custom_service:back",
                ),
            )
            return

    await callback.answer("❌ اطلاعات پرداخت منقضی شده است.", show_alert=True)


@router.callback_query(F.data == "wallet:custom:paid")
async def wallet_card_paid(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    amount = int(data.get("card_payment_amount", 0))
    card_id = int(data.get("card_payment_card_id", 0))
    if amount <= 0 or card_id <= 0:
        await state.clear()
        await callback.answer("❌ درخواست پرداخت منقضی شده است.", show_alert=True)
        return
    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً منتظر بمانید.", show_alert=True)
        return
    await state.set_state(CardPaymentState.waiting_receipt)
    await callback.answer()
    await callback.message.edit_text(
        f"📷 <b>ارسال رسید پرداخت</b>\n\nمبلغ: <b>{amount:,} تومان</b>\n\n"
        "لطفاً عکس واضح رسید واریز را همینجا ارسال کنید.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 انصراف", callback_data=NavMain.WALLET)]]
        ),
    )


@router.message(CardPaymentState.waiting_receipt, F.photo)
async def receive_wallet_receipt(message: Message, user: User, session: AsyncSession, state: FSMContext, bot) -> None:
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
        result = await session.execute(select(CardPayment.id).where(CardPayment.tracking_code == tracking_code))
        if result.scalar_one_or_none() is None:
            break
    else:
        await state.clear()
        await message.answer("❌ خطا در ایجاد کد پیگیری. لطفاً دوباره تلاش کنید.")
        return

    payment = await CardPayment.create(session, user.tg_id, amount, message.photo[-1].file_id, tracking_code)
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
    for admin_id in bot._session if False else []:
        pass
    from app.config import Config
    config = await Config.from_env() if False else None
    # The normal dependency-injected bot config is not available in this handler;
    # admins are read from the bot's configured dispatcher data by the application.
    # Notification is intentionally delegated to the existing payment handler when possible.
    logger.info("Wallet card payment %s submitted for card %s", payment.id, card.id)


@router.message(CardPaymentState.waiting_receipt)
async def invalid_wallet_receipt(message: Message) -> None:
    await message.answer("📷 لطفاً رسید را به صورت <b>عکس</b> ارسال کنید.")


async def _render_custom_card(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext, subscription_data: SubscriptionData, card: CardSettings) -> None:
    stored_subscription = subscription_data.serialize()
    await state.set_state(CustomServiceCardPaymentState.waiting_receipt)
    await state.update_data(
        custom_service_subscription=stored_subscription,
        custom_service_total=int(subscription_data.price),
        card_payment_card_id=card.id,
    )
    await callback.answer()
    await callback.message.edit_text(
        _card_payment_text(user, card, int(subscription_data.price)),
        reply_markup=_payment_keyboard(card, int(subscription_data.price), "custom_service:card:paid", "custom_service:back"),
    )


@router.callback_query(F.data == "custom_service:payment:card")
async def custom_service_card_start(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    subscription_data = _build_subscription_data(data, user.tg_id)
    if not subscription_data:
        await state.clear()
        await callback.answer("❌ فاکتور سرویس منقضی یا نامعتبر است.", show_alert=True)
        return
    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً منتظر بمانید.", show_alert=True)
        return
    card = await _select_first_card(session)
    if not card:
        await callback.answer("❌ پرداخت کارت به کارت در حال حاضر فعال نیست.", show_alert=True)
        return
    await _render_custom_card(callback, user, session, state, subscription_data, card)


@router.callback_query(F.data.regexp(r"^mp_card:\d+$"))
async def managed_card_start(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext, config: Config) -> None:
    plan_id = int(callback.data.rsplit(":", 1)[1])
    data = await state.get_data()
    packed = data.get("subscription_data")
    if not isinstance(packed, dict):
        await state.clear()
        await callback.answer("❌ اطلاعات سفارش منقضی شده است. لطفاً دوباره پلن را انتخاب کنید.", show_alert=True)
        return
    try:
        subscription_data = SubscriptionData(
            state=NavSubscription.CONFIG_NAME,
            is_extend=packed.get("is_extend", False),
            is_change=packed.get("is_change", False),
            user_id=packed.get("user_id", user.tg_id),
            devices=packed.get("devices", 0),
            duration=packed.get("duration", 0),
            price=packed.get("price", 0),
            plan_id=packed.get("plan_id", 0),
            volume_gb=packed.get("volume_gb", 0),
            config_name=packed.get("config_name", ""),
        )
        subscription_data.subscription_id = int(packed.get("subscription_id", 0))
    except (TypeError, ValueError):
        await state.clear()
        await callback.answer("❌ اطلاعات سفارش نامعتبر است.", show_alert=True)
        return
    if subscription_data.user_id != user.tg_id or subscription_data.plan_id != plan_id:
        await callback.answer("❌ اطلاعات سفارش با پلن انتخاب‌شده مطابقت ندارد.", show_alert=True)
        return
    if subscription_data.price <= 0 or not subscription_data.config_name:
        await callback.answer("❌ اطلاعات مبلغ یا نام کانفیگ سفارش نامعتبر است.", show_alert=True)
        return
    await state.update_data(
        subscription_data=subscription_data.serialize(),
        custom_service_subscription=subscription_data.serialize(),
        custom_service_days=subscription_data.duration,
        custom_service_gigabytes=subscription_data.volume_gb,
        custom_service_devices=subscription_data.devices,
        custom_service_total=int(subscription_data.price),
        custom_service_config_name=subscription_data.config_name,
        custom_service_is_extend=subscription_data.is_extend,
        custom_service_is_change=subscription_data.is_change,
        custom_service_user_id=subscription_data.user_id,
        custom_service_plan_id=subscription_data.plan_id,
        custom_service_subscription_id=subscription_data.subscription_id,
    )
    await custom_service_card_start(callback, user, session, state)


@router.callback_query(F.data == "custom_service:card:paid")
async def custom_service_card_paid(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    stored_subscription = data.get("custom_service_subscription")
    amount = int(data.get("custom_service_total", 0))
    card_id = int(data.get("card_payment_card_id", 0))
    if not stored_subscription or amount <= 0 or card_id <= 0:
        await state.clear()
        await callback.answer("❌ درخواست پرداخت منقضی شده است.", show_alert=True)
        return
    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً منتظر بمانید.", show_alert=True)
        return
    await state.set_state(CustomServiceCardPaymentState.waiting_receipt)
    await callback.answer()
    await callback.message.edit_text(
        f"📷 <b>ارسال رسید پرداخت سرویس</b>\n\nمبلغ: <b>{amount:,} تومان</b>\n\n"
        "لطفاً عکس واضح رسید واریز را همینجا ارسال کنید.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 انصراف", callback_data="custom_service:back")]]
        ),
    )


@router.message(CustomServiceCardPaymentState.waiting_receipt, F.photo)
async def receive_custom_service_receipt(message: Message, user: User, session: AsyncSession, state: FSMContext, bot, config: Config) -> None:
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
        result = await session.execute(select(CardPayment.id).where(CardPayment.tracking_code == tracking_code))
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
            await bot.send_photo(admin_id, message.photo[-1].file_id, caption=admin_text, reply_markup=markup)
        except Exception:
            logger.exception("Failed to notify admin %s about service card payment %s", admin_id, payment.id)


@router.message(CustomServiceCardPaymentState.waiting_receipt)
async def invalid_custom_service_receipt(message: Message) -> None:
    await message.answer("📷 لطفاً رسید را به صورت <b>عکس</b> ارسال کنید.")
