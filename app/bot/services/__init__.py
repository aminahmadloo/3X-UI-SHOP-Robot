from aiogram import Bot
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.models import ServicesContainer
from app.config import Config

from .invite_stats import InviteStatsService
from .notification import NotificationService
from .payment_stats import PaymentStatsService
from .plan import PlanService
from .referral import ReferralService
from .server_pool import ServerPoolService
from .subscription import SubscriptionService
from .test_account import TestAccountService
from .vpn import VPNService
from .wallet import WalletService


async def initialize(
    config: Config,
    session: async_sessionmaker,
    bot: Bot,
) -> ServicesContainer:
    server_pool = ServerPoolService(config=config, session=session)
    plan = PlanService()
    vpn = VPNService(config=config, session=session, server_pool_service=server_pool)
    notification = NotificationService(config=config, bot=bot)
    wallet = WalletService(session_factory=session)
    referral = ReferralService(
        config=config,
        session_factory=session,
        vpn_service=vpn,
        wallet_service=wallet,
        notification_service=notification,
    )
    subscription = SubscriptionService(config=config, session_factory=session, vpn_service=vpn)
    test_account = TestAccountService(
        config=config,
        session_factory=session,
        server_pool_service=server_pool,
    )
    payment_stats = PaymentStatsService(session_factory=session)
    invite_stats = InviteStatsService(session_factory=session, payment_stats_service=payment_stats)
    return ServicesContainer(
        server_pool=server_pool,
        plan=plan,
        vpn=vpn,
        notification=notification,
        referral=referral,
        subscription=subscription,
        test_account=test_account,
        payment_stats=payment_stats,
        invite_stats=invite_stats,
        wallet=wallet,
    )
