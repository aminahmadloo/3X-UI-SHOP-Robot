import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery
from aiogram.utils.i18n import gettext as _

from app.bot.models import ServicesContainer, SubscriptionData
from app.bot.payment_gateways import GatewayFactory
from app.bot.utils.formatting import format_subscription_period
from app.bot.utils.navigation import NavSubscription
from app.db.models import User

from .keyboard import pay_keyboard

logger = logging.getLogger(__name__)
router = Router(name=__name__)


class PaymentState(StatesGroup):
    processing = State()


@router.callback_query(SubscriptionData.filter(F.state.startswith(NavSubscription.PAY)))
async def callback_payment_method_selected(
    callback: CallbackQuery,
    user: User,
    callback_data: SubscriptionData,
    services: ServicesContainer,
    gateway_factory: GatewayFactory,
    state: FSMContext,
) -> None:
    if await state.get_state() == PaymentState.processing:
        logger.debug("User %s is already processing payment.", user.tg_id)
        return

    await state.set_state(PaymentState.processing)

    try:
        method = callback_data.state
        devices = callback_data.devices
        duration = callback_data.duration
        volume_gb = callback_data.volume_gb
        logger.info("User %s selected payment method: %s", user.tg_id, method)
        logger.info(
            "User %s selected %s devices, %s days and %s GB.",
            user.tg_id,
            devices,
            duration,
            volume_gb,
        )

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

            text = (
                "💳 <b>فاکتور کارت به کارت هوشمند آبان گیت</b>\n"
                "━━━━━━━━━━━━━━━\n"
                f"کد پیگیری: <code>{order_id}</code>\n"
                f"شماره فاکتور آبان گیت: <code>{invoice_id}</code>\n"
                f"مبلغ سفارش: <code>{price:,.0f}</code> تومان\n"
                f"مبلغ قابل پرداخت: <code>{float(payable_toman):,.0f}</code> تومان\n"
                "مهلت پرداخت: <b>طبق زمان اعلام‌شده در صفحه آبان گیت</b>\n"
                "━━━━━━━━━━━━━━━\n\n"
                "برای پرداخت، روی دکمه <b>«💳 پرداخت»</b> بزنید.\n"
                "پس از تأیید آبان گیت، شارژ یا سفارش شما به‌صورت خودکار انجام می‌شود."
            )
        elif callback_data.is_extend:
            text = _("payment:message:order_extend")
        elif callback_data.is_change:
            text = _("payment:message:order_change")
        else:
            text = _("payment:message:order")

        await callback.message.edit_text(
            text=text.format(
                devices=devices,
                duration=format_subscription_period(duration),
                volume=volume_gb,
                price=price,
                currency=gateway.currency.symbol,
            ),
            reply_markup=pay_keyboard(pay_url=pay_url, callback_data=callback_data),
        )
    except Exception as exception:
        logger.exception("Error processing payment for user %s: %s", user.tg_id, exception)
        await services.notification.show_popup(callback=callback, text=_("payment:popup:error"))
    finally:
        await state.set_state(None)
