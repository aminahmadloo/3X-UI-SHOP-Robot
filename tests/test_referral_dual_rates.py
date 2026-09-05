from app.bot.services.referral import ReferralService
from app.db.models import ReferralSettings


def test_referral_uses_first_purchase_rate_for_first_purchase() -> None:
    settings = ReferralSettings(reward_percent=30, repeat_reward_percent=5)

    assert ReferralService._select_reward_percent(settings, 0) == 30


def test_referral_uses_repeat_rate_after_first_purchase() -> None:
    settings = ReferralSettings(reward_percent=30, repeat_reward_percent=5)

    assert ReferralService._select_reward_percent(settings, 1) == 5
    assert ReferralService._select_reward_percent(settings, 10) == 5


def test_referral_rates_are_dynamic_from_settings() -> None:
    settings = ReferralSettings(reward_percent=40, repeat_reward_percent=7)

    assert ReferralService._select_reward_percent(settings, 0) == 40
    assert ReferralService._select_reward_percent(settings, 3) == 7
