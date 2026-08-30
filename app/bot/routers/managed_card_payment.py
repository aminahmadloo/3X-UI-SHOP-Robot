from aiogram import F, Router
from aiogram.dispatcher.event.bases import UNHANDLED
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.routers.custom_service_card_payment import CustomServiceCardPaymentState
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


def _subscription_dict(subscription_data: SubscriptionData) -> dict:
    return {
        "state": NavSubscription.CONFIG_NAME,
        "is_extend": subscription_data.is_extend,
        "is_change": subscription_data.is_change,
        "user_id": subscription_data.user_id,
        "devices": subscription_data.devices,
        "duration": subscription_data.duration,
        "price": subscription_data.price,
        "original_price": subscription_data.original_price,
        "discount_percent": subscription_data.discount_percent,
        "discount_level_title": subscription_data.discount_level_title,
        "plan_id": subscription_data.plan_id,
        "volume_gb": subscription_data.volume_gb,
        "config_name": subscription_data.config_name,
        "subscription_id": subscription_data.subscription_id,
    }


def _deserialize_value(value, user_tg_id: int) -> SubscriptionData | None:
    if not value:
        return None
    try:
        if isinstance(value, str):
            subscription_data = SubscriptionData.deserialize(value)
        elif isinstance(value, dict):
            subscription_data = SubscriptionData(
                state=NavSubscription.CONFIG_NAME,
                is_extend=value.get("is_extend", False),
                is_change=value.get("is_change", False),
                user_id=value.get("user_id", user_tg_id),
                devices=value.get("devices", 0),
                duration=value.get("duration", 0),
                price=value.get("price", 0),
                original_price=value.get("original_price", 0),
                discount_percent=value.get("discount_percent", 0),
                discount_level_title=value.get("discount_level_title", ""),
                plan_id=value.get("plan_id", 0),
                volume_gb=value.get("volume_gb", 0),
                config_name=value.get("config_name", ""),
            )
            subscription_data.subscription_id = int(value.get("subscription_id", 0) or 0)
        else:
            return None
    except (TypeError, ValueError, AttributeError):
        return None

    if (
        subscription_data.user_id != user_tg_id
        or subscription_data.price <= 0
        or subscription_data.plan_id <= 0
        or not subscription_data.config_name
    ):
        return None
    return subscription_data


def _managed_card_keyboard(card_number: str, amount: int, card_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📋 کپی شماره کارت",
                    copy_text=CopyTextButton(text=card_number),
                ),
                InlineKeyboardButton(
                    text="📋 کپی مبلغ",
                    copy_text=CopyTextButton(text=str(amount)),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔄 تعویض کارت",
                    callback_data=f"managed_card:swap:{card_id}",
                    style="success",
                )
            ],
            [InlineKeyboardButton(text="✅ پرداخت کردم - رسید می‌فرستم", callback_data="managed_card:paid")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data="managed_card:back")],
        ]
    )


def _deserialize_managed_card(data: dict, user_tg_id: int) -> SubscriptionData | None:
    # Prefer the dedicated managed snapshot. Fall back to the canonical
    # purchase context so a payment-method round trip cannot lose the order.
    for key in (
        MANAGED_CARD_SUBSCRIPTION_KEY,
        "subscription_data",
        "custom_service_subscription",
    ):
        subscription_data = _deserialize_value(data.get(key), user_tg_id)
        if subscription_data is not None:
            return subscription_data
    return None


async def _render_managed_card(
    callback: CallbackQuery,
    user: User,
    card: CardSettings,
    subscription_data: SubscriptionData,
    state: FSMContext,
    *,
    show_swap_notice: bool = False,
) -> None:
    serialized = subscription_data.serialize()
    canonical = _subscription_dict(subscription_data)
    await state.set_state(CustomServiceCardPaymentState.waiting_receipt)
    await state.update_data(
        # Keep the canonical purchase context as a dict. This is the format
        # consumed by the managed payment-method callback after pressing Back.
        subscription_data=canonical,
        custom_service_subscription=serialized,
        custom_service_total=int(subscription_data.price),
        card_payment_card_id=card.id,
        **{MANAGED_CARD_SUBSCRIPTION_KEY: serialized},
    )

    if show_swap_notice:
        # CallbackQuery.answer() does not accept/interpret a parse mode for
        # the alert text. Keep this popup plain text so HTML tags such as
        # <b> and <code> are not shown literally to the customer.
        notice = (
            "🔄 کارت عوض شد\n\n"
            f"💳 شماره کارت جدید:\n{card.card_number}\n\n"
            f"🏦 بانک: {card.bank_name or 'نامشخص'}\n"
            f"👤 بنام: {card.card_holder_name}\n\n"
            f"💰 مبلغ را به این کارت واریز کنید: {int(subscription_data.price):,} تومان"
        )
        await callback.answer(notice, show_alert=True)
    else:
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

    # The context can be a canonical dict or a serialized SubscriptionData,
    # depending on which payment screen the user returned from.
    subscription_data = _deserialize_value(packed, user.tg_id)
    if subscription_data is None:
        subscription_data = _deserialize_managed_card(data, user.tg_id)

    if subscription_data is None:
        await state.clear()
        await callback.answer("❌ اطلاعات سفارش منقضی شده است. لطفاً دوباره پلن را انتخاب کنید.", show_alert=True)
        return

    if subscription_data.plan_id != plan_id:
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

    await _render_managed_card(
        callback,
        user,
        next_card,
        subscription_data,
        state,
        show_swap_notice=True,
    )
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

    # Returning to payment-method selection must preserve the canonical order
    # snapshot and must not leave a serialized value in subscription_data.
    await state.update_data(
        subscription_data=_subscription_dict(subscription_data),
        custom_service_subscription=subscription_data.serialize(),
        custom_service_total=int(subscription_data.price),
        **{MANAGED_CARD_SUBSCRIPTION_KEY: subscription_data.serialize()},
    )

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
