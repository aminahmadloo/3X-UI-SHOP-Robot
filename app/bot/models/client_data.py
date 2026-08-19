import time

from aiogram.utils.i18n import gettext as _

from app.bot.utils.constants import UNLIMITED
from app.bot.utils.formatting import format_remaining_time, format_size


class ClientData:
    def __init__(
        self,
        max_devices: int,
        traffic_total: int,
        traffic_remaining: int,
        traffic_used: int,
        traffic_up: int,
        traffic_down: int,
        expiry_time: str,
        client_id: str | None = None,
        sub_id: str | None = None,
        tg_id: int | None = None,
        flow: str | None = None,
        inbound_id: int | None = None,
        config_name: str | None = None,
    ) -> None:
        self._max_devices = max_devices
        self._traffic_total = traffic_total
        self._traffic_remaining = traffic_remaining
        self._traffic_used = traffic_used
        self._traffic_up = traffic_up
        self._traffic_down = traffic_down
        self._expiry_time = expiry_time
        self._client_id = client_id
        self._sub_id = sub_id
        self._tg_id = tg_id
        self._flow = flow
        self._inbound_id = inbound_id
        self._config_name = config_name

    def __str__(self) -> str:
        return (
            f"ClientData(max_devices={self._max_devices}, traffic_total={self._traffic_total}, "
            f"traffic_remaining={self._traffic_remaining}, traffic_used={self._traffic_used}, "
            f"traffic_up={self._traffic_up}, traffic_down={self._traffic_down}, "
            f"expiry_time={self._expiry_time}, client_id={self._client_id}, "
            f"sub_id={self._sub_id}, tg_id={self._tg_id}, flow={self._flow}, "
            f"inbound_id={self._inbound_id}, config_name={self._config_name})"
        )

    @property
    def max_devices(self) -> str:
        devices = self._max_devices
        if devices == -1:
            return UNLIMITED
        return devices

    @property
    def traffic_total(self) -> str:
        return format_size(self._traffic_total)

    @property
    def traffic_remaining(self) -> str:
        return format_size(self._traffic_remaining)

    @property
    def traffic_used(self) -> str:
        return format_size(self._traffic_used)

    @property
    def traffic_up(self) -> str:
        return format_size(self._traffic_up)

    @property
    def traffic_down(self) -> str:
        return format_size(self._traffic_down)

    @property
    def expiry_time(self) -> str:
        return format_remaining_time(self._expiry_time)

    @property
    def client_id(self) -> str | None:
        return self._client_id

    @property
    def sub_id(self) -> str | None:
        return self._sub_id

    @property
    def tg_id(self) -> int | None:
        return self._tg_id

    @property
    def flow(self) -> str | None:
        return self._flow

    @property
    def inbound_id(self) -> int | None:
        return self._inbound_id

    @property
    def config_name(self) -> str | None:
        return self._config_name

    @property
    def has_subscription_expired(self) -> bool:
        current_time = time.time() * 1000
        expired = self._expiry_time != -1 and current_time > self._expiry_time
        return expired
