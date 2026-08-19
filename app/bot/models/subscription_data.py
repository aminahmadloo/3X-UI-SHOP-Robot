import json

from aiogram.filters.callback_data import CallbackData

from app.bot.utils.navigation import NavSubscription


class SubscriptionData(CallbackData, prefix="subscription"):
    state: NavSubscription
    is_extend: bool = False
    is_change: bool = False
    user_id: int = 0
    devices: int = 0
    duration: int = 0
    price: float = 0
    plan_id: int = 0
    volume_gb: int = 0
    config_name: str = ""
    subscription_id: int = 0

    def serialize(self) -> str:
        """Serialize subscription data for FSM/database storage.

        This is intentionally separate from CallbackData.pack(): Telegram
        limits callback_data to 64 bytes, while persisted order data does not
        have that restriction.
        """
        return json.dumps(
            {
                "state": self.state.value,
                "is_extend": self.is_extend,
                "is_change": self.is_change,
                "user_id": self.user_id,
                "devices": self.devices,
                "duration": self.duration,
                "price": self.price,
                "plan_id": self.plan_id,
                "volume_gb": self.volume_gb,
                "config_name": self.config_name,
                "subscription_id": self.subscription_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @classmethod
    def deserialize(cls, value: str) -> "SubscriptionData":
        """Restore persisted subscription data.

        Accept both the new JSON storage format and the legacy callback-data
        format so existing transactions/payments continue to work.
        """
        try:
            payload = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return cls.unpack(value)

        if not isinstance(payload, dict):
            raise ValueError("Invalid subscription data payload")

        return cls(
            state=NavSubscription(payload.get("state", NavSubscription.CONFIG_NAME)),
            is_extend=payload.get("is_extend", False),
            is_change=payload.get("is_change", False),
            user_id=payload.get("user_id", 0),
            devices=payload.get("devices", 0),
            duration=payload.get("duration", 0),
            price=payload.get("price", 0),
            plan_id=payload.get("plan_id", 0),
            volume_gb=payload.get("volume_gb", 0),
            config_name=payload.get("config_name", ""),
            subscription_id=payload.get("subscription_id", 0),
        )
