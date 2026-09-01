from __future__ import annotations

import hashlib
import hmac
import logging
import time
import uuid
from decimal import Decimal, InvalidOperation

from aiohttp import ClientSession, ClientTimeout
from aiohttp.web import Application, Request, Response
from aiogram import Bot
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.utils.i18n import I18n
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.models import ServicesContainer, SubscriptionData
from app.bot.payment_gateways._gateway import PaymentGateway
from app.bot.utils.constants import Currency, TransactionStatus
from app.config import Config
from app.db.models import PaymentGatewaySettings, Transaction

logger = logging.getLogger(__name__)


class NahanRamz(PaymentGateway):
    """NahanRamz hosted checkout integration.

    This gateway is intentionally isolated from ZarinPal/card/wallet flows.
    Secrets are read from persistent admin-managed gateway settings so the
    integration can be deployed before the merchant has an account.
    """

    name = "🪙 نهان رمز"
    currency = Currency.TOMAN
    callback = "pay_nahanramz"
    WEBHOOK_PATH = "/nahanramz"
    API_BASE_URL = "https://checkout.nahansepehr.ir"
    PAYMENT_SESSIONS_PATH = "/api/v1/payment-sessions"
    RATES_PATH = "/api/v1/rates"
    SIGNATURE_MAX_AGE_SECONDS = 300

    def __init__(
        self,
        app: Application,
        config: Config,
        session: async_sessionmaker,
        storage: RedisStorage,
        bot: Bot,
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
        self.app.router.add_post(self.WEBHOOK_PATH, self.webhook_handler)
        logger.info("NahanRamz payment gateway initialized.")

    async def _get_credentials(self) -> tuple[str | None, str | None]:
        async with self.session() as session:
            settings = await PaymentGatewaySettings.get(session)
            if settings is None:
                return None, None
            return (
                settings.nahanramz_api_key.strip() or None,
                settings.nahanramz_webhook_secret.strip() or None,
            )

    async def _request(self, method: str, path: str, api_key: str, payload: dict | None = None) -> dict:
        timeout = ClientTimeout(total=20)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with ClientSession(timeout=timeout) as client:
            async with client.request(
                method,
                f"{self.API_BASE_URL}{path}",
                json=payload,
                headers=headers,
            ) as response:
                body = await response.json(content_type=None)
                if response.status >= 400:
                    raise RuntimeError(f"NahanRamz HTTP {response.status}: {body}")
                return body

    @staticmethod
    def _validate_toman(amount: float) -> str:
        try:
            value = Decimal(str(amount))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid Toman amount: {amount}") from exc
        if value <= 0 or value != value.to_integral_value():
            raise ValueError("NahanRamz amount must be a positive whole Toman value")
        return str(int(value))

    async def create_payment(self, data: SubscriptionData) -> str:
        if data.payment_kind not in {"subscription", "wallet_topup"}:
            raise RuntimeError(f"NahanRamz is not supported for payment kind: {data.payment_kind}")

        api_key, webhook_secret = await self._get_credentials()
        if not api_key:
            raise RuntimeError("NahanRamz API key is not configured")
        if not webhook_secret:
            raise RuntimeError("NahanRamz webhook secret is not configured")

        amount = self._validate_toman(data.price)
        merchant_order_id = f"toonel-{uuid.uuid4().hex}"
        response = await self._request(
            "POST",
            self.PAYMENT_SESSIONS_PATH,
            api_key,
            {
                "merchant_order_id": merchant_order_id,
                "amount": amount,
                "currency": "IRT",
                "processing_model": "MANAGED_CUSTODIAL",
            },
        )
        checkout_url = str(response.get("checkout_url") or "").strip()
        if not checkout_url:
            raise RuntimeError(f"NahanRamz response has no checkout_url: {response}")

        async with self.session() as session:
            transaction = await Transaction.create(
                session=session,
                tg_id=data.user_id,
                subscription=data.serialize(),
                payment_id=merchant_order_id,
                status=TransactionStatus.PENDING,
            )
            if transaction is None:
                raise RuntimeError(f"Could not create NahanRamz transaction {merchant_order_id}")

        logger.info("NahanRamz payment session created: user=%s order=%s", data.user_id, merchant_order_id)
        return checkout_url

    async def handle_payment_succeeded(self, payment_id: str) -> None:
        lock = self.storage.redis.lock(
            f"payment:nahanramz:{payment_id}", timeout=300, blocking_timeout=10
        )
        async with lock:
            async with self.session() as session:
                transaction = await Transaction.get_by_id(session=session, payment_id=payment_id)
                if transaction is None:
                    raise RuntimeError(f"NahanRamz transaction {payment_id} was not found")
                if transaction.status == TransactionStatus.COMPLETED:
                    logger.info("Ignoring duplicate NahanRamz success for %s", payment_id)
                    return
                if transaction.status == TransactionStatus.CANCELED:
                    logger.warning("Ignoring success for canceled NahanRamz transaction %s", payment_id)
                    return
            await self._on_payment_succeeded(payment_id)

    async def handle_payment_canceled(self, payment_id: str) -> None:
        async with self.session() as session:
            transaction = await Transaction.get_by_id(session=session, payment_id=payment_id)
            if transaction is None:
                raise RuntimeError(f"NahanRamz transaction {payment_id} was not found")
            if transaction.status == TransactionStatus.COMPLETED:
                logger.info("Ignoring cancellation for completed NahanRamz transaction %s", payment_id)
                return
        await self._on_payment_canceled(payment_id)

    @classmethod
    def _verify_signature(cls, raw_body: bytes, signature: str, secret: str, timestamp: str) -> bool:
        try:
            ts = int(timestamp)
        except (TypeError, ValueError):
            return False
        if abs(int(time.time()) - ts) > cls.SIGNATURE_MAX_AGE_SECONDS:
            return False
        expected = "sha256=" + hmac.new(
            secret.encode("utf-8"), raw_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(signature.strip(), expected)

    async def webhook_handler(self, request: Request) -> Response:
        raw_body = await request.read()
        signature = request.headers.get("X-Checkout-Signature", "")
        timestamp = request.headers.get("X-Checkout-Timestamp", "")
        environment = (request.headers.get("X-Checkout-Environment") or "").lower()
        event = (request.headers.get("X-Checkout-Event") or "").strip()
        delivery_id = (request.headers.get("X-Checkout-Delivery") or "").strip()

        _, webhook_secret = await self._get_credentials()
        if not webhook_secret:
            logger.error("NahanRamz webhook rejected: secret is not configured")
            return Response(text="webhook is not configured", status=503)
        if not self._verify_signature(raw_body, signature, webhook_secret, timestamp):
            logger.warning("NahanRamz webhook rejected: invalid signature/replay")
            return Response(text="invalid signature", status=401)

        try:
            import json
            payload = json.loads(raw_body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return Response(text="invalid json", status=400)

        if event == "webhook.test":
            logger.info("NahanRamz webhook test received: delivery=%s", delivery_id)
            return Response(text="ok", status=200)

        # Sandbox events must never provision a real service.
        if environment != "live" or payload.get("livemode") is not True:
            logger.info(
                "Ignoring non-live NahanRamz webhook: event=%s environment=%s delivery=%s",
                event, environment, delivery_id,
            )
            return Response(text="ok", status=200)

        payment = payload.get("payment") or {}
        merchant_order_id = str(payment.get("merchant_order_id") or "").strip()
        status = str(payment.get("status") or "").upper()
        if not merchant_order_id:
            logger.warning("NahanRamz webhook has no merchant_order_id")
            return Response(text="ok", status=200)

        try:
            if event == "payment.confirmed" and status == "CONFIRMED":
                await self.handle_payment_succeeded(merchant_order_id)
            elif event in {"payment.expired", "payment.failed", "payment.create_failed"}:
                await self.handle_payment_canceled(merchant_order_id)
            elif event == "payment.review_required":
                logger.warning(
                    "NahanRamz payment requires review: order=%s delivery=%s",
                    merchant_order_id, delivery_id,
                )
            return Response(text="ok", status=200)
        except Exception:
            logger.exception(
                "NahanRamz webhook processing failed: event=%s order=%s delivery=%s",
                event, merchant_order_id, delivery_id,
            )
            return Response(text="retry", status=500)

    async def test_connection(self) -> dict:
        api_key, webhook_secret = await self._get_credentials()
        if not api_key:
            raise RuntimeError("API Key تنظیم نشده است")
        if not webhook_secret:
            raise RuntimeError("Webhook Secret تنظیم نشده است")
        return await self._request("GET", self.RATES_PATH, api_key)
