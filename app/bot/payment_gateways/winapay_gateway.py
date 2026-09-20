from __future__ import annotations

import hashlib
import html
import logging
import os
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlencode

from aiohttp import ClientSession, ClientTimeout
from aiohttp.web import Application, Request, Response
from aiogram import Bot
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.utils.i18n import I18n
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.models import ServicesContainer, SubscriptionData
from app.bot.payment_gateways._gateway import PaymentGateway
from app.bot.utils.constants import Currency, TransactionStatus
from app.config import Config
from app.db.models import Transaction

logger = logging.getLogger(__name__)


class WinapayGateway(PaymentGateway):
    """Independent Winapay REST payment provider."""

    name = "💳 پرداخت در ویناپی"
    currency = Currency.TOMAN
    callback = "pay_winapay"
    WEBHOOK_PATH = "/webhooks/winapay"
    PAYMENT_REQUEST_URL = "https://winapay.io/webservice/rest/PaymentRequest"
    PAYMENT_VERIFY_URL = "https://winapay.io/webservice/rest/PaymentVerification"
    PAYMENT_START_URL = "https://winapay.io/startPay"

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
        super().__init__(app, config, session, storage, bot, i18n, services)
        self.merchant_id = os.getenv("WINAPAY_MERCHANT_ID", "").strip()
        self.callback_url = f"{self.config.bot.DOMAIN.rstrip('/')}{self.WEBHOOK_PATH}"
        self.app.router.add_post(self.WEBHOOK_PATH, self.callback_handler)
        logger.info("Winapay payment gateway initialized.")

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("WINAPAY_MERCHANT_ID", "").strip())

    @staticmethod
    def _to_toman(amount: float | int | Decimal) -> int:
        try:
            value = Decimal(str(amount))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid Toman amount: {amount}") from exc
        if value <= 0:
            raise ValueError("Payment amount must be positive")
        if value != value.to_integral_value():
            raise ValueError("Payment amount must be a whole Toman amount")
        return int(value)

    async def _request(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        # Winapay's published examples send form-encoded fields while declaring
        # application/json. Keep that wire format for compatibility, but retain
        # normal TLS certificate verification in Production.
        body = urlencode({key: str(value) for key, value in payload.items() if value is not None})
        async with ClientSession(timeout=ClientTimeout(total=30)) as client:
            async with client.post(
                url,
                data=body,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            ) as response:
                result = await response.json(content_type=None)
                if not isinstance(result, dict):
                    raise RuntimeError(f"Winapay returned an invalid response: HTTP {response.status}")
                if response.status >= 400:
                    raise RuntimeError(
                        f"Winapay request failed: HTTP {response.status}, status={result.get('Status')}"
                    )
                return result

    @staticmethod
    def _status(result: dict[str, Any]) -> int | None:
        try:
            return int(result.get("Status"))
        except (TypeError, ValueError):
            return None

    @classmethod
    def _verify_success(cls, result: dict[str, Any], expected_amount: int) -> bool:
        status = cls._status(result)
        if status not in {100, 101}:
            return False
        remote_amount = result.get("Amount")
        if remote_amount not in (None, ""):
            try:
                if int(remote_amount) != expected_amount:
                    raise RuntimeError(
                        f"Winapay verification amount mismatch: expected={expected_amount}, remote={remote_amount}"
                    )
            except (TypeError, ValueError) as exc:
                raise RuntimeError("Winapay returned an invalid verified amount") from exc
        return True

    async def _find_pending_transaction(self, data: SubscriptionData) -> Transaction | None:
        serialized = data.serialize()
        async with self.session() as db:
            result = await db.execute(
                select(Transaction)
                .where(
                    Transaction.tg_id == data.user_id,
                    Transaction.status == TransactionStatus.PENDING,
                    Transaction.subscription == serialized,
                    Transaction.gateway == "winapay",
                )
                .order_by(Transaction.created_at.desc())
            )
            return result.scalars().first()

    async def create_payment(self, data: SubscriptionData) -> str:
        if not self.is_configured():
            raise RuntimeError("Winapay is not configured")

        amount = self._to_toman(data.price)
        if amount < 100:
            raise ValueError("Winapay minimum payment amount is 100 Toman")

        order_key = hashlib.sha256(data.serialize().encode("utf-8")).hexdigest()
        lock = self.storage.redis.lock(
            f"payment:winapay:create:{data.user_id}:{order_key}",
            timeout=180,
            blocking_timeout=10,
        )
        async with lock:
            existing = await self._find_pending_transaction(data)
            if existing is not None:
                return f"{self.PAYMENT_START_URL}/{existing.payment_id}"

            invoice_id = uuid.uuid4().hex
            description = "پرداخت سفارش ToonelVPN"
            if data.payment_kind == "wallet_topup":
                description = "شارژ کیف پول ToonelVPN"
            elif data.is_extend:
                description = "تمدید سرویس ToonelVPN"

            result = await self._request(
                self.PAYMENT_REQUEST_URL,
                {
                    "MerchantID": self.merchant_id,
                    "Amount": amount,
                    "InvoiceID": invoice_id,
                    "Description": description,
                    "CallbackURL": self.callback_url,
                },
            )

            if self._status(result) != 100:
                raise RuntimeError(f"Winapay payment request failed: status={result.get('Status')}")

            authority = str(result.get("Authority") or "").strip()
            payment_url = str(result.get("PaymentUrl") or "").strip()
            if not authority or not payment_url:
                raise RuntimeError("Winapay returned an incomplete payment request")

            async with self.session() as db:
                transaction = await Transaction.create(
                    session=db,
                    tg_id=data.user_id,
                    subscription=data.serialize(),
                    payment_id=authority,
                    gateway="winapay",
                    status=TransactionStatus.PENDING,
                )
                if transaction is None:
                    raise RuntimeError(f"Could not create ToonelVPN transaction for Winapay {authority}")

            logger.info(
                "Winapay payment created: authority=%s invoice_id=%s user=%s amount_toman=%s",
                authority,
                invoice_id,
                data.user_id,
                amount,
            )
            return payment_url

    async def handle_payment_succeeded(self, payment_id: str) -> None:
        lock = self.storage.redis.lock(
            f"payment:winapay:{payment_id}",
            timeout=180,
            blocking_timeout=10,
        )
        async with lock:
            async with self.session() as db:
                transaction = await Transaction.get_by_id(session=db, payment_id=payment_id)
                if transaction is None:
                    raise RuntimeError(f"Winapay transaction {payment_id} was not found")
                if transaction.gateway != "winapay":
                    raise RuntimeError(f"Payment {payment_id} does not belong to Winapay")
                if transaction.status == TransactionStatus.COMPLETED:
                    return
                if transaction.status == TransactionStatus.CANCELED:
                    logger.warning("Ignoring success for canceled Winapay transaction %s", payment_id)
                    return
                data = SubscriptionData.deserialize(transaction.subscription)

            amount = self._to_toman(data.price)
            result = await self._request(
                self.PAYMENT_VERIFY_URL,
                {
                    "MerchantID": self.merchant_id,
                    "Amount": amount,
                    "Authority": payment_id,
                },
            )
            if not self._verify_success(result, amount):
                raise RuntimeError(
                    f"Winapay verification failed: authority={payment_id}, status={result.get('Status')}"
                )

            logger.info(
                "Winapay payment verified: authority=%s status=%s ref_id=%s",
                payment_id,
                result.get("Status"),
                result.get("RefID"),
            )
            await self._on_payment_succeeded(payment_id)

    async def handle_payment_canceled(self, payment_id: str) -> None:
        await self._on_payment_canceled(payment_id)

    async def callback_handler(self, request: Request) -> Response:
        try:
            payload = await request.post()
            payment_status = str(payload.get("PaymentStatus") or "").strip().upper()
            authority = str(payload.get("Authority") or "").strip()
        except Exception:
            logger.exception("Failed to parse Winapay callback")
            return Response(status=400, text="invalid callback")

        if not authority:
            return Response(status=400, text="missing authority")

        try:
            async with self.session() as db:
                transaction = await Transaction.get_by_id(session=db, payment_id=authority)
                if transaction is None or transaction.gateway != "winapay":
                    return Response(status=404, text="unknown transaction")
                if transaction.status == TransactionStatus.COMPLETED:
                    return self._success_response(authority)

            if payment_status == "NOK":
                await self.handle_payment_canceled(authority)
                return Response(
                    status=200,
                    content_type="text/html",
                    charset="utf-8",
                    text="<html lang='fa' dir='rtl'><body><h3>پرداخت لغو شد.</h3><p>می‌توانید به ربات ToonelVPN بازگردید.</p></body></html>",
                )

            if payment_status != "OK":
                return Response(status=400, text="invalid payment status")

            await self.handle_payment_succeeded(authority)
            return self._success_response(authority)
        except Exception:
            logger.exception("Failed to process Winapay callback authority=%s", authority)
            return Response(status=500, text="processing failed")

    @staticmethod
    def _success_response(authority: str) -> Response:
        return Response(
            status=200,
            content_type="text/html",
            charset="utf-8",
            text=(
                "<!doctype html><html lang='fa' dir='rtl'><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>پرداخت ToonelVPN</title></head><body style='font-family:system-ui;text-align:center;padding:40px'>"
                "<h2>✅ پرداخت با موفقیت تأیید شد.</h2>"
                f"<p>شماره مرجع: <code>{html.escape(authority)}</code></p>"
                "<p>نتیجه پرداخت در ToonelVPN ثبت شد. می‌توانید به ربات بازگردید.</p>"
                "<p><a href='https://t.me/ToonelVpn_bot'>بازگشت به ربات</a></p>"
                "</body></html>"
            ),
        )
