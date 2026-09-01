from aiogram import Bot
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.utils.i18n import I18n
from aiohttp.web import Application
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.models import ServicesContainer
from app.config import Config

from ._gateway import PaymentGateway
from .kpay import KPay
from .nahanramz import NahanRamz
from .zarinpal import ZarinPal


class GatewayFactory:
    def __init__(self) -> None:
        self._gateways: dict[str, PaymentGateway] = {}

    def register_gateway(self, gateway: PaymentGateway) -> None:
        callback = gateway.callback
        if hasattr(callback, "value"):
            gateway.callback = callback.value
        self._gateways[gateway.callback] = gateway

    def get_gateway(self, name: str) -> PaymentGateway:
        gateway = self._gateways.get(name)
        if not gateway:
            raise ValueError(f"Gateway {name} is not registered.")
        return gateway

    def get_gateways(self) -> list[PaymentGateway]:
        return list(self._gateways.values())

    def register_gateways(
        self,
        app: Application,
        config: Config,
        session: async_sessionmaker,
        storage: RedisStorage,
        bot: Bot,
        i18n: I18n,
        services: ServicesContainer,
    ) -> None:
        dependencies = [app, config, session, storage, bot, i18n, services]

        if config.shop.PAYMENT_ZARINPAL_ENABLED:
            self.register_gateway(ZarinPal(*dependencies))

        # Keep NahanRamz registered before credentials exist so the admin UI
        # can configure it without a code or .env change. The customer payment
        # method remains disabled until the admin enables it.
        self.register_gateway(NahanRamz(*dependencies))

        # KPay is independently configurable from the admin panel. Its payment
        # method is disabled by default until API key/shop/card are configured.
        self.register_gateway(KPay(*dependencies))
