import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.payment_gateways import GatewayFactory
from app.bot.routers.subscription.keyboard import pay_keyboard
from app.bot.utils.navigation import NavSubscription
from app.db.models import ServicePurchasePlan, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


@router.callback_query(F.data.regexp(r"^mp:pay_[^:]+:\d+$"))
async def callback_managed_payment_compat(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    gateway_factory: GatewayFactory,
    state: FSMContext,
) -> None:
    """Handle the compact payment callback used by purchase/renewal keyboards.

    The purchase flow historically used ``mp:subscription:pay_*`` while the
    current keyboard emits ``mp:pay_*``. This compatibility handler accepts
    both dict and serialized-string purchase contexts so changing payment
    methods after returning from another gateway cannot invalidate the order.
    Traffic add-ons are excluded by requiring a positive duration.
    """
    gateway_callback, plan_id_text = callback.data[3:].rsplit(":", 1)

    data = await state.get_data()
    packed = data.get("subscription_data")

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
        await callback.answer("اطلاعات سفارش منقضی شده است. لطفاً دوباره پلن را انتخاب کنید.", show_alert=True)
        return

    duration = int(packed.get("duration", 0) or 0)
    if duration <= 0:
        # Let the dedicated traffic/add-on handler deal with zero-duration orders.
        await callback.answer()
        return

    subscription_data = SubscriptionData(
        state=NavSubscription.CONFIG_NAME,
        is_extend=packed.get("is_extend", False),
        is_change=packed.get("is_change", False),
        user_id=packed.get("user_id", user.tg_id),
        devices=packed.get("devices", 0),
        duration=duration,
        price=packed.get("price", 0),
        plan_id=packed.get("plan_id", 0),
        volume_gb=packed.get("volume_gb", 0),
        config_name=packed.get("config_name", ""),
    )
    subscription_data.subscription_id = packed.get("subscription_id", 0)

    if subscription_data.user_id != user.tg_id or subscription_data.plan_id != int(plan_id_text):
        await callback.answer("❌ اطلاعات سفارش با پلن انتخاب‌شده مطابقت ندارد.", show_alert=True)
        return

    plan = await ServicePurchasePlan.get(session, int(plan_id_text))
    if not plan or plan.duration_days <= 0 or plan.volume_gb <= 0:
        await callback.answer("❌ این پلن برای پرداخت مستقیم معتبر نیست.", show_alert=True)
        return

    try:
        gateway = gateway_factory.get_gateway(gateway_callback)
        pay_url = await gateway.create_payment(subscription_data)

        if gateway_callback == "pay_aban":
            invoice_id = pay_url.rstrip("/").rsplit("/", 1)[-1]
            invoice = await gateway._get_invoice(invoice_id)  # type: ignore[attr-defined]
            order_id = str(invoice.get("order_id") or "").strip()
            payable_toman = invoice.get("payable_toman")

            if not invoice_id or not order_id or payable_toman is None:
                raise RuntimeError("AbanGateway returned incomplete invoice details")

            if subscription_data.is_extend:
                text = (
                    "💳 <b>فاکتور کارت به کارت هوشمند آبان گیت</b>\n"
                    "━━━━━━━━━━━━━━━\n"
                    f"کد پیگیری: <code>{order_id}</code>\n"
                    f"شماره فاکتور آبان گیت: <code>{invoice_id}</code>\n"
                    f"نام کانفیگ: <code>{subscription_data.config_name}</code>\n"
                    f"حجم افزوده: <code>{plan.volume_gb} گیگ</code>\n"
                    f"زمان افزوده: <code>{plan.duration_days} روز</code>\n"
                    f"مبلغ سفارش: <code>{subscription_data.price:,.0f}</code> تومان\n"
                    f"مبلغ قابل پرداخت: <code>{float(payable_toman):,.0f}</code> تومان\n"
                    "مهلت پرداخت: <b>طبق زمان اعلام‌شده در صفحه آبان گیت</b>\n"
                    "━━━━━━━━━━━━━━━\n\n"
                    "برای پرداخت، روی دکمه <b>«💳 پرداخت»</b> بزنید.\n"
                    "پس از تأیید آبان گیت، تمدید سرویس به‌صورت خودکار انجام می‌شود."
                )
            else:
                text = (
                    "💳 <b>فاکتور کارت به کارت هوشمند آبان گیت</b>\n"
                    "━━━━━━━━━━━━━━━\n"
                    f"کد پیگیری: <code>{order_id}</code>\n"
                    f"شماره فاکتور آبان گیت: <code>{invoice_id}</code>\n"
                    f"نام کانفیگ: <code>{subscription_data.config_name}</code>\n"
                    f"حجم: <code>{subscription_data.volume_gb} گیگ</code>\n"
                    f"مدت: <code>{subscription_data.duration} روز</code>\n"
                    f"مبلغ سفارش: <code>{subscription_data.price:,.0f}</code> تومان\n"
                    f"مبلغ قابل پرداخت: <code>{float(payable_toman):,.0f}</code> تومان\n"
                    "مهلت پرداخت: <b>طبق زمان اعلام‌شده در صفحه آبان گیت</b>\n"
                    "━━━━━━━━━━━━━━━\n\n"
                    "برای پرداخت، روی دکمه <b>«💳 پرداخت»</b> بزنید.\n"
                    "پس از تأیید آبان گیت، شارژ یا سفارش شما به‌صورت خودکار انجام می‌شود."
                )
        else:
            text = (
                "🧾 <b>سفارش شما</b>\n\n"
                f"📝 نام کانفیگ: <code>{subscription_data.config_name}</code>\n"
                f"📱 تعداد دستگاه: <b>{subscription_data.devices}</b>\n"
                f"💾 حجم: <b>{subscription_data.volume_gb} گیگ</b>\n"
                f"📅 مدت: <b>{subscription_data.duration} روز</b>\n"
                f"💰 مبلغ: <b>{subscription_data.price:,} تومان</b>"
            )

        await callback.answer()
        await callback.message.edit_text(
            text,
            reply_markup=pay_keyboard(pay_url, subscription_data),
        )
    except Exception as exc:
        logger.exception("Managed payment creation failed: %s", exc)
        await callback.answer("❌ خطا در ایجاد پرداخت.", show_alert=True)
