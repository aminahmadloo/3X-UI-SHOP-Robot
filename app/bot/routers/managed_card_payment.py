from aiogram import F, Router
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.routers.custom_service_card_payment import (
    CustomServiceCardPaymentState,
    custom_service_payment_card,
)
from app.bot.routers.subscription.keyboard import (
    managed_payment_method_keyboard,
    managed_payment_method_keyboard_renewal,
)
from app.bot.routers.wallet.handler import card_text
from app.bot.utils.navigation import NavSubscription
from app.config import Config
from app.db.models import CardSettings, User

router = Router(name=__name__)

MANAGED_CARD_SUBSCRIPTION_KEY = "managed_card_subscription"


def _managed_card_keyboard(card_number: str, amount: int, card_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 کپی شماره کارت", copy_text=CopyTextButton(text=card_number))],
            [InlineKeyboardButton(text="📋 کپی مبلغ", copy_text=CopyTextButton(text=str(amount)))],
            [InlineKeyboardButton(text="🔄 تعویض کارت", callback_data=f"managed_card:swap:{card_id}", style="success")],
            [InlineKeyboardButton(text="✅ پرداخت کردم", callback_data="managed_card:paid")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="managed_card:back")],
        ]
    )


def _deserialize_managed_card(data: dict, user_tg_id: int) -> SubscriptionData | None:
    stored = data.get(MANAGED_CARD_SUBSCRIPTION_KEY)
    if not stored:
        return None
    try:
        subscription_data = SubscriptionData.deserialize(stored)
    except Exception:
        return None
    if (
        subscription_data.user_id != user_tg_id
        or subscription_data.price <= 0
        or subscription_data.plan_id <= 0
        or not subscription_data.config_name
    ):
        return None
    return subscription_data


async def _render_managed_card(
    callback: CallbackQuery,
    user: User,
    card: CardSettings,
    subscription_data: SubscriptionData,
    state: FSMContext,
) -> None:
    serialized = subscription_data.serialize()
    await state.set_state(CustomServiceCardPaymentState.waiting_receipt)
    await state.update_data(
        subscription_data=serialized,
        custom_service_subscription=serialized,
        custom_service_total=int(subscription_data.price),
        card_payment_card_id=card.id,
        **{MANAGED_CARD_SUBSCRIPTION_KEY: serialized},
    )
    await callback.answer()
    text = card_text(user.language_code, card, int(subscription_data.price))
    if card.bank_name:
        text += f"\n🏦 بانک: <b>{card.bank_name}</b>"
    await callback.message.edit_text(
        text,
        reply_markup=_managed_card_keyboard(
            card.card_number,
            int(subscription_data.price),
            card.id,
        ),
    )


@router.callback_query(F.data.regexp(r"^mp_card:\d+$"))
async def managed_card_payment(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    config: Config,
) -> None:
    plan_id = int((callback.data or "").rsplit(":", 1)[1])
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
            original_price=packed.get("original_price", 0),
            discount_percent=packed.get("discount_percent", 0),
            discount_level_title=packed.get("discount_level_title", ""),
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

    card = await CardSettings.get_or_create(session, card_number=config.shop.CARD_NUMBER or "")
    if not card.is_active or not card.card_number or not card.card_holder_name:
        await callback.answer("❌ پرداخت کارت به کارت در حال حاضر فعال نیست.", show_alert=True)
        return

    await _render_managed_card(callback, user, card, subscription_data, state)


@router.callback_query(F.data.regexp(r"^managed_card:swap:\d+$"))
async def managed_card_swap(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> object:
    data = await state.get_data()
    subscription_data = _deserialize_managed_card(data, user.tg_id)
    if subscription_data is None:
        return UNHANDLED

    current_id = int((callback.data or "").rsplit(":", 1)[1])
    cards = await CardSettings.get_active_cards(session)
    if not cards:
        await callback.answer("❌ هیچ کارت فعالی برای انتخاب وجود ندارد.", show_alert=True)
        return None

    next_card = None
    for index, card in enumerate(cards):
        if card.id == current_id:
            next_card = cards[(index + 1) % len(cards)]
            break
    next_card = next_card or cards[0]

    await _render_managed_card(callback, user, next_card, subscription_data, state)
    return None


@router.callback_query(F.data == "managed_card:paid")
async def managed_card_payment_paid(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    subscription_data = _deserialize_managed_card(data, user.tg_id)
    if subscription_data is None:
        await state.clear()
        await callback.answer("❌ درخواست پرداخت منقضی شده است.", show_alert=True)
        return

    serialized = subscription_data.serialize()
    await state.set_state(CustomServiceCardPaymentState.waiting_receipt)
    await state.update_data(
        custom_service_subscription=serialized,
        custom_service_total=int(subscription_data.price),
        **{MANAGED_CARD_SUBSCRIPTION_KEY: serialized},
    )
    await callback.answer()
    await callback.message.edit_text(
        f"📷 <b>ارسال رسید پرداخت سرویس</b>\n\n"
        f"مبلغ: <b>{int(subscription_data.price):,} تومان</b>\n\n"
        "لطفاً عکس واضح رسید واریز را همینجا ارسال کنید.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 انصراف", callback_data="managed_card:back")]]
        ),
    )


@router.callback_query(F.data == "managed_card:back")
async def managed_card_payment_back(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    gateway_factory,
) -> None:
    data = await state.get_data()
    subscription_data = _deserialize_managed_card(data, user.tg_id)
    if subscription_data is None:
        await state.clear()
        await callback.answer("❌ اطلاعات سفارش نامعتبر یا منقضی شده است.", show_alert=True)
        return

    await callback.answer()
    if subscription_data.is_extend:
        await callback.message.edit_text(
            "💳 <b>انتخاب روش پرداخت تمدید سرویس</b>\n\n"
            f"📦 <b>سرویس:</b> <code>{subscription_data.config_name}</code>\n"
            f"💾 <b>حجم:</b> {subscription_data.volume_gb} GB\n"
            f"📅 <b>مدت:</b> {subscription_data.duration} روز\n"
            f"💰 <b>مبلغ:</b> {subscription_data.price:,} تومان\n\n"
            "روش پرداخت را انتخاب کنید:",
            reply_markup=managed_payment_method_keyboard_renewal(
                subscription_data.plan_id,
                int(subscription_data.price),
                gateway_factory.get_gateways(),
            ),
        )
        return

    await callback.message.edit_text(
        "💳 <b>انتخاب روش پرداخت</b>\n\n"
        f"📝 نام کانفیگ: <code>{subscription_data.config_name}</code>\n"
        f"💾 پلن: <b>{subscription_data.volume_gb}GB | {subscription_data.duration} روز</b>\n"
        f"💰 مبلغ قابل پرداخت: <b>{subscription_data.price:,} تومان</b>\n\n"
        "روش پرداخت را انتخاب کنید:",
        reply_markup=managed_payment_method_keyboard(
            subscription_data.plan_id,
            int(subscription_data.price),
            gateway_factory.get_gateways(),
        ),
    )
