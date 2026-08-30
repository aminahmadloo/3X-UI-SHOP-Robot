from aiogram import F, Router
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
from app.bot.utils.navigation import NavSubscription
from app.config import Config
from app.db.models import CardSettings, User

router = Router(name=__name__)


MANAGED_CARD_SUBSCRIPTION_KEY = "managed_card_subscription"


def _managed_card_keyboard(card_number: str, amount: int) -> InlineKeyboardMarkup:
    """Card-payment keyboard used by regular purchase/renewal flows.

    Managed purchase/renewal deliberately uses its own callback namespace so
    that the Back/Paid actions cannot be confused with the generic custom
    service card-payment flow. The generic flow is still reused for rendering
    and receipt processing, but its navigation state is never authoritative
    for this managed screen.
    """
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 کپی شماره کارت", copy_text=CopyTextButton(text=card_number))],
            [InlineKeyboardButton(text="📋 کپی مبلغ", copy_text=CopyTextButton(text=str(amount)))],
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

    serialized = subscription_data.serialize()
    await state.update_data(
        subscription_data=serialized,
        custom_service_subscription=serialized,
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
        MANAGED_CARD_SUBSCRIPTION_KEY=serialized,
    )

    await custom_service_payment_card(
        callback=callback,
        user=user,
        session=session,
        state=state,
        config=config,
    )

    # custom_service_payment_card renders the common card-payment screen.
    # Replace only its navigation with managed callbacks for this exact order.
    settings = await CardSettings.get_or_create(
        session,
        card_number=config.shop.CARD_NUMBER or "",
    )
    if settings.is_active and settings.card_number and settings.card_holder_name and callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=_managed_card_keyboard(
                settings.card_number,
                int(subscription_data.price),
            )
        )


@router.callback_query(F.data == "managed_card:paid")
async def managed_card_payment_paid(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    """Move managed card payment to receipt upload without losing order state."""
    data = await state.get_data()
    subscription_data = _deserialize_managed_card(data, user.tg_id)
    if subscription_data is None:
        await state.clear()
        await callback.answer("❌ درخواست پرداخت منقضی شده است.", show_alert=True)
        return

    await state.set_state(CustomServiceCardPaymentState.waiting_receipt)
    await state.update_data(
        custom_service_subscription=subscription_data.serialize(),
        custom_service_total=int(subscription_data.price),
        MANAGED_CARD_SUBSCRIPTION_KEY=subscription_data.serialize(),
    )
    await callback.answer()
    await callback.message.edit_text(
        f"📷 <b>ارسال رسید پرداخت سرویس</b>\n\n"
        f"مبلغ: <b>{int(subscription_data.price):,} تومان</b>\n\n"
        "لطفاً عکس واضح رسید واریز را همینجا ارسال کنید.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 انصراف", callback_data="custom_service:back")]
            ]
        ),
    )


@router.callback_query(F.data == "managed_card:back")
async def managed_card_payment_back(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    gateway_factory,
) -> None:
    """Return to the payment-method screen using the managed order snapshot."""
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
