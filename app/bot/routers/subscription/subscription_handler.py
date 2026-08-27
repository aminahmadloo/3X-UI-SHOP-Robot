import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import ClientData, ServicesContainer, SubscriptionData
from app.bot.payment_gateways import GatewayFactory
from app.bot.services.customer_level import get_discounted_plan_price
from app.bot.routers.subscription.keyboard import config_name_keyboard, devices_keyboard, duration_keyboard, managed_payment_method_keyboard, pay_keyboard, payment_method_keyboard, purchase_duration_keyboard, service_purchase_plan_keyboard, subscription_keyboard
from app.bot.utils.navigation import NavSubscription
from app.config import Config
from app.db.models import ConnectedDeviceSettings, ServicePurchasePlan, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


class PurchaseConfigState(StatesGroup):
    waiting_config_name = State()
    selecting_payment = State()


async def show_subscription(callback: CallbackQuery, client_data: ClientData | None, callback_data: SubscriptionData) -> None:
    if client_data:
        text = _("subscription:message:expired") if client_data.has_subscription_expired else _("subscription:message:active").format(devices=client_data.max_devices, expiry_time=client_data.expiry_time)
    else:
        text = _("subscription:message:not_active")
    await callback.message.edit_text(text=text, reply_markup=subscription_keyboard(has_subscription=client_data, callback_data=callback_data))


@router.callback_query(F.data == NavSubscription.BUY)
async def callback_subscription_buy(callback: CallbackQuery, user: User, session: AsyncSession, state: FSMContext) -> None:
    await state.clear()
    settings = await ConnectedDeviceSettings.get_or_create(session)
    data = SubscriptionData(state=NavSubscription.PLAN_ONE_MONTH, user_id=user.tg_id, devices=settings.max_connected_devices)
    await callback.answer()
    await callback.message.edit_text(
        "🛒 <b>خرید سرویس جدید</b>\n\n"
        "لطفاً دسته‌بندی مورد نظر را انتخاب کنید:",
        reply_markup=purchase_duration_keyboard(settings.max_connected_devices, data),
    )


@router.callback_query(SubscriptionData.filter(F.state.in_({NavSubscription.PLAN_ONE_MONTH, NavSubscription.PLAN_THREE_MONTH})))
async def callback_subscription_plan_category(callback: CallbackQuery, user: User, session: AsyncSession, callback_data: SubscriptionData) -> None:
    service_type = "one_month" if callback_data.state == NavSubscription.PLAN_ONE_MONTH else "three_month"
    plans = await ServicePurchasePlan.list_by_type(session, service_type)
    if not plans:
        await callback.answer("برای این نوع سرویس هنوز پلنی ثبت نشده است.", show_alert=True)
        return
    settings = await ConnectedDeviceSettings.get_or_create(session)
    callback_data.devices = settings.max_connected_devices
    callback_data.state = NavSubscription.PLAN
    await callback.answer()
    await callback.message.edit_text(
        "<b>انتخاب پلن</b>\n\n"
        "لطفاً پلن مورد نظر را انتخاب کنید:\n\n"
        "قیمت‌های ویژه برای اولین خرید شما",
        reply_markup=service_purchase_plan_keyboard(plans, callback_data),
    )


@router.callback_query(F.data.regexp(r"^subscription_back_plan:\d+$"))
async def callback_subscription_back_to_plan(callback: CallbackQuery, session: AsyncSession) -> None:
    plan = await ServicePurchasePlan.get(session, int(callback.data.rsplit(":", 1)[1]))
    if not plan:
        await callback.answer("این پلن دیگر وجود ندارد.", show_alert=True)
        return
    plans = await ServicePurchasePlan.list_by_type(session, plan.service_type)
    settings = await ConnectedDeviceSettings.get_or_create(session)
    data = SubscriptionData(state=NavSubscription.PLAN_ONE_MONTH if plan.service_type == "one_month" else NavSubscription.PLAN_THREE_MONTH, user_id=callback.from_user.id, devices=settings.max_connected_devices)
    await callback.answer()
    await callback.message.edit_text(
        "<b>انتخاب پلن</b>\n\n"
        "لطفاً پلن مورد نظر را انتخاب کنید:\n\n"
        "قیمت‌های ویژه برای اولین خرید شما",
        reply_markup=service_purchase_plan_keyboard(plans, data),
    )


