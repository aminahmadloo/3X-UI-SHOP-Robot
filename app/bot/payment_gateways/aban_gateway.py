from __future__ import annotations

import hashlib
import hmac
import logging
import os
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

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
from app.db.models import Transaction

logger = logging.getLogger(__name__)


class AbanGateway(PaymentGateway):
    name = "💳 پرداخت خودکار کارت به کارت"
    currency = Currency.TOMAN
    callback = "pay_aban"
    WEBHOOK_PATH = "/webhooks/aban-gateway"
    DEFAULT_API_BASE_URL = "https://abangateway.ir/api/v1"
    EXPIRY_MINUTES = 10

    def __init__(self, app: Application, config: Config, session: async_sessionmaker,
                 storage: RedisStorage, bot: Bot, i18n: I18n,
                 services: ServicesContainer) -> None:
        super().__init__(app, config, session, storage, bot, i18n, services)
        self.api_base_url = os.getenv("ABAN_GATEWAY_API_BASE_URL", self.DEFAULT_API_BASE_URL).strip().rstrip("/")
        self.token = os.getenv("ABAN_GATEWAY_TOKEN", "").strip()
        self.webhook_secret = os.getenv("ABAN_GATEWAY_WEBHOOK_SECRET", "").strip()
        self.webhook_url = f"{self.config.bot.DOMAIN.rstrip('/')}{self.WEBHOOK_PATH}"
        self.app.router.add_post(self.WEBHOOK_PATH, self.callback_handler)
        logger.info("AbanGateway payment gateway initialized.")

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("ABAN_GATEWAY_TOKEN", "").strip() and
                    os.getenv("ABAN_GATEWAY_WEBHOOK_SECRET", "").strip())

    @staticmethod
    def _to_rial(amount_toman: float | int | Decimal) -> int:
        try:
            amount = Decimal(str(amount_toman))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid Toman amount: {amount_toman}") from exc
        if amount <= 0:
            raise ValueError("Payment amount must be positive")
        rial = amount * Decimal("10")
        if rial != rial.to_integral_value():
            raise ValueError("Payment amount must resolve to whole Rials")
        return int(rial)

    def _headers(self) -> dict[str, str]:
        if not self.token:
            raise RuntimeError("ABAN_GATEWAY_TOKEN is not configured")
        return {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json", "Accept": "application/json"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        async with ClientSession(timeout=ClientTimeout(total=20)) as client:
            async with client.request(method, f"{self.api_base_url}{path}", headers=self._headers(), **kwargs) as response:
                body = await response.json(content_type=None)
                return response.status, body if isinstance(body, dict) else {"raw": body}

    @staticmethod
    def _error_code(body: dict[str, Any]) -> str:
        error = body.get("error")
        return str(error.get("code", "")) if isinstance(error, dict) else ""

    async def create_payment(self, data: SubscriptionData) -> str:
        if not self.is_configured():
            raise RuntimeError("AbanGateway is not configured")
        amount_rial = self._to_rial(data.price)
        order_id = f"toonel-{uuid.uuid4().hex}"
        payload = {
            "amount_rial": amount_rial,
            "order_id": order_id,
            "callback_url": self.webhook_url,
            "description": "پرداخت سفارش ToonelVPN",
            "metadata": {"user_id": data.user_id, "payment_kind": data.payment_kind, "plan_id": data.plan_id},
            "expiry_minutes": self.EXPIRY_MINUTES,
        }
        status, response = await self._request("POST", "/invoices", json=payload)
        if status != 201:
            raise RuntimeError(f"AbanGateway invoice creation failed: HTTP {status}, code={self._error_code(response)}")
        invoice_id = str(response.get("invoice_id") or "").strip()
        payment_url = str(response.get("payment_url") or "").strip()
        if not invoice_id or not payment_url:
            raise RuntimeError("AbanGateway returned an incomplete invoice")
        async with self.session() as db:
            transaction = await Transaction.create(session=db, tg_id=data.user_id, subscription=data.serialize(),
                                                    payment_id=invoice_id, status=TransactionStatus.PENDING)
            if transaction is None:
                await self._cancel_invoice(invoice_id)
                raise RuntimeError(f"Could not create ToonelVPN transaction for {invoice_id}")
        logger.info("AbanGateway invoice created: %s payable_rial=%s", invoice_id, response.get("payable_rial"))
        return payment_url

    async def _cancel_invoice(self, invoice_id: str) -> None:
        try:
            status, body = await self._request("POST", f"/invoices/{invoice_id}/cancel")
            if status not in (200, 409):
                logger.warning("AbanGateway invoice cancel failed: %s %s", status, body)
        except Exception:
            logger.exception("Failed to cancel AbanGateway invoice %s", invoice_id)

    async def _verify_invoice(self, invoice_id: str) -> bool:
        status, body = await self._request("POST", f"/invoices/{invoice_id}/verify")
        if status == 200 and body.get("verified") is True:
            return True
        if status == 409 and self._error_code(body) == "already_verified":
            return False
        raise RuntimeError(f"AbanGateway verification failed: HTTP {status}, code={self._error_code(body)}")

    async def handle_payment_succeeded(self, payment_id: str) -> None:
        lock = self.storage.redis.lock(f"payment:aban:{payment_id}", timeout=180, blocking_timeout=10)
        async with lock:
            async with self.session() as db:
                transaction = await Transaction.get_by_id(session=db, payment_id=payment_id)
                if transaction is None:
                    raise RuntimeError(f"AbanGateway transaction {payment_id} was not found")
                if transaction.status == TransactionStatus.COMPLETED:
                    return
                if transaction.status == TransactionStatus.CANCELED:
                    logger.warning("Ignoring success for canceled AbanGateway transaction %s", payment_id)
                    return
            if not await self._verify_invoice(payment_id):
                logger.info("AbanGateway invoice %s was already verified; no duplicate delivery.", payment_id)
                return
            await self._on_payment_succeeded(payment_id)

    async def handle_payment_canceled(self, payment_id: str) -> None:
        async with self.session() as db:
            transaction = await Transaction.get_by_id(session=db, payment_id=payment_id)
            if transaction is None:
                logger.warning("AbanGateway cancellation for unknown invoice %s", payment_id)
                return
            if transaction.status == TransactionStatus.COMPLETED:
                return
        await self._on_payment_canceled(payment_id)

    def _valid_signature(self, raw_body: bytes, signature: str) -> bool:
        if not self.webhook_secret or not signature:
            return False
        expected = hmac.new(self.webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.strip())

    async def callback_handler(self, request: Request) -> Response:
        raw_body = await request.read()
        if not self._valid_signature(raw_body, request.headers.get("X-Signature", "")):
            logger.warning("Rejected AbanGateway webhook with invalid signature")
            return Response(status=400, text="invalid signature")
        try:
            payload = await request.json()
        except Exception:
            return Response(status=400, text="invalid json")
        if not isinstance(payload, dict):
            return Response(status=400, text="invalid payload")
        event = str(payload.get("event") or request.headers.get("X-Event") or "").strip()
        invoice_id = str(payload.get("invoice_id") or "").strip()
        if not invoice_id:
            return Response(status=400, text="missing invoice_id")
        try:
            if event == "invoice.paid":
                await self.handle_payment_succeeded(invoice_id)
            elif event in {"invoice.expired", "invoice.cancelled"}:
                await self.handle_payment_canceled(invoice_id)
            elif event == "invoice.partially_paid":
                logger.info("AbanGateway invoice %s is partially paid.", invoice_id)
            else:
                logger.info("Ignoring unknown AbanGateway event %s for %s", event, invoice_id)
        except Exception:
            logger.exception("Failed to process AbanGateway webhook %s", invoice_id)
            return Response(status=500, text="processing failed")
        return Response(status=200, text="ok")
