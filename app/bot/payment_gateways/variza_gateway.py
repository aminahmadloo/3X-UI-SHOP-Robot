from __future__ import annotations

import hashlib
import hmac
import html
import logging
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
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


class VarizaGateway(PaymentGateway):
    """Fully isolated Variza card-to-card smart gateway."""

    name = "💳 پرداخت با درگاه واریزا"
    currency = Currency.TOMAN
    callback = "pay_variza"
    WEBHOOK_PATH = "/webhooks/variza"
    RETURN_PATH = "/payments/variza/return"
    DEFAULT_API_BASE_URL = "https://variza.ir/api/v1"
    VARIZA_MAX_AMOUNT_DELTA_TOMAN = 5000

    def __init__(self, app: Application, config: Config, session: async_sessionmaker,
                 storage: RedisStorage, bot: Bot, i18n: I18n,
                 services: ServicesContainer) -> None:
        super().__init__(app, config, session, storage, bot, i18n, services)
        self.app.router.add_post(self.WEBHOOK_PATH, self.callback_handler)
        self.app.router.add_get(self.RETURN_PATH, self.return_handler)
        logger.info("VarizaGateway initialized as isolated card-to-card gateway.")

    @staticmethod
    def _env_file() -> Path:
        return Path("/app/.env")

    @classmethod
    def _env_value(cls, key: str, default: str = "") -> str:
        path = cls._env_file()
        if path.exists():
            try:
                for raw in path.read_text(encoding="utf-8").splitlines():
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    name, value = line.split("=", 1)
                    if name.strip() == key:
                        value = value.strip()
                        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                            value = value[1:-1]
                        return value.strip()
            except OSError:
                pass
        return os.getenv(key, default).strip()

    @classmethod
    def is_enabled(cls) -> bool:
        return cls._env_value("VARIZA_ENABLED", "false").lower() in {"1", "true", "yes", "on"}

    @classmethod
    def is_configured(cls) -> bool:
        return bool(cls._env_value("VARIZA_API_KEY") and cls._env_value("VARIZA_WEBHOOK_SECRET"))

    @classmethod
    def is_available(cls) -> bool:
        return cls.is_enabled() and cls.is_configured()

    @classmethod
    def webhook_url(cls, config: Config) -> str:
        return f"{config.bot.DOMAIN.rstrip('/')}{cls.WEBHOOK_PATH}"

    @classmethod
    def return_url(cls, config: Config) -> str:
        configured = cls._env_value("VARIZA_RETURN_URL")
        return configured or f"{config.bot.DOMAIN.rstrip('/')}{cls.RETURN_PATH}"

    @classmethod
    def _api_base_url(cls) -> str:
        return cls._env_value("VARIZA_API_BASE_URL", cls.DEFAULT_API_BASE_URL).rstrip("/")

    @classmethod
    def _expires_in(cls) -> str:
        return cls._env_value("VARIZA_EXPIRES_IN", "1h") or "1h"

    @classmethod
    def _card_last_4(cls) -> str:
        return cls._env_value("VARIZA_CARD_LAST_4", "")

    @classmethod
    def _api_key(cls) -> str:
        return cls._env_value("VARIZA_API_KEY")

    @classmethod
    def _webhook_secret(cls) -> str:
        return cls._env_value("VARIZA_WEBHOOK_SECRET")

    @classmethod
    def _to_toman(cls, amount: float | int | Decimal) -> int:
        try:
            value = Decimal(str(amount))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid Toman amount: {amount}") from exc
        if value <= 0:
            raise ValueError("Payment amount must be positive")
        if value != value.to_integral_value():
            raise ValueError("Payment amount must be a whole Toman")
        return int(value)

    @classmethod
    def tracking_code_for_slug(cls, slug: str) -> str:
        return f"toonel-vz-{slug}"

    @classmethod
    def tracking_code_for_order(cls, data: SubscriptionData) -> str:
        return f"toonel-vz-{cls._order_key(data)[:20]}"

    @classmethod
    def _order_key(cls, data: SubscriptionData) -> str:
        return hashlib.sha256(data.serialize().encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_digits(value: str) -> str:
        translation = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
        return value.translate(translation)

    @classmethod
    async def fetch_displayed_payable_toman(cls, pay_url: str) -> int | None:
        """Read the exact payable amount from the visible Variza payment page."""
        try:
            async with ClientSession(timeout=ClientTimeout(total=10)) as client:
                async with client.get(pay_url, allow_redirects=True) as response:
                    if response.status != 200:
                        logger.warning(
                            "Variza pay page returned HTTP %s for %s",
                            response.status,
                            pay_url,
                        )
                        return None
                    body = await response.text()
        except Exception:
            logger.exception("Failed to load Variza pay page %s", pay_url)
            return None

        # Remove non-visible HTML content first. Variza may keep unrelated
        # numeric values in JavaScript/state data that must never be parsed
        # as the payable amount.
        visible_body = re.sub(
            r"(?is)<(script|style|noscript|template)\b[^>]*>.*?</\1>",
            " ",
            body,
        )
        visible_body = re.sub(r"(?is)<!--.*?-->", " ", visible_body)

        text = html.unescape(re.sub(r"<[^>]+>", " ", visible_body))
        text = re.sub(r"\s+", " ", text).strip()

        # Extract only the number associated with the exact visible label.
        match = re.search(
            r"مبلغ\s*را\s*دقیق(?:اً|ا)?\s*واریز\s*کنید"
            r"[^0-9۰-۹٠-٩]{0,120}"
            r"([0-9۰-۹٠-٩][0-9۰-۹٠-٩,٬\.\s]*)"
            r"\s*(?:ریال|﷼)",
            text,
            re.IGNORECASE,
        )

        if not match:
            logger.warning(
                "Could not parse exact payable amount from Variza pay page %s",
                pay_url,
            )
            return None

        rial_text = cls._normalize_digits(match.group(1))
        rial_text = (
            rial_text
            .replace(",", "")
            .replace("٬", "")
            .replace(".", "")
            .replace(" ", "")
        )

        try:
            rial = int(rial_text)
        except ValueError:
            logger.warning(
                "Invalid Variza payable amount extracted: %r",
                rial_text,
            )
            return None

        if rial <= 0 or rial % 10 != 0:
            return None

        return rial // 10

    async def _find_pending_transaction(self, data: SubscriptionData) -> Transaction | None:
        serialized = data.serialize()
        async with self.session() as db:
            result = await db.execute(select(Transaction).where(
                Transaction.tg_id == data.user_id,
                Transaction.status == TransactionStatus.PENDING,
                Transaction.subscription == serialized,
            ).order_by(Transaction.created_at.desc()))
            return result.scalars().first()

    async def _find_completed_transaction(self, data: SubscriptionData) -> Transaction | None:
        serialized = data.serialize()
        async with self.session() as db:
            result = await db.execute(select(Transaction).where(
                Transaction.tg_id == data.user_id,
                Transaction.status == TransactionStatus.COMPLETED,
                Transaction.subscription == serialized,
            ).order_by(Transaction.created_at.desc()))
            return result.scalars().first()

    @classmethod
    def _headers(cls) -> dict[str, str]:
        token = cls._api_key()
        if not token:
            raise RuntimeError("VARIZA_API_KEY is not configured")
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}

    async def _request(self, method: str, path: str, **kwargs: Any) -> tuple[int, dict[str, Any]]:
        async with ClientSession(timeout=ClientTimeout(total=20)) as client:
            async with client.request(method, f"{self._api_base_url()}{path}", headers=self._headers(), **kwargs) as response:
                body = await response.json(content_type=None)
                return response.status, body if isinstance(body, dict) else {"raw": body}

    async def create_payment(self, data: SubscriptionData) -> str:
        if not self.is_available():
            raise RuntimeError("Variza is disabled or not configured")
        amount = self._to_toman(data.price)
        if await self._find_completed_transaction(data) is not None:
            raise RuntimeError("This order has already been paid")
        order_key = self._order_key(data)
        lock = self.storage.redis.lock(f"payment:variza:create:{order_key}", timeout=180, blocking_timeout=10)
        async with lock:
            if await self._find_completed_transaction(data) is not None:
                raise RuntimeError("This order has already been paid")
            existing = await self._find_pending_transaction(data)
            if existing is not None:
                return f"https://variza.ir/pay/{existing.payment_id}"
            payload: dict[str, Any] = {
                "amount": amount,
                "return_url": self.return_url(self.config),
                "title": f"ToonelVPN {self.tracking_code_for_order(data)}",
                "expires_in": self._expires_in(),
            }
            card_last_4 = self._card_last_4()
            if card_last_4:
                payload["card_last_4"] = card_last_4
            status, response = await self._request("POST", "/pay", json=payload)
            if status != 201:
                raise RuntimeError(f"Variza payment creation failed: HTTP {status}: {response}")
            slug = str(response.get("slug") or "").strip()
            pay_url = str(response.get("pay_url") or "").strip()
            response_amount = response.get("amount", amount)
            if not slug or not pay_url:
                raise RuntimeError("Variza returned an incomplete payment response")
            if self._to_toman(response_amount) != amount:
                raise RuntimeError("Variza returned an unexpected payment amount")
            async with self.session() as db:
                transaction = await Transaction.create(session=db, tg_id=data.user_id, subscription=data.serialize(), payment_id=slug, status=TransactionStatus.PENDING)
                if transaction is None:
                    raise RuntimeError(f"Could not create ToonelVPN transaction for Variza {slug}")
            logger.info("Variza payment created: slug=%s tg_id=%s amount=%s order_key=%s", slug, data.user_id, amount, order_key)
            return pay_url

    async def _cancel_sibling_transactions(self, serialized: str, current_payment_id: str) -> None:
        async with self.session() as db:
            result = await db.execute(select(Transaction).where(
                Transaction.status == TransactionStatus.PENDING,
                Transaction.subscription == serialized,
                Transaction.payment_id != current_payment_id,
            ))
            siblings = list(result.scalars().all())
            for sibling in siblings:
                sibling.status = TransactionStatus.CANCELED
            if siblings:
                await db.commit()

    async def handle_payment_succeeded(self, payment_id: str) -> None:
        lock = self.storage.redis.lock(f"payment:variza:{payment_id}", timeout=180, blocking_timeout=10)
        async with lock:
            async with self.session() as db:
                transaction = await Transaction.get_by_id(session=db, payment_id=payment_id)
                if transaction is None:
                    raise RuntimeError(f"Variza transaction {payment_id} was not found")
                if transaction.status == TransactionStatus.COMPLETED:
                    return
                if transaction.status == TransactionStatus.CANCELED:
                    return
                serialized = transaction.subscription
                data = SubscriptionData.deserialize(serialized)
            if data.payment_kind == "wallet_topup":
                user = await self._get_user(data.user_id)
                if user is None:
                    raise RuntimeError(f"User {data.user_id} not found for Variza {payment_id}")
                await self.services.wallet.credit(user_tg_id=user.tg_id, amount=int(data.price), transaction_type="topup", description="شارژ کیف پول از طریق درگاه واریزا", reference_id=f"variza:{payment_id}")
                async with self.session() as db:
                    await Transaction.update(session=db, payment_id=payment_id, status=TransactionStatus.COMPLETED)
                await self._cancel_sibling_transactions(serialized, payment_id)
                balance = await self.services.wallet.get_balance(user.tg_id)
                await self.bot.send_message(user.tg_id, f"✅ <b>شارژ کیف پول با موفقیت انجام شد.</b>\n\n💰 مبلغ شارژ: <b>{int(data.price):,} تومان</b>\n💳 موجودی جدید: <b>{balance:,} تومان</b>")
                return
            await self._on_payment_succeeded(payment_id)
            await self._cancel_sibling_transactions(serialized, payment_id)

    async def _get_user(self, tg_id: int) -> User | None:
        async with self.session() as db:
            return await User.get(session=db, tg_id=tg_id)

    async def handle_payment_canceled(self, payment_id: str) -> None:
        async with self.session() as db:
            transaction = await Transaction.get_by_id(session=db, payment_id=payment_id)
            if transaction is None or transaction.status == TransactionStatus.COMPLETED:
                return
        await self._on_payment_canceled(payment_id)

    @classmethod
    def _valid_signature(cls, raw_body: bytes, signature: str) -> bool:
        secret = cls._webhook_secret()
        if not secret or not signature:
            return False
        expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature.strip())

    async def callback_handler(self, request: Request) -> Response:
        raw_body = await request.read()
        if not self._valid_signature(raw_body, request.headers.get("X-Webhook-Signature", "")):
            return Response(status=400, text="invalid signature")
        try:
            payload = await request.json()
        except Exception:
            return Response(status=400, text="invalid json")
        if not isinstance(payload, dict):
            return Response(status=400, text="invalid payload")
        event = str(payload.get("event") or request.headers.get("X-Event") or "").strip()
        slug = str(payload.get("slug") or "").strip()
        status = str(payload.get("status") or "").strip().lower()
        if event != "payment.paid" or status != "paid" or not slug:
            return Response(status=200, text="ignored")
        async with self.session() as db:
            transaction = await Transaction.get_by_id(session=db, payment_id=slug)
            if transaction is None:
                return Response(status=404, text="unknown payment")
            expected_amount = self._to_toman(SubscriptionData.deserialize(transaction.subscription).price)
        webhook_amount = payload.get("amount")
        if webhook_amount is not None:
            actual_amount = self._to_toman(webhook_amount)
            delta = actual_amount - expected_amount
            if delta < 0 or delta > self.VARIZA_MAX_AMOUNT_DELTA_TOMAN:
                return Response(status=400, text="amount mismatch")
        try:
            await self.handle_payment_succeeded(slug)
        except Exception:
            logger.exception("Failed to process Variza webhook %s", slug)
            return Response(status=500, text="processing failed")
        return Response(status=200, text="ok")

    async def return_handler(self, request: Request) -> Response:
        return Response(text=("<!doctype html><html lang='fa' dir='rtl'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>ToonelVPN</title><style>body{font-family:system-ui;max-width:520px;margin:60px auto;padding:20px;text-align:center}.card{border:1px solid #ddd;border-radius:18px;padding:24px}</style>"
            "<div class='card'><h2>✅ پرداخت واریزا ثبت شد</h2><p>در صورت تأیید نهایی، سفارش شما به‌صورت خودکار تکمیل می‌شود.</p><p>می‌توانید به ربات ToonelVPN برگردید.</p></div></html>"), content_type="text/html")
