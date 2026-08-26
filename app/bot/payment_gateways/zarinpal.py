from __future__ import annotations

import logging
import ssl
import certifi
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from aiogram.fsm.storage.redis import RedisStorage
from aiogram.utils.i18n import I18n
from aiogram.utils.i18n import gettext as _
from aiohttp import ClientSession, ClientTimeout, TCPConnector
from aiohttp.web import Application, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.models import ServicesContainer, SubscriptionData
from app.bot.payment_gateways._gateway import PaymentGateway
from app.bot.utils.constants import Currency, TransactionStatus, ZARINPAL_WEBHOOK
from app.bot.utils.formatting import format_device_count, format_subscription_period
from app.bot.utils.navigation import NavSubscription
from app.config import Config
from app.db.models import PaymentGatewaySettings, ServicePurchasePlan, Transaction

logger = logging.getLogger(__name__)


class ZarinPal(PaymentGateway):
    name = "🏦 زرین‌پال"
    currency = Currency.TOMAN
    callback = NavSubscription.PAY_ZARINPAL
    CUSTOM_PAYMENT_PATH = "/pg/checkout/{authority}"

    def __init__(
        self,
        app: Application,
        config: Config,
        session: async_sessionmaker,
        storage: RedisStorage,
        bot,
        i18n: I18n,
        services: ServicesContainer,
    ) -> None:
        self.app = app
        self.config = config
        self.session = session
        self.storage = storage
        self.bot = bot
        self.i18n = i18n
        self.services = services

        self.app.router.add_get(ZARINPAL_WEBHOOK, self.callback_handler)
        logger.info("ZarinPal payment gateway initialized.")

    @staticmethod
    def _to_rial(amount_toman: float) -> int:
        try:
            amount = Decimal(str(amount_toman))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid Toman amount: {amount_toman}") from exc

        if amount <= 0:
            raise ValueError("Payment amount must be positive")

        rial = amount * Decimal("10")
        if rial != rial.to_integral_value():
            raise ValueError(f"Payment amount must resolve to whole Rials: {amount_toman}")
        return int(rial)

    async def _get_custom_payment_base_url(self, session: AsyncSession) -> str | None:
        settings = await PaymentGatewaySettings.get(session)
        if settings and settings.zarinpal_payment_base_url_configured:
            base_url = settings.zarinpal_payment_base_url.strip().rstrip("/")
            return base_url or None
        return self.config.zarinpal.PAYMENT_BASE_URL

    async def _build_payment_url(self, authority: str) -> str:
        async with self.session() as session:
            base_url = await self._get_custom_payment_base_url(session)

        if base_url:
            return f"{base_url}{self.CUSTOM_PAYMENT_PATH.format(authority=quote(authority, safe=''))}"
        return f"{self.config.zarinpal.DIRECT_PAYMENT_BASE_URL}/pg/StartPay/{authority}"

    async def _request(self, path: str, payload: dict) -> dict:
        timeout = ClientTimeout(total=self.config.zarinpal.HTTP_TIMEOUT)

        # Use certifi explicitly because the Debian 11 container's
        # system CA store is not being loaded correctly by Python/OpenSSL.
        # Certificate verification remains fully enabled.
        ssl_context = ssl.create_default_context(
            cafile=certifi.where()
        )
        connector = TCPConnector(ssl=ssl_context)

        async with ClientSession(
            timeout=timeout,
            connector=connector,
        ) as client:
            async with client.post(
                f"{self.config.zarinpal.API_BASE_URL}{path}",
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                body = await response.json(content_type=None)
                if response.status >= 400:
                    raise RuntimeError(f"ZarinPal HTTP {response.status}: {body}")
                return body

    async def create_payment(self, data: SubscriptionData) -> str:
        # Only these payment kinds may use the bank gateway:
        # normal service purchase, the dedicated main-menu renewal flow,
        # and wallet top-up. Dynamic time/traffic add-ons are intentionally
        # excluded so their payment logic cannot accidentally reuse this flow.
        if data.payment_kind not in {"subscription", "wallet_topup"}:
            raise RuntimeError(f"Unsupported ZarinPal payment kind: {data.payment_kind}")

        if data.is_extend:
            async with self.session() as session:
                plan = await ServicePurchasePlan.get(session, data.plan_id)
            if plan is None or plan.volume_gb <= 0 or plan.duration_days <= 0:
                raise RuntimeError("ZarinPal is available only for full service renewal plans.")

        amount_rial = self._to_rial(data.price)
        description = "پرداخت سفارش"
        callback_url = f"{self.config.bot.DOMAIN}{ZARINPAL_WEBHOOK}"

        payload = {
            "merchant_id": self.config.zarinpal.MERCHANT_ID,
            "amount": amount_rial,
            "description": description,
            "callback_url": callback_url,
            "metadata": {
                "order_id": f"toonel-{data.user_id}-{data.plan_id or data.duration}",
            },
        }

        response = await self._request(self.config.zarinpal.REQUEST_PATH, payload)
        errors = response.get("errors") or []
        result = response.get("data") or {}
        code = result.get("code")

        if errors or code != 100 or not result.get("authority"):
            raise RuntimeError(f"ZarinPal payment request failed: errors={errors}, data={result}")

        authority = str(result["authority"])

        async with self.session() as session:
            transaction = await Transaction.create(
                session=session,
                tg_id=data.user_id,
                subscription=data.serialize(),
                payment_id=authority,
                status=TransactionStatus.PENDING,
            )
            if transaction is None:
                raise RuntimeError(f"Could not create ZarinPal transaction for authority {authority}")

        pay_url = await self._build_payment_url(authority)
        logger.info("ZarinPal payment link created for user %s: %s", data.user_id, authority)
        return pay_url

    async def handle_payment_succeeded(self, payment_id: str) -> None:
        lock = self.storage.redis.lock(
            f"payment:zarinpal:{payment_id}",
            timeout=180,
            blocking_timeout=10,
        )
        async with lock:
            async with self.session() as session:
                transaction = await Transaction.get_by_id(session=session, payment_id=payment_id)
                if transaction is None:
                    raise RuntimeError(f"ZarinPal transaction {payment_id} was not found")
                if transaction.status == TransactionStatus.COMPLETED:
                    logger.info("ZarinPal transaction %s was already completed; ignoring duplicate callback.", payment_id)
                    return
                if transaction.status == TransactionStatus.CANCELED:
                    logger.warning("Ignoring success callback for canceled ZarinPal transaction %s", payment_id)
                    return

                data = SubscriptionData.deserialize(transaction.subscription)
                amount_rial = self._to_rial(data.price)

            response = await self._request(
                self.config.zarinpal.VERIFY_PATH,
                {
                    "merchant_id": self.config.zarinpal.MERCHANT_ID,
                    "amount": amount_rial,
                    "authority": payment_id,
                },
            )
            errors = response.get("errors") or []
            result = response.get("data") or {}
            code = result.get("code")

            if errors and code not in (100, 101):
                raise RuntimeError(f"ZarinPal verification failed: errors={errors}, data={result}")
            if code not in (100, 101):
                raise RuntimeError(f"ZarinPal verification failed: data={result}")

            logger.info(
                "ZarinPal payment verified: authority=%s ref_id=%s code=%s",
                payment_id,
                result.get("ref_id"),
                code,
            )
            await self._on_payment_succeeded(payment_id)

    async def handle_payment_canceled(self, payment_id: str) -> None:
        async with self.session() as session:
            transaction = await Transaction.get_by_id(session=session, payment_id=payment_id)
            if transaction is None:
                raise RuntimeError(f"ZarinPal transaction {payment_id} was not found")
            if transaction.status == TransactionStatus.COMPLETED:
                logger.info("Ignoring cancellation callback for completed ZarinPal transaction %s", payment_id)
                return

        await self._on_payment_canceled(payment_id)

    async def _redirect_to_bot(self) -> Response:
        bot_username = (await self.bot.get_me()).username
        if bot_username:
            return Response(status=302, headers={"Location": f"https://t.me/{bot_username}"})
        return Response(text="بازگشت به ربات انجام شد.", content_type="text/plain")

    async def callback_handler(self, request: Request) -> Response:
        status = (request.query.get("Status") or "").upper()
        authority = (request.query.get("Authority") or "").strip()

        if not authority:
            return Response(text="شناسه تراکنش نامعتبر است.", status=400, content_type="text/plain")

        try:
            if status != "OK":
                await self.handle_payment_canceled(authority)
                return await self._redirect_to_bot()

            await self.handle_payment_succeeded(authority)
            return await self._redirect_to_bot()
        except Exception as exc:
            logger.exception("Error processing ZarinPal callback for %s: %s", authority, exc)
            return Response(
                text="پرداخت دریافت شد، اما پردازش آن با خطا مواجه شد. لطفاً چند لحظه بعد وضعیت سرویس خود را بررسی کنید.",
                status=500,
                content_type="text/plain",
            )
