import unittest

from app.bot.models.subscription_data import SubscriptionData
from app.bot.utils.navigation import NavSubscription


class SubscriptionCallbackDataTests(unittest.TestCase):
    def test_subscription_menu_callback_is_under_telegram_limit(self) -> None:
        data = SubscriptionData(
            state=NavSubscription.PROCESS,
            user_id=418272523,
        )
        packed = data.pack()
        self.assertLessEqual(len(packed.encode("utf-8")), 64)
        self.assertEqual(packed, "subscription:p:0:0:0:0:0:0")

    def test_full_purchase_callback_round_trips_compact_fields(self) -> None:
        data = SubscriptionData(
            state=NavSubscription.PAY_ZARINPAL,
            is_extend=False,
            is_change=False,
            user_id=418272523,
            devices=1,
            duration=30,
            price=760000,
            plan_id=123,
            volume_gb=30,
            config_name="30GB-30D-tg418272523-1",
        )
        packed = data.pack()
        self.assertLessEqual(len(packed.encode("utf-8")), 64)
        restored = SubscriptionData.unpack(packed)
        self.assertEqual(restored.state, NavSubscription.PAY_ZARINPAL)
        self.assertEqual(restored.devices, 1)
        self.assertEqual(restored.duration, 30)
        self.assertEqual(restored.price, 760000)
        self.assertEqual(restored.plan_id, 123)
        self.assertEqual(restored.volume_gb, 30)
        self.assertEqual(restored.config_name, data.config_name)

    def test_long_config_name_is_not_put_in_callback(self) -> None:
        data = SubscriptionData(
            state=NavSubscription.PAY_ZARINPAL,
            devices=1,
            duration=30,
            price=760000,
            plan_id=123,
            volume_gb=30,
            config_name="x" * 200,
        )
        packed = data.pack()
        self.assertLessEqual(len(packed.encode("utf-8")), 64)
        restored = SubscriptionData.unpack(packed)
        self.assertEqual(restored.config_name, "")

    def test_legacy_subscription_callback_remains_unpackable(self) -> None:
        legacy = "subscription:process:0:0:418272523:0:0:0:0:0:0:0::0:0::subscription"
        restored = SubscriptionData.unpack(legacy)
        self.assertEqual(restored.state, NavSubscription.PROCESS)
        self.assertEqual(restored.user_id, 418272523)


if __name__ == "__main__":
    unittest.main()
