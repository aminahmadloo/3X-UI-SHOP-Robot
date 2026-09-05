from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.bot.services import NotificationService, VPNService

import logging
from decimal import Decimal

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.models import SubscriptionData
from app.bot.services.customer_level import get_customer_level
from app.bot.services.wallet import WalletService
from app.bot.utils.constants import ReferrerRewardLevel, ReferrerRewardType, TransactionStatus
from app.bot.utils.formatting import to_decimal
from app.bot.utils.navigation import NavMain
from app.config import Config
from app.db.models import Referral, ReferrerReward, ReferralSettings, Transaction, User

logger = logging.getLogger(__name__)


class ReferralService:
    def __init__(self, config: Config, session_factory: async_sessionmaker, vpn_service: VPNService, wallet_service: WalletService, notification_service: NotificationService) -> None:
        self.config = config
        self.session_factory = session_factory
        self.vpn_service = vpn_service
        self.wallet_service = wallet_service
        self.notification_service = notification_service

    async def is_referred_trial_available(self, user: User) -> bool:
        if not (self.config.shop.REFERRED_TRIAL_ENABLED and not user.server_id and not user.is_trial_used):
            return False
        async with self.session_factory() as session:
            referral = await Referral.get_referral(session, user.tg_id)
        return referral and not referral.referred_rewarded_at

    async def reward_referred_user(self, user: User, days_count: int) -> bool:
        if not await self.is_referred_trial_available(user):
            return False
        async with self.session_factory() as session:
            referral = await Referral.get_referral_with_users(session=session, referred_tg_id=user.tg_id)
            rewarded = await Referral.set_rewarded(session=session, referral=referral, referred_bonus_days=days_count)
            if not rewarded:
                return False
            success = await self.vpn_service.process_bonus_days(referral.referred, duration=self.config.shop.REFERRED_TRIAL_PERIOD, devices=self.config.shop.BONUS_DEVICES_COUNT)
            if success:
                return True
            await Referral.rollback_rewarded(session=session, referral=referral)
            return False

    @staticmethod
    def _select_reward_percent(settings: ReferralSettings, purchase_count: int) -> int:
        return int(settings.reward_percent if purchase_count == 0 else settings.repeat_reward_percent)

    @staticmethod
    async def _completed_purchase_count(session, referred_tg_id: int, current_payment_id: str) -> int:
        result = await session.execute(select(Transaction).where(Transaction.tg_id == referred_tg_id, Transaction.status == TransactionStatus.COMPLETED, Transaction.payment_id != current_payment_id))
        purchase_count = 0
        for transaction in result.scalars().all():
            try:
                data = SubscriptionData.deserialize(transaction.subscription)
                if data.payment_kind == "wallet_topup" or data.duration <= 0:
                    continue
            except Exception:
                continue
            purchase_count += 1
        return purchase_count

    async def _notify_referrer_purchase_point(self, session, referrer_tg_id: int, referred_user: User | None = None) -> None:
        try:
            level, points = await get_customer_level(session, referrer_tg_id)
            discount = f"{level.discount_percent}%" if level.discount_percent > 0 else f"ندارید ({level.title})"
            referred_name = (referred_user.first_name or "کاربر") if referred_user else "کاربر"
            referred_username = f"@{referred_user.username}" if referred_user and referred_user.username else "ندارد"
            referred_tg_id = referred_user.tg_id if referred_user else "نامشخص"
            keyboard = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 ورود به صفحه شروع ربات", callback_data=NavMain.MAIN_MENU, style="danger")]
                ]
            )
            await self.notification_service.notify_by_id(
                chat_id=referrer_tg_id,
                text=(
                    "🎉 <b>یک امتیاز جدید گرفتی!</b>\n\n"
                    f"💳 فرد دعوت‌شده شما <b>{referred_name}</b> یک خرید موفق انجام داد.\n"
                    f"👤 یوزرنیم: <b>{referred_username}</b>\n"
                    f"🆔 آیدی تلگرام: <code>{referred_tg_id}</code>\n\n"
                    "⭐️ امتیاز شما: <b>+1</b>\n"
                    f"⭐️ مجموع امتیازات شما: <b>{points}</b>\n"
                    f"⚡️ سطح فعلی: <b>{level.title}</b>\n"
                    f"💰 تخفیف خرید شما: <b>{discount}</b>"
                ),
                reply_markup=keyboard,
            )
        except Exception:
            logger.exception("Failed to notify referrer %s about purchase point", referrer_tg_id)

    async def add_referrers_rewards_on_payment(self, referred_tg_id: int, payment_amount: float, payment_id: str) -> bool:
        async with self.session_factory() as session:
            referral = await Referral.get_referral_with_users(session, referred_tg_id)
            if not referral:
                return False
            referrer_tg_id = referral.referrer_tg_id
            if not self.config.shop.REFERRER_REWARD_ENABLED:
                return False
            settings = await ReferralSettings.get_or_create(session)
            mode = self.config.shop.REFERRER_REWARD_TYPE
            if mode == ReferrerRewardType.DAYS.value:
                first_level_reward_amount = self.config.shop.REFERRER_LEVEL_ONE_PERIOD
                second_level_reward_amount = self.config.shop.REFERRER_LEVEL_TWO_PERIOD
            elif mode == ReferrerRewardType.MONEY.value:
                payment_amount = to_decimal(payment_amount)
                purchase_count = await self._completed_purchase_count(session, referred_tg_id, payment_id)
                reward_percent = self._select_reward_percent(settings, purchase_count)
                first_level_reward_amount = to_decimal(payment_amount * Decimal(reward_percent) / Decimal(100))
                second_level_reward_amount = to_decimal(payment_amount * Decimal(self.config.shop.REFERRER_LEVEL_TWO_RATE) / Decimal(100))
            else:
                first_level_reward_amount = Decimal(0)
                second_level_reward_amount = Decimal(0)

            rewards_created = []
            if referrer_tg_id and first_level_reward_amount > 0:
                reward = await ReferrerReward.create_referrer_reward(session=session, user_tg_id=referrer_tg_id, reward_type=ReferrerRewardType.from_str(mode), amount=first_level_reward_amount, reward_level=ReferrerRewardLevel.FIRST_LEVEL, payment_id=payment_id)
                if reward:
                    rewards_created.append(reward)

            second_level_referral = await Referral.get_referral(session, referrer_tg_id)
            if second_level_reward_amount > 0 and second_level_referral and second_level_referral.referrer_tg_id:
                reward = await ReferrerReward.create_referrer_reward(session=session, user_tg_id=second_level_referral.referrer_tg_id, reward_type=ReferrerRewardType.from_str(mode), amount=second_level_reward_amount, reward_level=ReferrerRewardLevel.SECOND_LEVEL, payment_id=payment_id)
                if reward:
                    rewards_created.append(reward)

            if referrer_tg_id:
                prior_purchases = await self._completed_purchase_count(session, referred_tg_id, payment_id)
                if prior_purchases == 0:
                    await self._notify_referrer_purchase_point(session, referrer_tg_id, referral.referred)

            return bool(rewards_created)

    async def process_referrer_rewards_after_payment(self, reward: ReferrerReward) -> bool:
        if reward.rewarded_at:
            return False
        async with self.session_factory() as session:
            if reward.reward_type == ReferrerRewardType.DAYS:
                days = int(reward.amount)
                user = await User.get(session=session, tg_id=reward.user_tg_id)
                if not user:
                    return False
                success = await self.vpn_service.process_bonus_days(user=user, duration=days, devices=self.config.shop.BONUS_DEVICES_COUNT)
                if not success:
                    return False
            elif reward.reward_type == ReferrerRewardType.MONEY:
                amount = int(round(float(reward.amount)))
                if amount <= 0:
                    return False
                settings = await ReferralSettings.get_or_create(session)
                await self.wallet_service.credit(user_tg_id=reward.user_tg_id, amount=amount, transaction_type="referral_reward", description=f"پاداش معرفی به دوستان ({settings.reward_percent}% خرید اول / {settings.repeat_reward_percent}% خریدهای بعدی)", reference_id=f"referral_reward:{reward.id}")
            else:
                return False
            await ReferrerReward.mark_reward_as_given(session=session, reward=reward)
            return True
