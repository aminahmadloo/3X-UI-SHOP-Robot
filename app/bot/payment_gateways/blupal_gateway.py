from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from decimal import Decimal, InvalidOperation
from typing import Any

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
    DEFAULT_API_BASE_URL = "https://blupal.net/api"

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
        self.api_key = os.getenv("BLUPAL_API_KEY", "").strip()
        self.webhook_url = f"{self.config.bot.DOMAIN.rstrip('/')}{self.WEBHOOK_PATH}"
        self.app.router.add_post(self.WEBHOOK_PATH, self.callback_handler)
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

    @staticmethod
    def _invoice_id_from_url(payment_url: str) -> str:
        value = (payment_url or "").rstrip("/").rsplit("/", 1)[-1]
        if not value.isdigit():
            raise RuntimeError("BluPal returned an invalid payment link")
        return value

    async def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        """Fetch an invoice, tolerating the provider's short post-creation race.

        BluPal can return the newly-created invoice from the create endpoint
        before the read endpoint is ready. The smart-card purchase handler
        immediately reads the invoice to render the final amount/card details,
        so a transient 404 otherwise becomes the misleading generic
        "invoice creation failed" message. Retry only transient 404/5xx
        responses; persistent failures still raise normally.
        """
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
            return str(invoice.get("payment_link") or "").strip() or self._payment_url(transaction.payment_id, invoice)
        if remote_status in {"EXPIRED", "CANCELED"}:
            async with self.session() as db:
                await Transaction.update(
                    session=db,
                    payment_id=transaction.payment_id,
                    status=TransactionStatus.CANCELED,
                )
            return None
        if remote_status == "PENDING":
            return str(invoice.get("payment_link") or "").strip() or self._payment_url(transaction.payment_id, invoice)
        raise RuntimeError(f"Unknown BluPal invoice status: {remote_status or 'missing'}")

    @staticmethod
    def _payment_url(invoice_id: str, invoice: dict[str, Any] | None = None) -> str:
        explicit = str((invoice or {}).get("payment_link") or "").strip()
        return explicit or f"https://blupal.net/payment/{invoice_id}"

    async def _verify_invoice_matches_transaction(
        self,
        transaction: Transaction,
        invoice: dict[str, Any],
    ) -> None:
        data = SubscriptionData.deserialize(transaction.subscription)
        expected_rial = self._to_rial(data.price)
        remote_amount = int(invoice.get("amount") or 0)
        final_amount = int(invoice.get("final_amount") or 0)
        if remote_amount != expected_rial:
            raise RuntimeError(
                f"BluPal invoice {transaction.payment_id} amount mismatch: "
                f"expected={expected_rial}, remote={remote_amount}"
            )
        if final_amount < remote_amount or final_amount > remote_amount + 999:
            raise RuntimeError(
                f"BluPal invoice {transaction.payment_id} final amount is invalid"
            )

    @staticmethod
    def _validate_created_invoice_response(
        response: dict[str, Any], expected_rial: int
    ) -> tuple[str, str, int]:
        invoice_id = str(response.get("invoice_id") or "").strip()
        payment_url = str(response.get("payment_link") or "").strip()

        try:
            remote_amount = int(response.get("amount") or 0)
            final_amount = int(response.get("final_amount") or 0)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("BluPal returned invalid invoice amounts") from exc

        if not invoice_id.isdigit() or not payment_url:
            raise RuntimeError("BluPal returned an incomplete invoice")

        if remote_amount != expected_rial:
            raise RuntimeError(
                f"BluPal returned an unexpected invoice amount: "
                f"expected={expected_rial}, remote={remote_amount}"
            )

        if final_amount < remote_amount or final_amount > remote_amount + 999:
            raise RuntimeError("BluPal returned an invalid final invoice amount")

        return invoice_id, payment_url, final_amount

    async def create_payment(self, data: SubscriptionData) -> str:
        if not self.is_configured():
            raise RuntimeError("BluPal is not configured")

        amount_rial = self._to_rial(data.price)
        order_key = data.serialize()
        lock = self.storage.redis.lock(
            f"payment:blupal:create:{data.user_id}:{hashlib.sha256(order_key.encode(\"utf-8\")).hexdigest()}",
            timeout=180,
            blocking_timeout=10,
        )
        async with lock:
            existing = await self._find_pending_transaction(data)
            if existing is not None:
                reused = await self._reconcile_existing_invoice(existing)
                if reused is not None:
                    return reused

            payload = {"amount": amount_rial}
            status, response = await self._request("POST", "/v1/invoices/create", json=payload)
            if status != 200 or response.get("success") is not True:
                raise RuntimeError(
                    f"BluPal invoice creation failed: HTTP {status}, code={self._error_code(response)}"
                )

            invoice_id, payment_url, final_amount = self._validate_created_invoice_response(
                response, amount_rial
            )

            async with self.session() as db:
                transaction = await Transaction.create(
                    session=db,
                    tg_id=data.user_id,
                    subscription=data.serialize(),
                    payment_id=invoice_id,
                    gateway="blupal",
                    status=TransactionStatus.PENDING,
                )
                if transaction is None:
                    raise RuntimeError(f"Could not create ToonelVPN transaction for BluPal {invoice_id}")

            logger.info(
                "BluPal invoice created: invoice=%s user=%s amount_rial=%s final_amount=%s",
                invoice_id,
                data.user_id,
                amount_rial,
                final_amount,
            )
            return payment_url

    async def handle_payment_succeeded(self, payment_id: str) -> None:
        lock = self.storage.redis.lock(
            f"payment:blupal:{payment_id}",
            timeout=180,
            blocking_timeout=10,
        )
        async with lock:
            async with self.session() as db:
                transaction = await Transaction.get_by_id(session=db, payment_id=payment_id)
                if transaction is None:
                    raise RuntimeError(f"BluPal transaction {payment_id} was not found")
                if transaction.gateway != "blupal":
                    raise RuntimeError(f"Payment {payment_id} does not belong to BluPal")
                if transaction.status == TransactionStatus.COMPLETED:
                    return
                if transaction.status == TransactionStatus.CANCELED:
                    logger.warning("Ignoring success for canceled BluPal transaction %s", payment_id)
                    return

            invoice = await self.get_invoice(payment_id)
            if str(invoice.get("status") or "").upper() != "PAID":
                raise RuntimeError(f"BluPal invoice {payment_id} is not PAID")
            async with self.session() as db:
                transaction = await Transaction.get_by_id(session=db, payment_id=payment_id)
                if transaction is None:
                    raise RuntimeError(f"BluPal transaction {payment_id} was not found")
                await self._verify_invoice_matches_transaction(transaction, invoice)

            await self._on_payment_succeeded(payment_id)

    async def handle_payment_canceled(self, payment_id: str) -> None:
        async with self.session() as db:
            transaction = await Transaction.get_by_id(session=db, payment_id=payment_id)
            if transaction is None or transaction.gateway != "blupal":
                return
            if transaction.status == TransactionStatus.COMPLETED:
                return
        await self._on_payment_canceled(payment_id)

    async def callback_handler(self, request: Request) -> Response:
        try:
            payload = await request.json()
        except Exception:
            return Response(status=400, text="invalid json")
        if not isinstance(payload, dict):
            return Response(status=400, text="invalid payload")

        event = str(payload.get("event") or "").strip()
        invoice_id = str(payload.get("invoice_id") or "").strip()
        if event != "payment.completed" or not invoice_id or payload.get("status") != "PAID":
            return Response(status=400, text="invalid webhook")

        try:
            async with self.session() as db:
                transaction = await Transaction.get_by_id(session=db, payment_id=invoice_id)
                if transaction is None or transaction.gateway != "blupal":
                    return Response(status=404, text="unknown invoice")

            invoice = await self.get_invoice(invoice_id)
            await self._verify_invoice_matches_transaction(transaction, invoice)
            if str(invoice.get("status") or "").upper() != "PAID":
                return Response(status=409, text="invoice not paid")

            await self.handle_payment_succeeded(invoice_id)
        except Exception:
            logger.exception("Failed to process BluPal webhook %s", invoice_id)
            return Response(status=500, text="processing failed")

        return Response(status=200, content_type="application/json", text='{"received": true}')

    async def credit_wallet(self, payment_id: str) -> None:
        """Use a provider-specific wallet reference while keeping base flows intact."""
        async with self.session() as db:
            transaction = await Transaction.get_by_id(session=db, payment_id=payment_id)
            if transaction is None:
                raise RuntimeError(f"BluPal transaction {payment_id} was not found")
            data = SubscriptionData.deserialize(transaction.subscription)
            user = await User.get(session=db, tg_id=data.user_id)
            if user is None:
                raise RuntimeError(f"User {data.user_id} was not found")
            if data.payment_kind != "wallet_topup":
                return
            if transaction.status == TransactionStatus.COMPLETED:
                return

        await self.services.wallet.credit(
            user_tg_id=user.tg_id,
            amount=int(data.price),
            transaction_type="topup",
            description="شارژ کیف پول از طریق کارت به کارت هوشمند بلوپال",
            reference_id=f"blupal:{payment_id}",
        )
        async with self.session() as db:
            await Transaction.update(session=db, payment_id=payment_id, status=TransactionStatus.COMPLETED)
        balance = await self.services.wallet.get_balance(user.tg_id)
        await self.bot.send_message(
            user.tg_id,
            f"✅ <b>شارژ کیف پول با موفقیت انجام شد.</b>\n\n"
            f"💰 مبلغ شارژ: <b>{int(data.price):,} تومان</b>\n"
            f"💳 موجودی جدید: <b>{balance:,} تومان</b>",
        )
