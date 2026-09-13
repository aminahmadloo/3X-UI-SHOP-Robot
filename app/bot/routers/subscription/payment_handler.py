import json
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery
from aiogram.utils.i18n import gettext as _
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import ServicesContainer, SubscriptionData
from app.bot.payment_gateways import GatewayFactory
from app.bot.payment_gateways.variza_gateway import VarizaGateway
from app.bot.routers.variza_payment_handler import gateway_choice_markup, gateway_choice_text
from app.bot.utils.formatting import format_subscription_period
from app.bot.utils.navigation import NavSubscription
from app.db.models import ServicePurchasePlan, User

from .keyboard import pay_keyboard

logger = logging.getLogger(__name__)
router = Router(name=__name__)


class PaymentState(StatesGroup):
    processing = State()


def _hydrate_from_fsm(callback_data: SubscriptionData, payload: object) -> SubscriptionData:
    if isinstance(payload, str):
        try:
            stored = SubscriptionData.deserialize(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            return callback_data
    elif isinstance(payload, dict):
        try:
            stored = SubscriptionData.deserialize(json.dumps(payload, ensure_ascii=False))
        except (TypeError, ValueError, json.JSONDecodeError):
            return callback_data
    else:
        return callback_data

    for field in ("user_id", "original_price", "base_plan_price", "special_offer", "discount_percent", "discount_level_title", "config_name", "payment_kind", "subscription_id"):
        setattr(callback_data, field, getattr(stored, field))
    if not callback_data.price:
        callback_data.price = stored.price
    if not callback_data.plan_id:
        callback_data.plan_id = stored.plan_id
    if not callback_data.volume_gb:
        callback_data.volume_gb = stored.volume_gb
    if not callback_data.devices:
        callback_data.devices = stored.devices
    if not callback_data.duration:
        callback_data.duration = stored.duration
    return callback_data


@router.callback_query(SubscriptionData.filter(F.state.startswith(NavSubscription.PAY)))
async def callback_payment_method_selected(
    callback: CallbackQuery,
    user: User,
    callback_data: SubscriptionData,
    services: ServicesContainer,
    gateway_factory: GatewayFactory,
    state: FSMContext,
    session: AsyncSession,
) -> None:
    if await state.get_state() == PaymentState.processing:
        logger.debug("User %s is already processing payment.", user.tg_id)
        return

    state_data = await state.get_data()
    callback_data = _hydrate_from_fsm(callback_data, state_data.get("subscription_data"))
    callback_data.user_id = callback_data.user_id or user.tg_id
    await state.set_state(PaymentState.processing)

    try:
        method = callback_data.state
        devices = callback_data.devices
        duration = callback_data.duration
        volume_gb = callback_data.volume_gb
        logger.info("User %s selected payment method: %s", user.tg_id, method)
        logger.info("User %s selected %s devices, %s days and %s GB.", user.tg_id, devices, duration, volume_gb)

        gateway = gateway_factory.get_gateway(method)
        if callback_data.plan_id:
            price = callback_data.price
        else:
            plan = services.plan.get_plan(devices)
            if plan is None:
                raise RuntimeError(f"Plan for {devices} devices was not found")
            price = plan.get_price(currency=gateway.currency, duration=duration)
            callback_data.price = price

        pay_url = await gateway.create_payment(callback_data)

        if method == "pay_aban":
            invoice_id = pay_url.rstrip("/").rsplit("/", 1)[-1]
            invoice = await gateway._get_invoice(invoice_id)  # type: ignore[attr-defined]
            order_id = str(invoice.get("order_id") or "").strip()
            payable_toman = invoice.get("payable_toman")
            if not invoice_id or not order_id or payable_toman is None:
                raise RuntimeError("AbanGateway returned incomplete invoice details")

            if VarizaGateway.is_available():
                await callback.message.edit_text(gateway_choice_text(callback_data, payable_toman), reply_markup=gateway_choice_markup(invoice_id, callback_data.plan_id))
                return

            if callback_data.is_extend:
                renewal_plan = await ServicePurchasePlan.get(session, callback_data.plan_id) if callback_data.plan_id else None
                added_volume = renewal_plan.volume_gb if renewal_plan is not None and renewal_plan.volume_gb > 0 else callback_data.volume_gb
                added_duration = renewal_plan.duration_days if renewal_plan is not None and renewal_plan.duration_days > 0 else duration
                text = ("💳 <b>فاکتور کارت به کارت هوشمند آبان گیت</b>\n━━━━━━━━━━━━━━━\n"
                        f"کد پیگیری: <code>{order_id}</code>\nشماره فاکتور آبان گیت: <code>{invoice_id}</code>\n"
                        f"نام کانفیگ: <code>{callback_data.config_name}</code>\nحجم افزوده: <code>{added_volume} گیگ</code>\n"
                        f"زمان افزوده: <code>{added_duration} روز</code>\nمبلغ سفارش: <code>{price:,.0f}</code> تومان\n"
                        f"مبلغ قابل پرداخت: <code>{float(payable_toman):,.0f}</code> تومان\nمهلت پرداخت: <b>طبق زمان اعلام‌شده در صفحه آبان گیت</b>\n━━━━━━━━━━━━━━━\n\n"
                        "برای پرداخت، روی دکمه <b>«💳 پرداخت»</b> بزنید.\nپس از تأیید آبان گیت، تمدید سرویس به‌صورت خودکار انجام می‌شود.")
            else:
                text = ("💳 <b>فاکتور کارت به کارت هوشمند آبان گیت</b>\n━━━━━━━━━━━━━━━\n"
                        f"کد پیگیری: <code>{order_id}</code>\nشماره فاکتور آبان گیت: <code>{invoice_id}</code>\n"
                        f"نام کانفیگ: <code>{callback_data.config_name}</code>\nحجم: <code>{callback_data.volume_gb} گیگ</code>\nمدت: <code>{callback_data.duration} روز</code>\n"
                        f"مبلغ سفارش: <code>{price:,.0f}</code> تومان\nمبلغ قابل پرداخت: <code>{float(payable_toman):,.0f}</code> تومان\n"
                        "مهلت پرداخت: <b>طبق زمان اعلام‌شده در صفحه آبان گیت</b>\n━━━━━━━━━━━━━━━\n\n"
                        "برای پرداخت، روی دکمه <b>«💳 پرداخت»</b> بزنید.\nپس از تأیید آبان گیت، شارژ یا سفارش شما به‌صورت خودکار انجام می‌شود.")
        elif callback_data.is_extend:
            text = ("🏦 <b>پرداخت تمدید سرویس</b>\n\n"
                    f"📦 <b>حجم افزوده:</b> {volume_gb} GB\n📅 <b>زمان افزوده:</b> {duration} روز\n"
                    f"💰 <b>مبلغ:</b> {price:,.0f} تومان\n\nبرای تکمیل پرداخت، روی دکمه <b>«💳 پرداخت»</b> بزنید.")
        elif callback_data.is_change:
            text = _("payment:message:order_change")
        else:
            text = _("payment:message:order")

        await callback.message.edit_text(text=text.format(devices=devices, duration=format_subscription_period(duration), volume=volume_gb, price=price, currency=gateway.currency.symbol), reply_markup=pay_keyboard(pay_url=pay_url, callback_data=callback_data))
    except Exception as exception:
        logger.exception("Error processing payment for user %s: %s", user.tg_id, exception)
        await services.notification.show_popup(callback=callback, text=_("payment:popup:error"))
    finally:
        await state.set_state(None)
