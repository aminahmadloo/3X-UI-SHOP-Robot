from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.bot.services import VPNService

import logging
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.models import SubscriptionData
from app.bot.utils.constants import ReferrerRewardLevel, ReferrerRewardType, TransactionStatus
from app.bot.utils.formatting import to_decimal
from app.bot.services.wallet import WalletService
from app.config import Config
from app.db.models import Referral, ReferrerReward, ReferralSettings, Transaction, User

logger = logging.getLogger(__name__)


class ReferralService:
    def __init__(
        self,
        config: Config,
        session_factory: async_sessionmaker,
        vpn_service: VPNService,
        wallet_service: WalletService,
    ) -> None:
        self.config = config
        self.session_factory = session_factory
        self.vpn_service = vpn_service
        self.wallet_service = wallet_service
        logger.info("Referral Service initialized")

    async def is_referred_trial_available(self, user: User) -> bool:
        is_first_check_ok = (
            self.config.shop.REFERRED_TRIAL_ENABLED
            and not user.server_id
            and not user.is_trial_used
        )
        if not is_first_check_ok:
            return False

        async with self.session_factory() as session:
            referral = await Referral.get_referral(session, user.tg_id)

        return referral and not referral.referred_rewarded_at

    async def reward_referred_user(self, user: User, days_count: int) -> bool:
        if not await self.is_referred_trial_available(user=user):
            logger.warning(
                f"Aborting. Tried to give referred-trial to the user {user.tg_id}, when it is unavailable."
            )
            return False

        async with self.session_factory() as session:
            referral = await Referral.get_referral_with_users(
                session=session, referred_tg_id=user.tg_id
            )

            rewarded = await Referral.set_rewarded(
                session=session, referral=referral, referred_bonus_days=days_count
            )
            if not rewarded:
                logger.warning(
                    f"Aborting. Tried to duplicate referred-trial period to a user {user.tg_id}"
                )
                return False

            logger.info(
                f"Started giving reward to referred user {referral.referred_tg_id}. Referral ID: {referral.id}"
            )
            referred_success = await self.vpn_service.process_bonus_days(
                referral.referred,
                duration=self.config.shop.REFERRED_TRIAL_PERIOD,
                devices=self.config.shop.BONUS_DEVICES_COUNT,
            )

            if referred_success:
                logger.info(
                    f"Referred-trial has been successfully processed for referral ID {referral.id}"
                )
                return True

            logger.warning(
                f"Failed while giving referred-trial {referral.id}. Rolling back Referral.referred_rewarded_at."
            )
            await Referral.rollback_rewarded(
                session=session,
                referral=referral,
            )

            return False

    @staticmethod
    def _select_reward_percent(settings: ReferralSettings, purchase_count: int) -> int:
        """Select the first-purchase or repeat-purchase commission rate."""
        return int(settings.reward_percent if purchase_count == 0 else settings.repeat_reward_percent)

    @staticmethod
    async def _completed_purchase_count(
        session, referred_tg_id: int, current_payment_id: str
    ) -> int:
        """Count completed purchases before the current payment by the referred user."""
        result = await session.execute(
            select(Transaction).where(
                Transaction.tg_id == referred_tg_id,
                Transaction.status == TransactionStatus.COMPLETED,
                Transaction.payment_id != current_payment_id,
            )
        )

        purchase_count = 0
        for transaction in result.scalars().all():
            try:
                data = SubscriptionData.deserialize(transaction.subscription)
                if data.payment_kind == "wallet_topup":
                    continue
            except Exception:
                # Preserve the existing behavior for legacy/non-deserializable
                # transaction payloads: they count as purchases unless they are
                # explicitly identified as wallet top-ups.
                pass
            purchase_count += 1

        return purchase_count

    async def add_referrers_rewards_on_payment(
        self, referred_tg_id: int, payment_amount: float, payment_id: str
    ) -> bool:
        if not self.config.shop.REFERRER_REWARD_ENABLED:
            logger.warning(
                f"Aborting. Tried to assign referrers payment reward for user {referred_tg_id}, when it is disabled."
            )
            return False

        async with self.session_factory() as session:
            referral = await Referral.get_referral_with_users(session, referred_tg_id)
            if not referral:
                logger.warning(f"No referral found for user {referred_tg_id} on payment event.")
                return False
            referrer_tg_id = referral.referrer_tg_id
            settings = await ReferralSettings.get_or_create(session)

            mode = self.config.shop.REFERRER_REWARD_TYPE

            if mode == ReferrerRewardType.DAYS.value:
                first_level_reward_amount = self.config.shop.REFERRER_LEVEL_ONE_PERIOD
                second_level_reward_amount = self.config.shop.REFERRER_LEVEL_TWO_PERIOD
            elif mode == ReferrerRewardType.MONEY.value:
                payment_amount = to_decimal(payment_amount)
                purchase_count = await self._completed_purchase_count(
                    session=session,
                    referred_tg_id=referred_tg_id,
                    current_payment_id=payment_id,
                )
                reward_percent = self._select_reward_percent(settings, purchase_count)
                reward_rate = Decimal(reward_percent) / Decimal(100)
                first_level_reward_amount = to_decimal(payment_amount * reward_rate)
                second_level_rate = Decimal(self.config.shop.REFERRER_LEVEL_TWO_RATE) / Decimal(100)
                second_level_reward_amount = to_decimal(payment_amount * second_level_rate)
                logger.info(
                    "Referral reward rate for referred user %s: %s%% (%s completed prior purchases)",
                    referred_tg_id,
                    reward_percent,
                    purchase_count,
                )
            else:
                first_level_reward_amount = Decimal(0)
                second_level_reward_amount = Decimal(0)

            rewards_created = []

            if referrer_tg_id and first_level_reward_amount > 0:
                reward = await ReferrerReward.create_referrer_reward(
                    session=session,
                    user_tg_id=referrer_tg_id,
                    reward_type=ReferrerRewardType.from_str(mode),
                    amount=first_level_reward_amount,
                    reward_level=ReferrerRewardLevel.FIRST_LEVEL,
                    payment_id=payment_id,
                )
                if reward:
                    rewards_created.append(reward)

            second_level_referral = await Referral.get_referral(session, referrer_tg_id)
            if (
                second_level_reward_amount > 0
                and second_level_referral
                and second_level_referral.referrer_tg_id
            ):
                reward = await ReferrerReward.create_referrer_reward(
                    session=session,
                    user_tg_id=second_level_referral.referrer_tg_id,
                    reward_type=ReferrerRewardType.from_str(mode),
                    amount=second_level_reward_amount,
                    reward_level=ReferrerRewardLevel.SECOND_LEVEL,
                    payment_id=payment_id,
                )
                if reward:
                    rewards_created.append(reward)

            return bool(rewards_created)

    async def process_referrer_rewards_after_payment(self, reward: ReferrerReward) -> bool:
        if reward.rewarded_at:
            logger.info(
                f"ReferrerReward {reward.id} (tg_id: {reward.user_tg_id}) was already given earlier."
            )
            return False

        async with self.session_factory() as session:
            if reward.reward_type == ReferrerRewardType.DAYS:
                days = int(reward.amount)
                user = await User.get(session=session, tg_id=reward.user_tg_id)
                if not user:
                    return False

                success = await self.vpn_service.process_bonus_days(
                    user=user, duration=days, devices=self.config.shop.BONUS_DEVICES_COUNT
                )
                if not success:
                    logger.error(
                        f"Failed to give {days} days reward to a referrer user {reward.user_tg_id}"
                    )
                    return False

                logger.info(f"Gave {days} days to a referrer user {reward.user_tg_id}")

            elif reward.reward_type == ReferrerRewardType.MONEY:
                amount = int(round(float(reward.amount)))
                if amount <= 0:
                    return False
                settings = await ReferralSettings.get_or_create(session)
                await self.wallet_service.credit(
                    user_tg_id=reward.user_tg_id,
                    amount=amount,
                    transaction_type="referral_reward",
                    description=(
                        f"پاداش معرفی به دوستان ({settings.reward_percent}% خرید اول / "
                        f"{settings.repeat_reward_percent}% خریدهای بعدی)"
                    ),
                    reference_id=f"referral_reward:{reward.id}",
                )
                logger.info("Credited %s toman referral reward to user %s", amount, reward.user_tg_id)

            else:
                logger.warning(
                    f"Failed to give referrer reward. Unknown reward type: {reward.reward_type}"
                )
                return False

            await ReferrerReward.mark_reward_as_given(session=session, reward=reward)

            logger.info(
                f"ReferrerReward {reward.id} (tg_id: {reward.user_tg_id}) successfully rewarded."
            )
            return True
