import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.routers.custom_service_card_payment import CustomServiceCardPaymentState, _build_subscription_data
from app.bot.routers.wallet.handler import CardPaymentState, card_text, has_pending_payment
from app.bot.utils.navigation import NavMain, NavSubscription
from app.config import Config
from app.db.models import CardSettings, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


async def _cards(session: AsyncSession) -> list[CardSettings]:
    return await CardSettings.get_active_cards(session)


async def _first_card(session: AsyncSession) -> CardSettings | None:
    cards = await _cards(session)
    return cards[0] if cards else None


async def _next_card(session: AsyncSession, current_id: int) -> CardSettings | None:
    cards = await _cards(session)
    if not cards:
        return None
    for index, card in enumerate(cards):
        if card.id == current_id:
            return cards[(index + 1) % len(cards)]
    return cards[0]


def _payment_text(user: User, card: CardSettings, amount: int) -> str:
    text = card_text(user.language_code, card, amount)
    if card.bank_name:
        text += f"\n🏦 بانک: <b>{card.bank_name}</b>"
    return text


def _keyboard(card: CardSettings, amount: int, paid_callback: str, back_callback: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 کپی شماره کارت",
                    copy_text=CopyTextButton(text=card.card_number),
                ),
                InlineKeyboardButton(
                    text="📋 کپی مبلغ",
                    copy_text=CopyTextButton(text=str(amount)),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔄 تعویض کارت",
                    callback_data=f"multicard:swap:{card.id}",
                    style="success",
                )
            ],
            [
                InlineKeyboardButton(
                    text="✅ پرداخت کردم-- رسید می فرستم",
                    callback_data=paid_callback,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت",
                    callback_data=back_callback,
                )
            ],
        ]
    )


def _swap_alert(card: CardSettings) -> str:
    bank = card.bank_name or "بانک ثبت نشده"
    return (
        "کارت عوض شد\n"
        f"شماره کارت جدید: {card.card_number}\n"
        f"{bank} — بنام {card.card_holder_name}\n"
        "مبلغ را به این کارت واریز کنید."
    )


async def _render_wallet(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext, card: CardSettings, amount: int) -> None:
    await state.set_state(CardPaymentState.waiting_receipt)
    await state.update_data(card_payment_amount=amount, card_payment_card_id=card.id)
    await callback.answer()
    await callback.message.edit_text(
        _payment_text(user, card, amount),
        reply_markup=_keyboard(card, amount, "wallet:custom:paid", NavMain.WALLET),
    )


async def _render_service(callback: CallbackQuery, user: User, state: FSMContext, card: CardSettings, subscription_data: SubscriptionData) -> None:
    amount = int(subscription_data.price)
    await state.set_state(CustomServiceCardPaymentState.waiting_receipt)
    await state.update_data(
        custom_service_subscription=subscription_data.serialize(),
        custom_service_total=amount,
        card_payment_card_id=card.id,
    )
    await callback.answer()
    await callback.message.edit_text(
        _payment_text(user, card, amount),
        reply_markup=_keyboard(card, amount, "custom_service:card:paid", "custom_service:back"),
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
    card = await _first_card(session)
    if not card:
        await callback.answer("❌ پرداخت کارت به کارت در حال حاضر فعال نیست.", show_alert=True)
        return
    await _render_wallet(callback, user, session, state, card, amount)


@router.callback_query(F.data.regexp(r"^multicard:swap:\d+$"))
async def swap_card(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    current_id = int(callback.data.rsplit(":", 1)[1])
    card = await _next_card(session, current_id)
    if not card:
        await callback.answer("❌ هیچ کارت فعالی برای انتخاب وجود ندارد.", show_alert=True)
        return

    stored_subscription = data.get("custom_service_subscription") or data.get("subscription_data")
    if stored_subscription:
        try:
            if isinstance(stored_subscription, str):
                subscription_data = SubscriptionData.deserialize(stored_subscription)
            elif isinstance(stored_subscription, dict):
                subscription_data = SubscriptionData(
                    state=NavSubscription.CONFIG_NAME,
                    is_extend=stored_subscription.get("is_extend", False),
                    is_change=stored_subscription.get("is_change", False),
                    user_id=stored_subscription.get("user_id", user.tg_id),
                    devices=stored_subscription.get("devices", 0),
                    duration=stored_subscription.get("duration", 0),
                    price=stored_subscription.get("price", 0),
                    plan_id=stored_subscription.get("plan_id", 0),
                    volume_gb=stored_subscription.get("volume_gb", 0),
                    config_name=stored_subscription.get("config_name", ""),
                )
                subscription_data.subscription_id = stored_subscription.get("subscription_id", 0)
            else:
                subscription_data = None
        except Exception:
            subscription_data = None
        if subscription_data and subscription_data.user_id == user.tg_id:
            await state.update_data(card_payment_card_id=card.id)
            await callback.answer(_swap_alert(card), show_alert=True)
            await callback.message.edit_text(
                _payment_text(user, card, int(subscription_data.price)),
                reply_markup=_keyboard(card, int(subscription_data.price), "custom_service:card:paid", "custom_service:back"),
            )
            return

    amount = int(data.get("card_payment_amount", 0))
    if amount > 0:
        await state.update_data(card_payment_card_id=card.id)
        await callback.answer(_swap_alert(card), show_alert=True)
        await callback.message.edit_text(
            _payment_text(user, card, amount),
            reply_markup=_keyboard(card, amount, "wallet:custom:paid", NavMain.WALLET),
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
    card = await _first_card(session)
    if not card:
        await callback.answer("❌ پرداخت کارت به کارت در حال حاضر فعال نیست.", show_alert=True)
        return
    await _render_service(callback, user, state, card, subscription_data)


@router.callback_query(F.data.regexp(r"^mp_card:\d+$"))
async def managed_card_start(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext, config: Config) -> None:
    plan_id = int(callback.data.rsplit(":", 1)[1])
    data = await state.get_data()
    packed = data.get("subscription_data")

    # The canonical purchase context is a dict. Older managed-card code stored
    # a serialized string here, especially after the first payment attempt.
    # Accept both representations so returning from a payment screen never
    # invalidates the order context.
    if isinstance(packed, str):
        try:
            restored = SubscriptionData.deserialize(packed)
            packed = {
                "is_extend": restored.is_extend,
                "is_change": restored.is_change,
                "user_id": restored.user_id,
                "devices": restored.devices,
                "duration": restored.duration,
                "price": restored.price,
                "plan_id": restored.plan_id,
                "volume_gb": restored.volume_gb,
                "config_name": restored.config_name,
                "subscription_id": restored.subscription_id,
            }
        except Exception:
            packed = None

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

    # Keep subscription_data in its canonical dict form in FSM. The dedicated
    # card-receipt context remains serialized separately for receipt handling.
    await state.update_data(
        subscription_data={
            "state": NavSubscription.CONFIG_NAME,
            "is_extend": subscription_data.is_extend,
            "is_change": subscription_data.is_change,
            "user_id": subscription_data.user_id,
            "devices": subscription_data.devices,
            "duration": subscription_data.duration,
            "price": subscription_data.price,
            "plan_id": subscription_data.plan_id,
            "volume_gb": subscription_data.volume_gb,
            "config_name": subscription_data.config_name,
            "subscription_id": subscription_data.subscription_id,
        },
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