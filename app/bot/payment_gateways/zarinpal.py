from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from aiogram.fsm.storage.redis import RedisStorage
from aiogram.utils.i18n import I18n
from aiogram.utils.i18n import gettext as _
from aiohttp import ClientSession, ClientTimeout
from aiohttp.web import Application, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.models import ServicesContainer, SubscriptionData
from app.bot.payment_gateways._gateway import PaymentGateway
from app.bot.utils.constants import Currency, TransactionStatus, ZARINPAL_WEBHOOK
from app.bot.utils.formatting import format_device_count, format_subscription_period
from app.bot.utils.navigation import NavSubscription
from app.config import Config
from app.db.models import PaymentGatewaySettings, Transaction

logger = logging.getLogger(__name__)


class ZarinPal(PaymentGateway):
    name = "🏦 زرین‌پال"
    currency = Currency.TOMAN
    callback = NavSubscription.PAY_ZARINPAL

    API_HOST = "https://api.zarinpal.com"
    REQUEST_PATH = "/pg/v4/payment/request.json"
    VERIFY_PATH = "/pg/v4/payment/verify.json"
    PAYMENT_HOST = "https://www.zarinpal.com"
    CUSTOM_PAYMENT_PATH = "/pg/StartPay/{authority}"

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
        self.app.router.add_get("/pg/StartPay/{authority}", self.custom_payment_redirect_handler)
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

    async def _request(self, path: str, payload: dict) -> dict:
        timeout = ClientTimeout(total=20)
        async with ClientSession(timeout=timeout) as client:
            async with client.post(
                f"{self.API_HOST}{path}",
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as response:
                body = await response.json(content_type=None)
                if response.status >= 400:
                    raise RuntimeError(f"ZarinPal HTTP {response.status}: {body}")
                return body

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
        return f"{self.PAYMENT_HOST}/pg/StartPay/{authority}"

    async def create_payment(self, data: SubscriptionData) -> str:
        amount_rial = self._to_rial(data.price)
        description = _("payment:invoice:description").format(
            devices=format_device_count(data.devices),
            duration=format_subscription_period(data.duration),
        )
        callback_url = f"{self.config.bot.DOMAIN}{ZARINPAL_WEBHOOK}"

        payload = {
            "merchant_id": self.config.zarinpal.MERCHANT_ID,
            "amount": amount_rial,
            "description": description,
            "callback_url": callback_url,
            "metadata": {
                "email": self.config.shop.EMAIL,
                "order_id": f"toonel-{data.user_id}-{data.plan_id or data.duration}",
            },
        }

        response = await self._request(self.REQUEST_PATH, payload)
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

    async def custom_payment_redirect_handler(self, request: Request) -> Response:
        authority = (request.match_info.get("authority") or "").strip()
        if not authority:
            return Response(text="شناسه پرداخت نامعتبر است.", status=400, content_type="text/plain")

        async with self.session() as session:
            base_url = await self._get_custom_payment_base_url(session)

        if not base_url:
            return Response(text="مسیر پرداخت اختصاصی فعال نیست.", status=404, content_type="text/plain")

        location = f"{self.PAYMENT_HOST}/pg/StartPay/{quote(authority, safe='')}"
        logger.info("Redirecting custom payment URL to ZarinPal: authority=%s", authority)
        return Response(status=302, headers={"Location": location})

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
                self.VERIFY_PATH,
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
