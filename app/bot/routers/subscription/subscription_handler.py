import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import ClientData, ServicesContainer, SubscriptionData
from app.bot.payment_gateways import GatewayFactory
from app.bot.routers.subscription.keyboard import (
    devices_keyboard,
    duration_keyboard,
    payment_method_keyboard,
    purchase_duration_keyboard,
    service_purchase_plan_keyboard,
    subscription_keyboard,
)
from app.bot.utils.navigation import NavSubscription
from app.config import Config
from app.db.models import ConnectedDeviceSettings, ServicePurchasePlan, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


async def show_subscription(
    callback: CallbackQuery,
    client_data: ClientData | None,
    callback_data: SubscriptionData,
) -> None:
    if client_data:
        if client_data.has_subscription_expired:
            text = _("subscription:message:expired")
        else:
            text = _("subscription:message:active").format(
                devices=client_data.max_devices,
                expiry_time=client_data.expiry_time,
            )
    else:
        text = _("subscription:message:not_active")

    await callback.message.edit_text(
        text=text,
        reply_markup=subscription_keyboard(
            has_subscription=client_data,
            callback_data=callback_data,
        ),
    )


@router.callback_query(F.data == NavSubscription.BUY)
async def callback_subscription_buy(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    """Start the admin-managed service purchase flow."""
    logger.info(f"User {user.tg_id} started a new service purchase.")

    await state.clear()

    settings = await ConnectedDeviceSettings.get_or_create(session)
    callback_data = SubscriptionData(
        state=NavSubscription.PLAN_ONE_MONTH,
        user_id=user.tg_id,
        devices=settings.max_connected_devices,
    )

    await callback.answer()
    await callback.message.edit_text(
        "🛒 <b>انتخاب نوع سرویس</b>\n\n"
        f"👥 تعداد دستگاه: <b>{settings.max_connected_devices}</b>\n\n"
        "نوع سرویس را انتخاب کنید:",
        reply_markup=purchase_duration_keyboard(
            devices=settings.max_connected_devices,
            callback_data=callback_data,
        ),
    )


@router.callback_query(
    SubscriptionData.filter(
        F.state.in_({NavSubscription.PLAN_ONE_MONTH, NavSubscription.PLAN_THREE_MONTH})
    )
)
async def callback_subscription_plan_category(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    callback_data: SubscriptionData,
) -> None:
    service_type = (
        "one_month"
        if callback_data.state == NavSubscription.PLAN_ONE_MONTH
        else "three_month"
    )

    plans = await ServicePurchasePlan.list_by_type(session, service_type)
    if not plans:
        await callback.answer(
            "برای این نوع سرویس هنوز پلنی ثبت نشده است.",
            show_alert=True,
        )
        return

    settings = await ConnectedDeviceSettings.get_or_create(session)
    callback_data.devices = settings.max_connected_devices
    callback_data.state = NavSubscription.PLAN

    title = (
        "📅 <b>سرویس‌های یک ماهه</b>"
        if service_type == "one_month"
        else "📅 <b>سرویس‌های سه ماهه</b>"
    )

    await callback.answer()
    await callback.message.edit_text(
        f"{title}\n\n"
        f"👥 تعداد دستگاه: <b>{settings.max_connected_devices}</b>\n"
        "یکی از پلن‌های زیر را انتخاب کنید:",
        reply_markup=service_purchase_plan_keyboard(
            plans,
            callback_data,
        ),
    )


@router.callback_query(F.data.regexp(r"^subscription_plan:\d+$"))
async def callback_subscription_plan_selected(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    gateway_factory: GatewayFactory,
) -> None:
    try:
        plan_id = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, IndexError):
        await callback.answer("شناسه پلن نامعتبر است.", show_alert=True)
        return

    plan = await ServicePurchasePlan.get(session, plan_id)
    if not plan:
        await callback.answer("این پلن دیگر وجود ندارد.", show_alert=True)
        return

    settings = await ConnectedDeviceSettings.get_or_create(session)

    callback_data = SubscriptionData(
        state=NavSubscription.PAY,
        user_id=user.tg_id,
        devices=settings.max_connected_devices,
        duration=plan.duration_days,
        price=plan.price_toman,
        plan_id=plan.id,
        volume_gb=plan.volume_gb,
    )

    logger.info(
        "User %s selected managed plan %s | devices=%s duration=%s volume=%sGB price=%s",
        user.tg_id,
        plan.id,
        callback_data.devices,
        callback_data.duration,
        callback_data.volume_gb,
        callback_data.price,
    )

    await callback.answer()
    await callback.message.edit_text(
        "💳 <b>انتخاب روش پرداخت</b>\n\n"
        f"📱 تعداد دستگاه: <b>{callback_data.devices}</b>\n"
        f"💾 حجم: <b>{callback_data.volume_gb} گیگ</b>\n"
        f"📅 مدت: <b>{callback_data.duration} روز</b>\n"
        f"💰 مبلغ: <b>{callback_data.price:,} تومان</b>",
        reply_markup=payment_method_keyboard(
            plan=None,
            callback_data=callback_data,
            gateways=gateway_factory.get_gateways(),
            price_override=callback_data.price,
        ),
    )