def _build_auto_config_name(volume_gb: int, duration_days: int, tg_id: int, sub_number: int = 1) -> str:
    return f"{volume_gb}GB-{duration_days}D-tg{tg_id}-{sub_number}"


def _sanitize_config_name(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", name.strip())


@router.callback_query(F.data.regexp(r"^subscription_plan:\d+$"))
async def callback_subscription_plan_selected(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
) -> None:
    plan = await ServicePurchasePlan.get(session, int(callback.data.rsplit(":", 1)[1]))

    if not plan:
        await callback.answer("این پلن دیگر وجود ندارد.", show_alert=True)
        return

    auto_name = await services.vpn._generate_unique_config_name(
        volume_gb=plan.volume_gb,
        duration_days=plan.duration_days,
        tg_id=user.tg_id,
    )

    customer_level, purchase_count, discounted_price = await get_discounted_plan_price(
        session,
        user.tg_id,
        plan.price_toman,
    )

    discount_percent = int(getattr(customer_level, "discount_percent", 0) or 0)

    data = SubscriptionData(
        state=NavSubscription.CONFIG_NAME,
        user_id=user.tg_id,
        devices=(await ConnectedDeviceSettings.get_or_create(session)).max_connected_devices,
        duration=plan.duration_days,
        price=discounted_price,
        original_price=plan.price_toman,
        discount_percent=int(discount_percent or 0),
        discount_level_title=str(
            getattr(customer_level, "title", "")
            or getattr(customer_level, "name", "")
            or ""
        ),
        plan_id=plan.id,
        volume_gb=plan.volume_gb,
        config_name=auto_name,
    )

    await state.update_data(
        subscription_data={
            "state": NavSubscription.CONFIG_NAME.value,
            "is_extend": data.is_extend,
            "is_change": data.is_change,
            "user_id": data.user_id,
            "devices": data.devices,
            "duration": data.duration,
            "price": data.price,
            "original_price": data.original_price,
            "discount_percent": data.discount_percent,
            "discount_level_title": data.discount_level_title,
            "plan_id": data.plan_id,
            "volume_gb": data.volume_gb,
            "config_name": data.config_name,
        }
    )
    await state.set_state(PurchaseConfigState.waiting_config_name)

    await callback.answer()

    await callback.message.edit_text(
        "⚙️ <b>نام کانفیگ</b>\n\n"
        f"نام خودکار:\n<code>{auto_name}</code>\n\n"
        "یا نام دلخواه خود را وارد کنید <b>(فقط انگلیسی)</b>:\n\n"
        "نام انتخابی باید فقط شامل حروف انگلیسی، عدد، <code>_</code> یا <code>-</code> باشد.",
        reply_markup=config_name_keyboard(data),
    )


@router.callback_query(F.data == "subscription_config_name:auto")
async def callback_config_name_auto(
    callback: CallbackQuery,
    state: FSMContext,
    gateway_factory: GatewayFactory,
) -> None:
    data = await state.get_data()
    packed = data.get("subscription_data")

    if not packed:
        await callback.answer(
            "اطلاعات سفارش منقضی شده است. لطفاً دوباره پلن را انتخاب کنید.",
            show_alert=True,
        )
        return

    if not isinstance(packed, dict):
        await callback.answer(
            "اطلاعات سفارش نامعتبر است. لطفاً دوباره پلن را انتخاب کنید.",
            show_alert=True,
        )
        await state.clear()
        return

    callback_data = SubscriptionData(
        state=NavSubscription.CONFIG_NAME,
        is_extend=packed.get("is_extend", False),
        is_change=packed.get("is_change", False),
        user_id=packed.get("user_id", 0),
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

    if not callback_data.config_name:
        await callback.answer("نام خودکار موجود نیست.", show_alert=True)
        return

    await state.set_state(PurchaseConfigState.selecting_payment)
    await callback.answer()

    await callback.message.edit_text(
        "💳 <b>انتخاب روش پرداخت</b>\n\n"
        f"📝 نام کانفیگ: <code>{callback_data.config_name}</code>\n"
        f"💾 پلن: <b>{callback_data.volume_gb}GB | {callback_data.duration} روز</b>\n"
        f"💰 مبلغ پلن انتخابی: <b>{int(callback_data.original_price):,}".replace(",", ".") + " تومان</b>\n"
        f"🎁 تخفیف {callback_data.discount_level_title or 'سطح پایه'}: <b>{callback_data.discount_percent}%</b>\n"
        f"💳 مبلغ قابل پرداخت: <b>{int(callback_data.price):,}".replace(",", ".") + " تومان</b>\n\n"
        "روش پرداخت را انتخاب کنید:",
        reply_markup=managed_payment_method_keyboard(
            callback_data.plan_id,
            int(callback_data.price),
            gateway_factory.get_gateways(),
        ),
    )


@router.callback_query(F.data == "subscription_config_name:custom")
async def callback_config_name_custom(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    data = await state.get_data()

    if not data.get("subscription_data"):
        await callback.answer(
            "اطلاعات سفارش منقضی شده است. لطفاً دوباره پلن را انتخاب کنید.",
            show_alert=True,
        )
        await state.clear()
        return

    await state.set_state(PurchaseConfigState.waiting_config_name)
    await callback.answer()

    await callback.message.edit_text(
        "✏️ <b>نام دلخواه کانفیگ</b>\n\n"
        "لطفاً نام مورد نظر را ارسال کنید.\n\n"
        "فقط این کاراکترها مجاز هستند:\n"
        "<code>A-Z</code>، <code>a-z</code>، <code>0-9</code>، "
        "<code>_</code> و <code>-</code>"
    )


@router.message(PurchaseConfigState.waiting_config_name)
async def message_config_name(
    message: Message,
    user: User,
    state: FSMContext,
    gateway_factory: GatewayFactory,
) -> None:
    raw_name = (message.text or "").strip()

    if not re.fullmatch(r"[A-Za-z0-9_-]+", raw_name):
        await message.answer(
            "❌ نام واردشده معتبر نیست.\n\n"
            "لطفاً فقط از حروف انگلیسی، عدد، <code>_</code> و <code>-</code> استفاده کنید."
        )
        return

    data = await state.get_data()
    packed = data.get("subscription_data")

    if not packed:
        await message.answer(
            "اطلاعات سفارش منقضی شده است. لطفاً دوباره پلن را انتخاب کنید."
        )
        await state.clear()
        return

    if not isinstance(packed, dict):
        await message.answer(
            "اطلاعات سفارش نامعتبر است. لطفاً دوباره پلن را انتخاب کنید."
        )
        await state.clear()
        return

    callback_data = SubscriptionData(
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
        config_name="",
    )

    callback_data.config_name = (
        f"{callback_data.volume_gb}GB-"
        f"{callback_data.duration}D-"
        f"tg{user.tg_id}-"
        f"1-"
        f"{raw_name}"
    )

    await state.update_data(
        subscription_data={
            **packed,
            "config_name": callback_data.config_name,
        }
    )
    await state.set_state(PurchaseConfigState.selecting_payment)

    await message.answer(
        "💳 <b>انتخاب روش پرداخت</b>\n\n"
        f"📝 نام کانفیگ: <code>{callback_data.config_name}</code>\n"
        f"💾 پلن: <b>{callback_data.volume_gb}GB | {callback_data.duration} روز</b>\n"
        f"💰 مبلغ پلن انتخابی: <b>{int(callback_data.original_price):,}".replace(",", ".") + " تومان</b>\n"
        f"🎁 تخفیف {callback_data.discount_level_title or 'سطح پایه'}: <b>{callback_data.discount_percent}%</b>\n"
        f"💳 مبلغ قابل پرداخت: <b>{int(callback_data.price):,}".replace(",", ".") + " تومان</b>\n\n"
        "روش پرداخت را انتخاب کنید:",
        reply_markup=managed_payment_method_keyboard(
            callback_data.plan_id,
            int(callback_data.price),
            gateway_factory.get_gateways(),
        ),
    )


@router.callback_query(F.data.regexp(r"^mp:subscription:pay_[^:]+:\d+$"))
async def callback_managed_payment(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    gateway_factory: GatewayFactory,
    state: FSMContext,
) -> None:
    gateway_callback, plan_id_text = callback.data[3:].rsplit(":", 1)

    data = await state.get_data()
    packed = data.get("subscription_data")

    if not packed:
        await callback.answer(
            "اطلاعات سفارش منقضی شده است. لطفاً دوباره پلن را انتخاب کنید.",
            show_alert=True,
        )
        return

    if not isinstance(packed, dict):
        await callback.answer(
            "اطلاعات سفارش نامعتبر است. لطفاً دوباره پلن را انتخاب کنید.",
            show_alert=True,
        )
        await state.clear()
        return

    subscription_data = SubscriptionData(
        state=NavSubscription.CONFIG_NAME,
        is_extend=packed.get("is_extend", False),
        is_change=packed.get("is_change", False),
        user_id=packed.get("user_id", 0),
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
    subscription_data.subscription_id = packed.get("subscription_id", 0)

    if subscription_data.user_id != user.tg_id:
        await callback.answer("خطا در اطلاعات سفارش.", show_alert=True)
        return

    plan = await ServicePurchasePlan.get(
        session,
        int(plan_id_text),
    )

    if not plan:
        await callback.answer(
            "این پلن دیگر وجود ندارد.",
            show_alert=True,
        )
        return

    gateway = gateway_factory.get_gateway(gateway_callback)

    try:
        pay_url = await gateway.create_payment(subscription_data)

        await callback.answer()

        await callback.message.edit_text(
            "🧾 <b>سفارش شما</b>\n\n"
            f"📝 نام کانفیگ: <code>{subscription_data.config_name}</code>\n"
            f"📱 تعداد دستگاه: <b>{subscription_data.devices}</b>\n"
            f"💾 حجم: <b>{subscription_data.volume_gb} گیگ</b>\n"
            f"📅 مدت: <b>{subscription_data.duration} روز</b>\n"
            f"💰 مبلغ: <b>{subscription_data.price:,} تومان</b>",
            reply_markup=pay_keyboard(pay_url, subscription_data),
        )

    except Exception as exception:
        logger.exception(
            "Managed payment creation failed: %s",
            exception,
        )
        await callback.answer(
            "خطا در ایجاد پرداخت.",
            show_alert=True,
        )
        return

    finally:
        await state.set_state(PurchaseConfigState.selecting_payment)


@router.callback_query(F.data.regexp(r"^mp_back:\d+$"))
async def callback_managed_payment_back(
    callback: CallbackQuery,
    state: FSMContext,
    gateway_factory: GatewayFactory,
) -> None:
    data = await state.get_data()
    packed = data.get("subscription_data")

    if not isinstance(packed, dict):
        await callback.answer(
            "اطلاعات سفارش منقضی شده است. لطفاً دوباره پلن را انتخاب کنید.",
            show_alert=True,
        )
        await state.clear()
        return

    subscription_data = SubscriptionData(
        state=NavSubscription.CONFIG_NAME,
        is_extend=packed.get("is_extend", False),
        is_change=packed.get("is_change", False),
        user_id=packed.get("user_id", 0),
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
    subscription_data.subscription_id = packed.get("subscription_id", 0)

    if not subscription_data.plan_id:
        await callback.answer(
            "اطلاعات پلن سفارش نامعتبر است.",
            show_alert=True,
        )
        await state.clear()
        return

    await state.set_state(PurchaseConfigState.selecting_payment)
    await callback.answer()

    await callback.message.edit_text(
        "💳 <b>انتخاب روش پرداخت</b>\n\n"
        f"📝 نام کانفیگ: <code>{subscription_data.config_name}</code>\n"
        f"💾 پلن: <b>{subscription_data.volume_gb}GB | {subscription_data.duration} روز</b>\n"
        f"💰 مبلغ: <b>{subscription_data.price:,} تومان</b>\n\n"
        "روش پرداخت را انتخاب کنید:",
        reply_markup=managed_payment_method_keyboard(
            subscription_data.plan_id,
            int(subscription_data.price),
            gateway_factory.get_gateways(),
        ),
    )


@router.callback_query(F.data == NavSubscription.RENEW_SERVICE)
async def callback_subscription_renew_service(callback: CallbackQuery, user: User, state: FSMContext, services: ServicesContainer) -> None:
    await state.clear()
    client_data = await services.vpn.get_client_data(user) if user.server_id else None
    await show_subscription(callback, client_data, SubscriptionData(state=NavSubscription.PROCESS, user_id=user.tg_id))


@router.callback_query(F.data == NavSubscription.MAIN)
async def callback_subscription(callback: CallbackQuery, user: User, state: FSMContext, services: ServicesContainer) -> None:
    await state.clear()
    client_data = await services.vpn.get_client_data(user) if user.server_id else None
    await show_subscription(callback, client_data, SubscriptionData(state=NavSubscription.PROCESS, user_id=user.tg_id))


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.EXTEND))
async def callback_subscription_extend(callback: CallbackQuery, user: User, callback_data: SubscriptionData, config: Config, services: ServicesContainer) -> None:
    client = await services.vpn.is_client_exists(user)
    current_devices = await services.vpn.get_limit_ip(user=user, client=client)
    if not services.plan.get_plan(current_devices):
        await services.notification.show_popup(callback=callback, text=_("subscription:popup:error_fetching_plan"))
        return
    callback_data.devices = current_devices
    callback_data.state = NavSubscription.DURATION
    callback_data.is_extend = True
    await callback.message.edit_text(text=_("subscription:message:duration"), reply_markup=duration_keyboard(services.plan, callback_data, config.shop.CURRENCY))


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.CHANGE))
async def callback_subscription_change(callback: CallbackQuery, user: User, callback_data: SubscriptionData, services: ServicesContainer) -> None:
    callback_data.state = NavSubscription.DEVICES
    callback_data.is_change = True
    await callback.message.edit_text(text=_("subscription:message:devices"), reply_markup=devices_keyboard(services.plan.get_all_plans(), callback_data))


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.PROCESS))
async def callback_subscription_process(callback: CallbackQuery, user: User, session: AsyncSession, callback_data: SubscriptionData, services: ServicesContainer) -> None:
    if not await services.server_pool.get_available_server():
        await services.notification.show_popup(callback=callback, text=_("subscription:popup:no_available_servers"), cache_time=120)
        return
    callback_data.state = NavSubscription.DEVICES
    await callback.message.edit_text(text=_("subscription:message:devices"), reply_markup=devices_keyboard(services.plan.get_all_plans(), callback_data))


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.DEVICES))
async def callback_devices_selected(callback: CallbackQuery, user: User, callback_data: SubscriptionData, config: Config, services: ServicesContainer) -> None:
    callback_data.state = NavSubscription.DURATION
    await callback.message.edit_text(text=_("subscription:message:duration"), reply_markup=duration_keyboard(services.plan, callback_data, config.shop.CURRENCY))


@router.callback_query(SubscriptionData.filter(F.state == NavSubscription.DURATION))
async def callback_duration_selected(callback: CallbackQuery, user: User, callback_data: SubscriptionData, services: ServicesContainer, gateway_factory: GatewayFactory) -> None:
    callback_data.state = NavSubscription.PAY
    await callback.message.edit_text(text=_("subscription:message:payment_method"), reply_markup=payment_method_keyboard(services.plan.get_plan(callback_data.devices), callback_data, gateway_factory.get_gateways()))
