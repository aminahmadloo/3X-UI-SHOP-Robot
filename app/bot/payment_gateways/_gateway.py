import logging
from abc import ABC, abstractmethod

from aiogram import Bot
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.utils.i18n import I18n
from aiogram.utils.i18n import gettext as _
from aiohttp.web import Application
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.models import ServicesContainer, SubscriptionData
from app.bot.utils.constants import (
    DEFAULT_LANGUAGE,
    EVENT_PAYMENT_CANCELED_TAG,
    EVENT_PAYMENT_SUCCEEDED_TAG,
    Currency,
    TransactionStatus,
)
from app.bot.utils.formatting import format_device_count, format_subscription_period
from app.config import Config
from app.db.models import Subscription, Transaction, User

logger = logging.getLogger(__name__)


class PaymentGateway(ABC):
    name: str
    currency: Currency
    callback: str

    def __init__(self, app: Application, config: Config, session: async_sessionmaker, storage: RedisStorage, bot: Bot, i18n: I18n, services: ServicesContainer) -> None:
        self.app = app
        self.config = config
        self.session = session
        self.storage = storage
        self.bot = bot
        self.i18n = i18n
        self.services = services

    @abstractmethod
    async def create_payment(self, data: SubscriptionData) -> str:
        pass

    @abstractmethod
    async def handle_payment_succeeded(self, payment_id: str) -> None:
        pass

    @abstractmethod
    async def handle_payment_canceled(self, payment_id: str) -> None:
        pass

    async def _on_payment_succeeded(self, payment_id: str) -> None:
        logger.info(f"Payment succeeded {payment_id}")

        async with self.session() as session:
            transaction = await Transaction.get_by_id(session=session, payment_id=payment_id)
            if transaction is None:
                raise RuntimeError(f"Transaction {payment_id} was not found")
            data = SubscriptionData.deserialize(transaction.subscription)
            user = await User.get(session=session, tg_id=data.user_id)
            if user is None:
                raise RuntimeError(f"User {data.user_id} was not found for payment {payment_id}")

        if data.payment_kind == "wallet_topup":
            await self.services.wallet.credit(
                user_tg_id=user.tg_id,
                amount=int(data.price),
                transaction_type="topup",
                description="شارژ کیف پول از طریق درگاه بانکی",
                reference_id=f"zarinpal:{payment_id}",
            )
            async with self.session() as session:
                await Transaction.update(session=session, payment_id=payment_id, status=TransactionStatus.COMPLETED)
            balance = await self.services.wallet.get_balance(user.tg_id)
            await self.bot.send_message(user.tg_id, f"✅ <b>شارژ کیف پول با موفقیت انجام شد.</b>\n\n💰 مبلغ شارژ: <b>{int(data.price):,} تومان</b>\n💳 موجودی جدید: <b>{balance:,} تومان</b>")
            return

        try:
            if data.is_extend:
                if data.subscription_id:
                    from app.bot.services.renewal import extend_existing_subscription

                    success = await extend_existing_subscription(services=self.services, user=user, subscription_id=data.subscription_id, duration_days=data.duration, plan_id=data.plan_id)
                    if not success:
                        raise RuntimeError(f"Failed to extend subscription {data.subscription_id} for user {user.tg_id}")
                else:
                    success = await self.services.vpn.extend_subscription(user=user, devices=data.devices, duration=data.duration, total_gb=data.volume_gb)
                    if not success:
                        raise RuntimeError(f"Failed to extend subscription for user {user.tg_id}")
                logger.info(f"Subscription extended for user {user.tg_id}")
            elif data.is_change:
                success = await self.services.vpn.change_subscription(user=user, devices=data.devices, duration=data.duration, total_gb=data.volume_gb)
                if not success:
                    raise RuntimeError(f"Failed to change subscription for user {user.tg_id}")
                logger.info(f"Subscription changed for user {user.tg_id}")
            else:
                success = await self.services.vpn.create_subscription(user=user, devices=data.devices, duration=data.duration, total_gb=data.volume_gb, config_name=data.config_name)
                if not success:
                    raise RuntimeError(f"Failed to create subscription for user {user.tg_id}")
                if data.plan_id:
                    result = await session.execute(select(Subscription).where(Subscription.user_id == user.id).order_by(Subscription.id.desc()))
                    created_subscription = result.scalars().first()
                    if created_subscription is not None:
                        created_subscription.plan_id = data.plan_id
                        await session.commit()
                logger.info(f"Subscription created for user {user.tg_id}")
        except Exception:
            logger.exception("Payment %s succeeded but VPN provisioning failed; transaction remains pending for safe retry/reconciliation.", payment_id)
            raise

        async with self.session() as session:
            await Transaction.update(session=session, payment_id=payment_id, status=TransactionStatus.COMPLETED)

        if self.config.shop.REFERRER_REWARD_ENABLED:
            await self.services.referral.add_referrers_rewards_on_payment(referred_tg_id=data.user_id, payment_amount=data.price, payment_id=payment_id)

        await self.services.notification.notify_developer(text=EVENT_PAYMENT_SUCCEEDED_TAG + "\n\n" + _("payment:event:payment_succeeded").format(payment_id=payment_id, user_id=user.tg_id, devices=format_device_count(data.devices), duration=format_subscription_period(data.duration)))

        locale = user.language_code if user else DEFAULT_LANGUAGE
        with self.i18n.use_locale(locale):
            from app.bot.routers.main_menu.handler import redirect_to_main_menu

            async with self.session() as session:
                await redirect_to_main_menu(
                    bot=self.bot,
                    user=user,
                    services=self.services,
                    config=self.config,
                    session=session,
                    storage=self.storage,
                )
            if data.is_extend:
                await self.services.notification.notify_extend_success(user_id=user.tg_id, data=data)
            elif data.is_change:
                await self.services.notification.notify_change_success(user_id=user.tg_id, data=data)
            else:
                key = await self.services.vpn.get_key(user)
                await self.services.notification.notify_purchase_success(user_id=user.tg_id, key=key)

    async def _on_payment_canceled(self, payment_id: str) -> None:
        logger.info(f"Payment canceled {payment_id}")
        async with self.session() as session:
            transaction = await Transaction.get_by_id(session=session, payment_id=payment_id)
            data = SubscriptionData.deserialize(transaction.subscription)
            await Transaction.update(session=session, payment_id=payment_id, status=TransactionStatus.CANCELED)

        await self.services.notification.notify_developer(text=EVENT_PAYMENT_CANCELED_TAG + "\n\n" + _("payment:event:payment_canceled").format(payment_id=payment_id, user_id=data.user_id, devices=format_device_count(data.devices), duration=format_subscription_period(data.duration)))