@router.callback_query(F.data == NavSubscription.RENEW_SERVICE)
async def callback_subscription_renew_service(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    """Open the existing subscription page for renewal/change actions."""
    logger.info(f"User {user.tg_id} opened renew service page.")

    await state.set_state(None)
    client_data = None

    if user.server_id:
        client_data = await services.vpn.get_client_data(user)
        if not client_data:
            logger.warning(
                f"No active 3X-UI client data for user {user.tg_id}; "
                "showing subscription page as inactive."
            )

    callback_data = SubscriptionData(
        state=NavSubscription.PROCESS,
        user_id=user.tg_id,
    )

    await show_subscription(
        callback=callback,
        client_data=client_data,
        callback_data=callback_data,
    )


@router.callback_query(F.data == NavSubscription.MAIN)
async def callback_subscription(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    logger.info(f"User {user.tg_id} opened subscription page.")
    await state.set_state(None)

    client_data = None
    if user.server_id:
        client_data = await services.vpn.get_client_data(user)
        if not client_data:
            logger.warning(
                f"No active 3X-UI client data for user {user.tg_id}; "
                "showing subscription page as inactive."
            )

    callback_data = SubscriptionData(state=NavSubscription.PROCESS, user_id=user.tg_id)
    await show_subscription(
        callback=callback,
        client_data=client_data,
        callback_data=callback_data,
    )


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.EXTEND))
async def callback_subscription_extend(
    callback: CallbackQuery,
    user: User,
    callback_data: SubscriptionData,
    config: Config,
    services: ServicesContainer,
) -> None:
    logger.info(f"User {user.tg_id} started extend subscription.")
    client = await services.vpn.is_client_exists(user)

    current_devices = await services.vpn.get_limit_ip(user=user, client=client)
    if not services.plan.get_plan(current_devices):
        await services.notification.show_popup(
            callback=callback,
            text=_("subscription:popup:error_fetching_plan"),
        )
        return

    callback_data.devices = current_devices
    callback_data.state = NavSubscription.DURATION
    callback_data.is_extend = True
    await callback.message.edit_text(
        text=_("subscription:message:duration"),
        reply_markup=duration_keyboard(
            plan_service=services.plan,
            callback_data=callback_data,
            currency=config.shop.CURRENCY,
        ),
    )


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.CHANGE))
async def callback_subscription_change(
    callback: CallbackQuery,
    user: User,
    callback_data: SubscriptionData,
    services: ServicesContainer,
) -> None:
    logger.info(f"User {user.tg_id} started change subscription.")
    callback_data.state = NavSubscription.DEVICES
    callback_data.is_change = True
    await callback.message.edit_text(
        text=_("subscription:message:devices"),
        reply_markup=devices_keyboard(services.plan.get_all_plans(), callback_data),
    )


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.PROCESS))
async def callback_subscription_process(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    callback_data: SubscriptionData,
    services: ServicesContainer,
) -> None:
    logger.info(f"User {user.tg_id} started subscription process.")
    server = await services.server_pool.get_available_server()

    if not server:
        await services.notification.show_popup(
            callback=callback,
            text=_("subscription:popup:no_available_servers"),
            cache_time=120,
        )
        return

    callback_data.state = NavSubscription.DEVICES
    await callback.message.edit_text(
        text=_("subscription:message:devices"),
        reply_markup=devices_keyboard(services.plan.get_all_plans(), callback_data),
    )


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.DEVICES))
async def callback_devices_selected(
    callback: CallbackQuery,
    user: User,
    callback_data: SubscriptionData,
    config: Config,
    services: ServicesContainer,
) -> None:
    logger.info(f"User {user.tg_id} selected devices: {callback_data.devices}")
    callback_data.state = NavSubscription.DURATION
    await callback.message.edit_text(
        text=_("subscription:message:duration"),
        reply_markup=duration_keyboard(
            plan_service=services.plan,
            callback_data=callback_data,
            currency=config.shop.CURRENCY,
        ),
    )


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.DURATION))
async def callback_duration_selected(
    callback: CallbackQuery,
    user: User,
    callback_data: SubscriptionData,
    services: ServicesContainer,
    gateway_factory: GatewayFactory,
) -> None:
    logger.info(f"User {user.tg_id} selected duration: {callback_data.duration}")
    callback_data.state = NavSubscription.PAY
    await callback.message.edit_text(
        text=_("subscription:message:payment_method"),
        reply_markup=payment_method_keyboard(
            plan=services.plan.get_plan(callback_data.devices),
            callback_data=callback_data,
            gateways=gateway_factory.get_gateways(),
        ),
    )
