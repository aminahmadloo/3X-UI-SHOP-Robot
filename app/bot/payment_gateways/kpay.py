from __future__ import annotations

import logging
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


class KPay(PaymentGateway):
    """KPay card-to-card hosted checkout integration.

    KPay owns the bank cards. ToonelVPN stores only KPay API credentials and
    the identifiers of the selected shop/card; full card numbers are never
    stored here.
    """

    name = "💳 کارت‌به‌کارت هوشمند"
    currency = Currency.TOMAN
    callback = "pay_kpay"
    CALLBACK_PATH = "/kpay/callback"
    API_BASE_URL = "https://kpay.website/api/v1"
    wallet_reference_prefix = "kpay"

    def __init__(self, app: Application, config: Config, session: async_sessionmaker, storage: RedisStorage, bot: Bot, i18n: I18n, services: ServicesContainer) -> None:
        self.app = app
        self.config = config
        self.session = session
        self.storage = storage
        self.bot = bot
        self.i18n = i18n
        self.services = services
        self.app.router.add_get(self.CALLBACK_PATH, self.callback_handler)
        self.app.router.add_post(self.CALLBACK_PATH, self.callback_handler)
        logger.info("KPay payment gateway initialized.")

    async def _get_credentials(self) -> tuple[str | None, str | None, str | None]:
        async with self.session() as session:
            settings = await PaymentGatewaySettings.get(session)
            if settings is None:
                return None, None, None
            return settings.kpay_api_key.strip() or None, settings.kpay_shop_id.strip() or None, settings.kpay_card_id.strip() or None

    async def _request(self, method: str, path: str, api_key: str, payload: dict | None = None) -> dict:
        timeout = ClientTimeout(total=20)
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "Accept": "application/json"}
        async with ClientSession(timeout=timeout) as client:
            async with client.request(method, f"{self.API_BASE_URL}{path}", json=payload, headers=headers) as response:
                body = await response.json(content_type=None)
                if response.status >= 400:
                    raise RuntimeError(f"KPay HTTP {response.status}: {body}")
                if not isinstance(body, dict):
                    raise RuntimeError(f"Unexpected KPay response: {body}")
                return body

    @staticmethod
    def _validate_toman(amount: int | float | str) -> int:
        try:
            value = Decimal(str(amount))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid Toman amount: {amount}") from exc
        if value <= 0 or value != value.to_integral_value():
            raise ValueError("KPay amount must be a positive whole Toman value")
        return int(value)

    @staticmethod
    def _extract_authority(request: Request) -> str:
        for key in ("authority", "Authority", "payment_id", "transaction_id", "id"):
            value = request.query.get(key)
            if value and str(value).strip():
                return str(value).strip()
        return ""

    async def create_payment(self, data: SubscriptionData) -> str:
        if data.payment_kind not in {"subscription", "wallet_topup"}:
            raise RuntimeError(f"KPay is not supported for payment kind: {data.payment_kind}")
        api_key, shop_id, card_id = await self._get_credentials()
        if not api_key or not shop_id or not card_id:
            raise RuntimeError("KPay API Key / Shop ID / Card ID are not fully configured")

        amount_toman = self._validate_toman(data.price)
        amount_rial = amount_toman * 10
        payment_id = f"toonel-kpay-{uuid.uuid4().hex}"
        callback_url = f"{self.config.bot.DOMAIN.rstrip('/')}{self.CALLBACK_PATH}"
        response = await self._request(
            "POST", "/transactions/create", api_key,
            {
                "shop_id": shop_id,
                "card_id": card_id,
                "amount": amount_rial,
                "callback_url": callback_url,
                "description": f"ToonelVPN payment {payment_id}",
                "factor_number": payment_id,
                "fee_side": "customer",
            },
        )
        authority = str(response.get("authority") or "").strip()
        payment_url = str(response.get("payment_url") or "").strip()
        remote_amount = response.get("amount")
        if not authority or not payment_url:
            raise RuntimeError(f"KPay response has no authority/payment_url: {response}")
        if remote_amount is not None and int(Decimal(str(remote_amount))) != amount_rial:
            raise RuntimeError(f"KPay amount mismatch while creating payment: expected={amount_rial} got={remote_amount}")

        async with self.session() as session:
            transaction = await Transaction.create(
                session=session,
                tg_id=data.user_id,
                subscription=data.serialize(),
                payment_id=authority,
                status=TransactionStatus.PENDING,
            )
            if transaction is None:
                raise RuntimeError(f"Could not create KPay transaction {authority}")
        logger.info("KPay payment created: user=%s authority=%s expected_rials=%s", data.user_id, authority, amount_rial)
        return payment_url

    async def _verify_remote_payment(self, authority: str, expected_rials: int) -> bool:
        api_key, _, _ = await self._get_credentials()
        if not api_key:
            raise RuntimeError("KPay API key is not configured")

        check = await self._request("GET", f"/transactions/check/{authority}", api_key)
        check_status = str(check.get("status") or "").lower()
        check_paid = bool(check.get("is_paid")) or check_status in {"paid", "completed", "success", "successful", "verified", "confirmed"}
        if not check_paid:
            return False

        response = await self._request("POST", "/transactions/verify", api_key, {"authority": authority})
        status = str(response.get("status") or "").lower()
        paid = bool(response.get("is_paid")) or status in {"paid", "completed", "success", "successful", "verified", "confirmed"}
        amount = response.get("amount")
        if amount is not None:
            try:
                verified_rials = int(Decimal(str(amount)))
            except (InvalidOperation, ValueError):
                raise RuntimeError(f"KPay returned invalid verified amount: {amount}")
            if verified_rials != expected_rials:
                raise RuntimeError(f"KPay amount mismatch: expected={expected_rials} got={verified_rials} authority={authority}")
        return paid

    async def handle_payment_succeeded(self, payment_id: str) -> None:
        lock = self.storage.redis.lock(f"payment:kpay:{payment_id}", timeout=300, blocking_timeout=10)
        async with lock:
            async with self.session() as session:
                transaction = await Transaction.get_by_id(session=session, payment_id=payment_id)
                if transaction is None:
                    raise RuntimeError(f"KPay transaction {payment_id} was not found")
                if transaction.status == TransactionStatus.COMPLETED:
                    logger.info("Ignoring duplicate KPay success for %s", payment_id)
                    return
                if transaction.status == TransactionStatus.CANCELED:
                    logger.warning("Ignoring success for canceled KPay transaction %s", payment_id)
                    return
                data = SubscriptionData.deserialize(transaction.subscription)
            expected_rials = self._validate_toman(data.price) * 10
            paid = await self._verify_remote_payment(payment_id, expected_rials)
            if not paid:
                logger.info("KPay callback arrived before payment confirmation: %s", payment_id)
                return
            await self._on_payment_succeeded(payment_id)

    async def handle_payment_canceled(self, payment_id: str) -> None:
        async with self.session() as session:
            transaction = await Transaction.get_by_id(session=session, payment_id=payment_id)
            if transaction is None:
                raise RuntimeError(f"KPay transaction {payment_id} was not found")
            if transaction.status == TransactionStatus.COMPLETED:
                logger.info("Ignoring cancellation for completed KPay transaction %s", payment_id)
                return
        await self._on_payment_canceled(payment_id)

    async def callback_handler(self, request: Request) -> Response:
        authority = self._extract_authority(request)
        if not authority:
            return Response(text="پرداخت نامشخص است؛ کد تراکنش دریافت نشد.", status=400, content_type="text/plain", charset="utf-8")
        try:
            await self.handle_payment_succeeded(authority)
        except RuntimeError as exc:
            logger.warning("KPay callback rejected: authority=%s error=%s", authority, exc)
            return Response(text=f"پرداخت قابل تأیید نیست.\n{str(exc)[:500]}", status=400, content_type="text/plain", charset="utf-8")
        except Exception:
            logger.exception("KPay callback processing failed: authority=%s", authority)
            return Response(text="خطا در تأیید پرداخت. لطفاً چند لحظه بعد وضعیت سرویس را بررسی کنید.", status=500, content_type="text/plain", charset="utf-8")
        return Response(text="پرداخت شما با موفقیت تأیید شد. پیام تحویل سرویس در تلگرام برای شما ارسال می‌شود.", status=200, content_type="text/plain", charset="utf-8")

    async def test_connection(self) -> dict:
        api_key, shop_id, card_id = await self._get_credentials()
        if not api_key:
            raise RuntimeError("API Key تنظیم نشده است")
        if not shop_id:
            raise RuntimeError("Shop ID تنظیم نشده است")
        if not card_id:
            raise RuntimeError("Card ID تنظیم نشده است")
        shops = await self._request("GET", "/shops", api_key)
        cards = await self._request("GET", "/cards", api_key)
        shop_items = shops.get("shops") or []
        card_items = cards.get("cards") or []
        shop = next((item for item in shop_items if str(item.get("id")) == shop_id), None)
        card = next((item for item in card_items if str(item.get("id")) == card_id), None)
        if shop is None:
            raise RuntimeError("Shop ID در KPay پیدا نشد یا به این API Key تعلق ندارد")
        if card is None:
            raise RuntimeError("Card ID در KPay پیدا نشد یا به این API Key تعلق ندارد")
        if shop.get("is_active") is False:
            raise RuntimeError("Shop انتخاب‌شده در KPay غیرفعال است")
        if card.get("is_active") is False:
            raise RuntimeError("Card انتخاب‌شده در KPay غیرفعال است")
        return {"shop": shop, "card": card, "callback_url": f"{self.config.bot.DOMAIN.rstrip('/')}{self.CALLBACK_PATH}"}
