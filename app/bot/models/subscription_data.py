import json
import string

from aiogram.filters.callback_data import CallbackData
from pydantic import PrivateAttr

from app.bot.utils.navigation import NavSubscription


_B36 = string.digits + string.ascii_lowercase
_STATE_TO_CODE = {
    NavSubscription.MAIN.value: "m",
    NavSubscription.BUY.value: "b",
    NavSubscription.RENEW_SERVICE.value: "rs",
    NavSubscription.ADD_TRAFFIC.value: "at",
    NavSubscription.CHANGE.value: "c",
    NavSubscription.EXTEND.value: "e",
    NavSubscription.PROCESS.value: "p",
    NavSubscription.DEVICES.value: "d",
    NavSubscription.DURATION.value: "du",
    NavSubscription.PLAN_ONE_MONTH.value: "p1",
    NavSubscription.PLAN_THREE_MONTH.value: "p3",
    NavSubscription.PLAN.value: "pl",
    NavSubscription.CONFIG_NAME.value: "cn",
    NavSubscription.PROMOCODE.value: "pc",
    NavSubscription.GIFT_CODE.value: "g",
    NavSubscription.GET_TRIAL.value: "gt",
    NavSubscription.PAY.value: "pay",
    NavSubscription.PAY_ZARINPAL.value: "pz",
    NavSubscription.BACK_TO_DURATION.value: "bd",
    NavSubscription.BACK_TO_PAYMENT.value: "bp",
    "pay_aban": "pa",
    "pay_blupal": "pb",
    "pay_variza": "pv",
}
_CODE_TO_STATE = {value: key for key, value in _STATE_TO_CODE.items()}


def _b36_encode(value: int) -> str:
    value = int(value or 0)
    if value == 0:
        return "0"
    result = ""
    while value:
        value, remainder = divmod(value, 36)
        result = _B36[remainder] + result
    return result


def _b36_decode(value: str) -> int:
    return int(value or "0", 36)


class SubscriptionData(CallbackData, prefix="subscription"):
    state: NavSubscription
    is_extend: bool = False
    is_change: bool = False
    user_id: int = 0
    devices: int = 0
    duration: int = 0
    price: float = 0
    original_price: int = 0
    base_plan_price: int = 0
    special_offer: bool = False
    discount_percent: int = 0
    discount_level_title: str = ""
    plan_id: int = 0
    volume_gb: int = 0
    config_name: str = ""
    payment_kind: str = "subscription"
    _subscription_id: int = PrivateAttr(default=0)

    @property
    def subscription_id(self) -> int:
        return self._subscription_id

    @subscription_id.setter
    def subscription_id(self, value: int) -> None:
        self._subscription_id = int(value or 0)

    def pack(self) -> str:
        """Pack only callback-routing data into Telegram's 64-byte budget."""
        state = self.state.value if isinstance(self.state, NavSubscription) else str(self.state)
        state_code = _STATE_TO_CODE.get(state, state)
        flags = (1 if self.is_extend else 0) | (2 if self.is_change else 0)
        payload = (
            f"subscription:{state_code}:{flags}:"
            f"{_b36_encode(self.devices)}:{_b36_encode(self.duration)}:"
            f"{self.price:g}:{_b36_encode(self.plan_id)}:{_b36_encode(self.volume_gb)}"
        )

        config_name = str(self.config_name or "")
        if config_name:
            candidate = f"{payload}:{config_name}"
            if len(candidate.encode("utf-8")) <= 64:
                flags |= 4
                payload = (
                    f"subscription:{state_code}:{flags}:"
                    f"{_b36_encode(self.devices)}:{_b36_encode(self.duration)}:"
                    f"{self.price:g}:{_b36_encode(self.plan_id)}:{_b36_encode(self.volume_gb)}:{config_name}"
                )

        size = len(payload.encode("utf-8"))
        if size > 64:
            raise ValueError(f"Subscription callback data exceeds Telegram limit: {size} bytes")
        return payload

    @classmethod
    def unpack(cls, value: str) -> "SubscriptionData":
        """Unpack compact callbacks and retain compatibility with legacy data."""
        parts = value.split(":")
        if len(parts) >= 8 and parts[0] == "subscription" and parts[1] in _CODE_TO_STATE:
            state = _CODE_TO_STATE[parts[1]]
            flags = int(parts[2] or 0)
            return cls(
                state=NavSubscription(state) if state in NavSubscription._value2member_map_ else state,
                is_extend=bool(flags & 1),
                is_change=bool(flags & 2),
                devices=_b36_decode(parts[3]),
                duration=_b36_decode(parts[4]),
                price=float(parts[5] or 0),
                plan_id=_b36_decode(parts[6]),
                volume_gb=_b36_decode(parts[7]),
                config_name=parts[8] if len(parts) > 8 and flags & 4 else "",
            )
        return super().unpack(value)

    def serialize(self) -> str:
        """Serialize full subscription data for FSM/database storage."""
        return json.dumps(
            {
                "state": self.state.value,
                "is_extend": self.is_extend,
                "is_change": self.is_change,
                "user_id": self.user_id,
                "devices": self.devices,
                "duration": self.duration,
                "price": self.price,
                "original_price": self.original_price,
                "base_plan_price": self.base_plan_price,
                "special_offer": self.special_offer,
                "discount_percent": self.discount_percent,
                "discount_level_title": self.discount_level_title,
                "plan_id": self.plan_id,
                "volume_gb": self.volume_gb,
                "config_name": self.config_name,
                "payment_kind": self.payment_kind,
                "subscription_id": self.subscription_id,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @classmethod
    def deserialize(cls, value: str) -> "SubscriptionData":
        """Restore persisted subscription data, including legacy callback data."""
        try:
            payload = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return cls.unpack(value)

        if not isinstance(payload, dict):
            raise ValueError("Invalid subscription data payload")

        data = cls(
            state=NavSubscription(payload.get("state", NavSubscription.CONFIG_NAME)),
            is_extend=payload.get("is_extend", False),
            is_change=payload.get("is_change", False),
            user_id=payload.get("user_id", 0),
            devices=payload.get("devices", 0),
            duration=payload.get("duration", 0),
            price=payload.get("price", 0),
            original_price=payload.get("original_price", 0),
            base_plan_price=payload.get("base_plan_price", 0),
            special_offer=payload.get("special_offer", False),
            discount_percent=payload.get("discount_percent", 0),
            discount_level_title=payload.get("discount_level_title", ""),
            plan_id=payload.get("plan_id", 0),
            volume_gb=payload.get("volume_gb", 0),
            config_name=payload.get("config_name", ""),
            payment_kind=payload.get("payment_kind", "subscription"),
        )
        data.subscription_id = payload.get("subscription_id", 0)
        return data
