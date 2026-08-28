from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.bot.services import (
        NotificationService,
        PlanService,
        ServerPoolService,
        VPNService,
        ReferralService,
        SubscriptionService,
        PaymentStatsService,
        InviteStatsService,
        WalletService,
        TestAccountService,
    )

from dataclasses import dataclass


@dataclass
class ServicesContainer:
    server_pool: ServerPoolService
    plan: PlanService
    vpn: VPNService
    notification: NotificationService
    referral: ReferralService
    subscription: SubscriptionService
    test_account: TestAccountService
    payment_stats: PaymentStatsService
    invite_stats: InviteStatsService
    wallet: WalletService
