from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

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
from app.db.models import Transaction, User

logger = logging.getLogger(__name__)


class BluPalPaymentURL(str):
    """
    Payment URL that behaves exactly like str while carrying
    the numeric BluPal invoice_id required by the lookup API.
    """

    def __new__(cls, url: str, invoice_id: str | int):
        obj = str.__new__(cls, url)
        obj.invoice_id = str(invoice_id)
        return obj


class BluPalGateway(PaymentGateway):
    """Independent BluPal card-to-card provider.

    BluPal has no documented webhook signature. The webhook is therefore only
    a wake-up signal: the invoice is re-fetched from BluPal and only a verified
    PAID status with matching amounts is accepted.
    """

    name = "💳 کارت به کارت هوشمند بلوپال"
    currency = Currency.TOMAN
    callback = "pay_blupal"
    WEBHOOK_PATH = "/webhooks/blupal"
    RETURN_PATH = "/back"
    DEFAULT_API_BASE_URL = "https://blupal.net/api"
    DEFAULT_PAYMENT_BASE_URL = "https://blupal.net/payment"

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
        self.api_base_url = os.getenv("BLUPAL_API_BASE_URL", self.DEFAULT_API_BASE_URL).strip().rstrip("/")
        self.payment_base_url = os.getenv("BLUPAL_PAYMENT_BASE_URL", self.DEFAULT_PAYMENT_BASE_URL).strip().rstrip("/")
        self.api_key = os.getenv("BLUPAL_API_KEY", "").strip()
        self.webhook_url = f"{self.config.bot.DOMAIN.rstrip('/')}{self.WEBHOOK_PATH}"
        self.app.router.add_post(self.WEBHOOK_PATH, self.callback_handler)
        self.app.router.add_get(self.RETURN_PATH, self.return_handler)
        logger.info("BluPal payment gateway initialized.")

    @classmethod
    def is_configured(cls) -> bool:
        return bool(os.getenv("BLUPAL_API_KEY", "").strip())

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
        if not self.api_key:
            raise RuntimeError("BLUPAL_API_KEY is not configured")
        return {
            "X-API-Key": self.api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(self, method: str, path: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        async with ClientSession(timeout=ClientTimeout(total=20)) as client:
            async with client.request(
                method,
                f"{self.api_base_url}{path}",
                headers=self._headers(),
                **kwargs,
            ) as response:
                body = await response.json(content_type=None)
                return response.status, body if isinstance(body, dict) else {"raw": body}

    @staticmethod
    def _error_code(body: dict[str, Any]) -> str:
        return str(body.get("error") or "")

    async def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        """
        Fetch BluPal invoice.

        BluPal payment links contain a public token,
        but invoice lookup API requires numeric invoice_id.
        """

        invoice_id = str(invoice_id).strip()

        if not invoice_id.isdigit():
            logger.warning(
                "BluPal invalid invoice id received: %s",
                invoice_id,
            )
            raise RuntimeError(
                f"BluPal invalid invoice id format: {invoice_id}"
            )

        last_status = 0
        last_body: dict[str, Any] = {}

        for attempt in range(3):
            status, body = await self._request("GET", f"/v1/invoices/{invoice_id}")
            last_status = status
            last_body = body
            if status == 200 and body.get("success") is not False:
                return body

            transient = status == 404 or 500 <= status < 600
            if not transient or attempt == 2:
                break

            delay = 0.35 * (attempt + 1)
            logger.info(
                "BluPal invoice lookup retry: invoice=%s status=%s attempt=%s delay=%.2fs",
                invoice_id,
                status,
                attempt + 1,
                delay,
            )
            await asyncio.sleep(delay)

        raise RuntimeError(
            f"BluPal invoice lookup failed: HTTP {last_status}, code={self._error_code(last_body)}"
        )

    async def _find_pending_transaction(self, data: SubscriptionData) -> Transaction | None:
        serialized = data.serialize()
        async with self.session() as db:
            result = await db.execute(
                select(Transaction)
                .where(
                    Transaction.tg_id == data.user_id,
                    Transaction.status == TransactionStatus.PENDING,
                    Transaction.subscription == serialized,
                    Transaction.gateway == "blupal",
                )
                .order_by(Transaction.created_at.desc())
            )
            return result.scalars().first()

    async def _reconcile_existing_invoice(self, transaction: Transaction) -> str | None:
        invoice = await self.get_invoice(transaction.payment_id)
        remote_status = str(invoice.get("status") or "").strip().upper()
        if remote_status == "PAID":
            await self._verify_invoice_matches_transaction(transaction, invoice)
            await self.handle_payment_succeeded(transaction.payment_id)
            return self._payment_url(transaction.payment_id, invoice)
        if remote_status in {"EXPIRED", "CANCELED"}:
            async with self.session() as db:
                await Transaction.update(
                    session=db,
                    payment_id=transaction.payment_id,
                    status=TransactionStatus.CANCELED,
                )
            return None
        if remote_status == "PENDING":
            return self._payment_url(transaction.payment_id, invoice)
        raise RuntimeError(f"Unknown BluPal invoice status: {remote_status or 'missing'}")

    def _payment_url(self, invoice_id: str | int, invoice: dict[str, Any]) -> str:
        """
        Return the public BluPal payment URL while preserving the
        numeric invoice_id needed for subsequent invoice lookup.
        """

        invoice_id = str(invoice_id).strip()

        payment_link = str(
            invoice.get("payment_link")
            or invoice.get("url")
            or ""
        ).strip()

        public_token = str(
            invoice.get("public_token")
            or invoice.get("token")
            or ""
        ).strip()

        if payment_link:
            return BluPalPaymentURL(payment_link, invoice_id)

        if public_token:
            return BluPalPaymentURL(f"{self.payment_base_url}/{quote(public_token)}", invoice_id)

        raise RuntimeError("BluPal invoice did not contain a usable payment_link/public_token")

    async def _verify_invoice_matches_transaction(
        self,
        transaction: Transaction,
        invoice: dict[str, Any],
    ) -> None:
        remote_amount = invoice.get("amount")
        if remote_amount is None:
            raise RuntimeError("BluPal invoice amount is missing")

        expected_rial = self._to_rial(transaction.amount)
        try:
            actual_rial = int(Decimal(str(remote_amount)))
        except (InvalidOperation, ValueError) as exc:
            raise RuntimeError(f"BluPal invoice amount is invalid: {remote_amount}") from exc

        if actual_rial != expected_rial:
            raise RuntimeError(
                f"BluPal invoice amount mismatch: expected={expected_rial} actual={actual_rial}"
            )

    async def create_payment(self, data: SubscriptionData) -> str:
        transaction = await self._find_pending_transaction(data)
        if transaction is not None:
            try:
                return await self._reconcile_existing_invoice(transaction) or ""
            except Exception:
                logger.exception(
                    "BluPal existing pending transaction reconciliation failed: payment_id=%s",
                    transaction.payment_id,
                )
                return ""

        amount_rial = self._to_rial(data.amount)
        payload = {
            "amount": amount_rial,
            "description": f"ToonelVPN TG:{data.user_id}",
            "callback_url": f"{self.config.bot.DOMAIN.rstrip('/')}{self.RETURN_PATH}",
        }
        status, body = await self._request("POST", "/v1/invoices", json=payload)
        if status < 200 or status >= 300 or body.get("success") is False:
            raise RuntimeError(
                f"BluPal invoice creation failed: HTTP {status}, code={self._error_code(body)}"
            )

        invoice = body.get("data") if isinstance(body.get("data"), dict) else body
        invoice_id = invoice.get("invoice_id") or invoice.get("id")
        if invoice_id is None:
            raise RuntimeError("BluPal invoice creation response did not contain invoice_id")

        payment_url = self._payment_url(invoice_id, invoice)
        async with self.session() as db:
            await Transaction.create(
                session=db,
                tg_id=data.user_id,
                amount=data.amount,
                currency=self.currency,
                status=TransactionStatus.PENDING,
                payment_id=str(invoice_id),
                subscription=data.serialize(),
                gateway="blupal",
            )
        return payment_url

    async def callback_handler(self, request: Request) -> Response:
        try:
            payload = await request.json()
        except Exception:
            logger.warning("BluPal webhook received invalid JSON")
            return Response(status=400, text="invalid json")

        if not isinstance(payload, dict):
            return Response(status=400, text="invalid payload")

        event = str(payload.get("event") or "").strip().lower()
        if event and event != "payment.completed":
            return Response(status=200, text='{"received":true}', content_type="application/json")

        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        invoice_id = str(data.get("invoice_id") or data.get("id") or "").strip()
        status = str(data.get("status") or "").strip().upper()

        if not invoice_id.isdigit():
            logger.warning("BluPal webhook missing numeric invoice_id")
            return Response(status=400, text="invalid invoice_id")

        if status and status != "PAID":
            return Response(status=200, text='{"received":true}', content_type="application/json")

        try:
            invoice = await self.get_invoice(invoice_id)
            remote_status = str(invoice.get("status") or "").strip().upper()
            if remote_status != "PAID":
                logger.info("BluPal webhook ignored: invoice=%s status=%s", invoice_id, remote_status)
                return Response(status=200, text='{"received":true}', content_type="application/json")

            transaction = None
            async with self.session() as db:
                result = await db.execute(
                    select(Transaction).where(
                        Transaction.payment_id == invoice_id,
                        Transaction.gateway == "blupal",
                    )
                )
                transaction = result.scalars().first()

            if transaction is None:
                logger.warning("BluPal webhook transaction not found: invoice=%s", invoice_id)
                return Response(status=200, text='{"received":true}', content_type="application/json")

            await self._verify_invoice_matches_transaction(transaction, invoice)
            await self.handle_payment_succeeded(invoice_id)
            logger.info("BluPal payment completed: invoice=%s", invoice_id)
        except Exception:
            logger.exception("BluPal webhook processing failed: invoice=%s", invoice_id)

        return Response(status=200, text='{"received":true}', content_type="application/json")

    async def return_handler(self, request: Request) -> Response:
        invoice_id = str(request.query.get("invoice_id") or "").strip()
        invoice_text = (
            f"<p>شماره فاکتور: <b>{invoice_id}</b></p>"
            if invoice_id
            else ""
        )
        html = f"""
<!doctype html>
<html lang="fa" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>بازگشت به ToonelVPN</title>
  <style>
    body {{ font-family: sans-serif; background: #f5f7fa; margin: 0; padding: 24px; }}
    .card {{ max-width: 520px; margin: 10vh auto; background: #fff; padding: 28px; border-radius: 18px; box-shadow: 0 8px 30px rgba(0,0,0,.08); text-align: center; }}
    a {{ display: inline-block; margin-top: 18px; padding: 12px 20px; border-radius: 10px; background: #229ed9; color: #fff; text-decoration: none; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>بازگشت از بلوپال</h1>
    <p>پرداخت شما به ToonelVPN ارسال شد و نتیجه پرداخت از طریق سیستم پرداخت بررسی می‌شود.</p>
    {invoice_text}
    <p>در صورت موفقیت، تکمیل سفارش به‌صورت خودکار انجام می‌شود.</p>
    <a href="https://t.me/ToonelVpn_bot">بازگشت به ربات ToonelVPN</a>
  </div>
</body>
</html>
"""
        return Response(text=html, content_type="text/html", charset="utf-8")
