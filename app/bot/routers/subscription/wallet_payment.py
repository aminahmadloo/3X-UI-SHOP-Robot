import logging
from uuid import uuid4

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import ServicesContainer, SubscriptionData
from app.bot.utils.constants import TransactionStatus
from app.bot.utils.navigation import NavSubscription
from app.config import Config
from app.db.models import ServicePurchasePlan, Transaction, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)

WALLET_PAYMENT_PREFIX = "wallet_payment"


def _subscription_from_state(data: dict, user_tg_id: int) -> SubscriptionData | None:
    packed = data.get("subscription_data")
    if not isinstance(packed, dict):
        return None

    try:
        subscription = SubscriptionData(
            state=NavSubscription.CONFIG_NAME,
            is_extend=packed.get("is_extend", False),
            is_change=packed.get("is_change", False),
            user_id=packed.get("user_id", user_tg_id),
            devices=int(packed.get("devices", 0)),
            duration=int(packed.get("duration", 0)),
            price=int(round(float(packed.get("price", 0)))),
            plan_id=int(packed.get("plan_id", 0)),
            volume_gb=int(packed.get("volume_gb", 0)),
            config_name=str(packed.get("config_name", "")),
        )
    except (TypeError, ValueError):
        return None

    if subscription.user_id != user_tg_id:
        return None
    if subscription.plan_id <= 0 or subscription.price <= 0:
        return None
    if not subscription.config_name:
        return None
    return subscription


@router.callback_query(F.data.regexp(r"^mp_wallet:\d+$"))
async def managed_wallet_payment(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state: FSMContext,
    services: ServicesContainer,
    config: Config,
) -> None:
    plan_id = int((callback.data or "").rsplit(":", 1)[1])
    data = await state.get_data()
    subscription = _subscription_from_state(data, user.tg_id)

    if not subscription or subscription.plan_id != plan_id:
        await callback.answer(
            "❌ اطلاعات سفارش منقضی یا نامعتبر است. لطفاً دوباره پلن را انتخاب کنید.",
            show_alert=True,
        )
        await state.clear()
        return

    plan = await ServicePurchasePlan.get(session, plan_id)
    if not plan:
        await callback.answer("❌ این پلن دیگر وجود ندارد.", show_alert=True)
        return

    payment_id = f"{WALLET_PAYMENT_PREFIX}:{uuid4().hex}"

    transaction = await Transaction.create(
        session=session,
        tg_id=user.tg_id,
        subscription=subscription.serialize(),
        payment_id=payment_id,
        status=TransactionStatus.PENDING,
    )
    if transaction is None:
        await callback.answer("❌ ایجاد تراکنش پرداخت ناموفق بود.", show_alert=True)
        return

    try:
        balance = await services.wallet.debit(
            user_tg_id=user.tg_id,
            amount=int(subscription.price),
            transaction_type="purchase",
            description=(
                f"خرید سرویس {subscription.volume_gb}GB / "
                f"{subscription.duration}D"
            ),
            reference_id=payment_id,
        )
    except ValueError:
        await Transaction.update(
            session=session,
            payment_id=payment_id,
            status=TransactionStatus.CANCELED,
        )
        await callback.answer(
            "❌ موجودی کیف پول برای این خرید کافی نیست.",
            show_alert=True,
        )
        return
    except Exception:
        await Transaction.update(
            session=session,
            payment_id=payment_id,
            status=TransactionStatus.CANCELED,
        )
        logger.exception("Wallet debit failed for %s", user.tg_id)
        await callback.answer("❌ پرداخت کیف پول انجام نشد.", show_alert=True)
        return

    service_user = await User.get(session=session, tg_id=user.tg_id)
    if service_user is None:
        try:
            await services.wallet.credit(
                user_tg_id=user.tg_id,
                amount=int(subscription.price),
                transaction_type="purchase_refund",
                description="بازگشت وجه به علت پیدا نشدن کاربر",
                reference_id=f"{payment_id}:refund",
            )
        except Exception:
            logger.exception("CRITICAL: failed to refund missing-user wallet payment %s", payment_id)
        await Transaction.update(session=session, payment_id=payment_id, status=TransactionStatus.CANCELED)
        await callback.answer("❌ کاربر سفارش پیدا نشد؛ مبلغ بازگردانده شد.", show_alert=True)
        return

    success = False
    try:
        if subscription.is_extend:
            success = await services.vpn.extend_subscription(
                user=service_user,
                devices=subscription.devices,
                duration=subscription.duration,
                total_gb=subscription.volume_gb,
            )
        elif subscription.is_change:
            success = await services.vpn.change_subscription(
                user=service_user,
                devices=subscription.devices,
                duration=subscription.duration,
                total_gb=subscription.volume_gb,
            )
        else:
            success = await services.vpn.create_subscription(
                user=service_user,
                devices=subscription.devices,
                duration=subscription.duration,
                total_gb=subscription.volume_gb,
                config_name=subscription.config_name,
            )
    except Exception:
        logger.exception("VPN provisioning failed after wallet debit for %s", user.tg_id)

    if not success:
        try:
            await services.wallet.credit(
                user_tg_id=user.tg_id,
                amount=int(subscription.price),
                transaction_type="purchase_refund",
                description="بازگشت وجه خرید ناموفق سرویس",
                reference_id=f"{payment_id}:refund",
            )
        except Exception:
            logger.exception("CRITICAL: failed to refund wallet payment %s", payment_id)

        await Transaction.update(
            session=session,
            payment_id=payment_id,
            status=TransactionStatus.CANCELED,
        )
        await callback.answer(
            "❌ ساخت سرویس انجام نشد و مبلغ به کیف پول شما بازگردانده شد.",
            show_alert=True,
        )
        return

    await Transaction.update(
        session=session,
        payment_id=payment_id,
        status=TransactionStatus.COMPLETED,
    )

    await state.clear()
    await callback.answer("✅ پرداخت با کیف پول انجام شد و سرویس آماده است.", show_alert=True)

    if subscription.is_extend:
        await services.notification.notify_extend_success(
            user_id=user.tg_id,
            data=subscription,
        )
    elif subscription.is_change:
        await services.notification.notify_change_success(
            user_id=user.tg_id,
            data=subscription,
        )
    else:
        # Remove the payment-method selection message before sending
        # the final successful-payment message.
        try:
            if callback.message:
                await callback.message.delete()
                logger.info(
                    "Payment method selection message deleted for user %s",
                    user.tg_id,
                )
        except Exception:
            logger.warning(
                "Failed to delete payment method selection message for user %s",
                user.tg_id,
                exc_info=True,
            )

        key = await services.vpn.get_key(service_user)
        await services.notification.notify_purchase_success(
            user_id=user.tg_id,
            key=key,
        )

    logger.info(
        "Wallet payment completed for user %s: payment=%s amount=%s balance=%s",
        user.tg_id,
        payment_id,
        subscription.price,
        balance,
    )
