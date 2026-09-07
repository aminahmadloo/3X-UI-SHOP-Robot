from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.bot.models import ServicesContainer
from app.bot.routers.my_services.handler import _discover_user_subscriptions_from_xui
from app.bot.services.customer_level import get_customer_level
from app.db.models.service_period import ServicePeriod
from app.db.models.service_purchase_plan import ServicePurchasePlan
from app.db.models.connected_device_settings import ConnectedDeviceSettings
from app.db.models import (
    Referral,
    ReferrerReward,
    Server,
    Subscription,
    SupportMessage,
    SupportTicket,
    Transaction,
    User,
    WalletTransaction,
)

BASE_DIR = Path(__file__).resolve().parent
INDEX_FILE = BASE_DIR / "miniapp" / "index.html"
MAX_INIT_DATA_AGE = 60 * 60
MAX_CLOCK_SKEW = 60
HEX_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
BOT_USERNAME = "ToonelVpn_bot"


def _mini_app_url(domain: str) -> str:
    domain = domain.strip().rstrip("/")
    if not domain:
        raise ValueError("BOT_DOMAIN must be configured for Mini App")
    if not domain.startswith(("http://", "https://")):
        domain = f"https://{domain}"
    return f"{domain}/miniapp"


def _validate_init_data(init_data: str, bot_token: str) -> dict[str, object]:
    if not init_data or not bot_token:
        raise web.HTTPUnauthorized(text="Invalid Telegram init data")
    try:
        raw_pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise web.HTTPUnauthorized(text="Invalid Telegram init data") from exc
    keys = [key for key, _ in raw_pairs]
    if len(keys) != len(set(keys)):
        raise web.HTTPUnauthorized(text="Invalid Telegram init data")
    pairs = dict(raw_pairs)
    received_hash = pairs.pop("hash", None)
    if not received_hash or not HEX_HASH_RE.fullmatch(received_hash):
        raise web.HTTPUnauthorized(text="Invalid Telegram init data hash")
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received_hash, expected_hash):
        raise web.HTTPUnauthorized(text="Invalid Telegram init data")
    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise web.HTTPUnauthorized(text="Invalid auth date") from exc
    now = int(time.time())
    age = now - auth_date
    if auth_date <= 0 or age > MAX_INIT_DATA_AGE or age < -MAX_CLOCK_SKEW:
        raise web.HTTPUnauthorized(text="Expired or invalid Telegram init data")
    try:
        telegram_user = json.loads(pairs["user"])
    except (KeyError, json.JSONDecodeError, TypeError) as exc:
        raise web.HTTPUnauthorized(text="Invalid Telegram user data") from exc
    if not isinstance(telegram_user, dict):
        raise web.HTTPUnauthorized(text="Invalid Telegram user data")
    user_id = telegram_user.get("id")
    if not isinstance(user_id, int) or isinstance(user_id, bool) or user_id <= 0:
        raise web.HTTPUnauthorized(text="Invalid Telegram user id")
    pairs["telegram_user"] = telegram_user
    return pairs


def _iso(value) -> str | None:
    return value.isoformat() if value else None


def _tx_status(value) -> str:
    return getattr(value, "value", str(value))


class MiniAppController:
    def __init__(
        self,
        db,
        bot_token: str,
        admin_ids: list[int],
        services: ServicesContainer,
    ) -> None:
        self.db = db
        self.bot_token = bot_token
        self.admin_ids = {int(admin_id) for admin_id in admin_ids}
        self.services = services

    async def _authenticate(self, request: web.Request) -> tuple[int, dict[str, object]]:
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        if not init_data:
            raise web.HTTPUnauthorized(text="Telegram Mini App authentication required")
        validated = _validate_init_data(init_data, self.bot_token)
        telegram_user = validated["telegram_user"]
        assert isinstance(telegram_user, dict)
        tg_id = int(telegram_user["id"])
        # Mini App is available to every authenticated Telegram user.
        # Individual admin-only endpoints enforce admin_ids themselves.
        return tg_id, telegram_user

    async def _get_user(self, session, tg_id: int) -> User:
        user = await User.get(session=session, tg_id=tg_id)
        if user is None:
            raise web.HTTPNotFound(text="User not found")
        return user

    async def index(self, request: web.Request) -> web.StreamResponse:
        if not INDEX_FILE.is_file():
            raise web.HTTPNotFound(text="Mini App frontend not found")
        return web.FileResponse(INDEX_FILE)

    async def me(self, request: web.Request) -> web.Response:
        tg_id, telegram_user = await self._authenticate(request)
        async with self.db.session() as session:
            user = await self._get_user(session, tg_id)

            subscriptions = await _discover_user_subscriptions_from_xui(session, user, self.services)
            vpn_service = self.services.vpn
            services_payload: list[dict[str, object]] = []
            for subscription in subscriptions:
                live = await vpn_service.get_client_data(user, subscription.id)
                if live is None:
                    continue
                services_payload.append(self._serialize_live_subscription(subscription, live))

            active = [item for item in services_payload if item["status"] == "active"]
            expired = [item for item in services_payload if item["status"] == "expired"]
            nearest = min(
                (item for item in services_payload if item.get("expire_date")),
                key=lambda item: item["expire_date"],
                default=None,
            )
            servers: list[dict[str, object]] = []
            seen_servers: set[tuple[object, object]] = set()
            for item in services_payload:
                server = item.get("server") or {}
                key = (server.get("name"), server.get("location"))
                if key not in seen_servers:
                    seen_servers.add(key)
                    servers.append(server)

            used = sum(int(item.get("traffic_used", 0) or 0) for item in services_payload)
            total = sum(
                int(item.get("traffic_total", 0) or 0)
                for item in services_payload
                if int(item.get("traffic_total", 0) or 0) > 0
            )

            wallet_balance = await self.services.wallet.get_balance(tg_id)
            wallet_transactions = await self.services.wallet.get_recent_transactions(tg_id, 8)
            referral_count = await Referral.get_referral_count(session, tg_id)
            level, points = await get_customer_level(session, tg_id)
            reward_sum = await session.scalar(
                select(func.coalesce(func.sum(ReferrerReward.amount), 0)).where(
                    ReferrerReward.user_tg_id == tg_id
                )
            ) or 0
            recent_transactions = await self._recent_transactions(session, tg_id, 8)
            support = await self._support_summary(session, user.id)

            recent_activity = self._build_recent_activity(
                services_payload, recent_transactions, wallet_transactions, support
            )[:8]

            return web.json_response(
                {
                    "user": {
                        "id": user.tg_id,
                        "first_name": user.first_name,
                        "username": user.username,
                        "language_code": user.language_code,
                        "created_at": _iso(user.created_at),
                        "is_trial_used": user.is_trial_used,
                        "source_invite_name": user.source_invite_name,
                    },
                    "telegram": {
                        "first_name": telegram_user.get("first_name"),
                        "last_name": telegram_user.get("last_name"),
                        "username": telegram_user.get("username"),
                        "photo_url": telegram_user.get("photo_url"),
                    },
                    "account": {
                        "wallet_balance": int(wallet_balance),
                        "level": level.title,
                        "level_key": level.key,
                        "discount_percent": level.discount_percent,
                        "points": points,
                        "referrals": referral_count,
                        "referral_rewards": float(reward_sum),
                        "support_open": support["open_count"],
                    },
                    "dashboard": {
                        "total_services": len(services_payload),
                        "active_services": len(active),
                        "expired_services": len(expired),
                        "traffic_used": used,
                        "traffic_total": total,
                        "traffic_remaining": max(0, total - used) if total else -1,
                        "nearest_expiry": nearest.get("expire_date") if nearest else None,
                        "servers": servers,
                        "recent_activity": recent_activity,
                        "generated_at": time.time(),
                    },
                    "services": services_payload,
                    "wallet_transactions": [self._serialize_wallet_transaction(item) for item in wallet_transactions],
                    "transactions": recent_transactions,
                    "support": support,
                    "referral": {
                        "link": f"https://t.me/{BOT_USERNAME}?start=ref_{tg_id}",
                        "referrals": referral_count,
                        "purchase_count": sum(1 for item in recent_transactions if item["status"] == "completed"),
                        "rewards_total": float(reward_sum),
                    },
                    "admin": tg_id in self.admin_ids,
                }
            )

    async def plans(self, request: web.Request) -> web.Response:
        await self._authenticate(request)

        async with self.db.session() as session:
            settings = await ConnectedDeviceSettings.get_or_create(session)

            active_periods = await ServicePeriod.list_active(session)

            # Match the Bot purchase flow exactly:
            # only active/non-archived periods that have normal purchase plans.
            cards: dict[int, dict[str, object]] = {}
            durations: list[int] = []

            for period in active_periods:
                purchase_plans = await ServicePurchasePlan.list_by_type(
                    session,
                    period.service_type,
                )

                if not purchase_plans:
                    continue

                durations.append(int(period.duration_days))

                for plan in purchase_plans:
                    volume = int(plan.volume_gb)
                    card = cards.setdefault(
                        volume,
                        {
                            "devices": int(settings.max_connected_devices),
                            "prices": {"تومان": {}},
                            "plans": [],
                        },
                    )

                    days_key = str(int(plan.duration_days))
                    card["prices"]["تومان"][days_key] = int(plan.price_toman)
                    card["plans"].append(
                        {
                            "id": int(plan.id),
                            "volume_gb": volume,
                            "duration_days": int(plan.duration_days),
                            "price_toman": int(plan.price_toman),
                            "service_type": plan.service_type,
                        }
                    )

            ordered_cards = []
            for volume in sorted(cards):
                card = cards[volume]
                card["plans"].sort(
                    key=lambda x: (x["duration_days"], x["price_toman"])
                )
                ordered_cards.append(card)

            return web.json_response(
                {
                    "plans": ordered_cards,
                    "durations": sorted(set(durations)),
                    "source": "service_periods",
                    "currency": "تومان",
                }
            )

    async def service(self, request: web.Request) -> web.Response:
        tg_id, _ = await self._authenticate(request)
        try:
            subscription_id = int(request.match_info["subscription_id"])
        except (KeyError, ValueError):
            raise web.HTTPBadRequest(text="Invalid service id")

        async with self.db.session() as session:
            user = await self._get_user(session, tg_id)
            result = await session.execute(
                select(Subscription)
                .options(selectinload(Subscription.server))
                .where(
                    Subscription.id == subscription_id,
                    Subscription.user_id == user.id,
                    Subscription.server_id.is_not(None),
                )
            )
            subscription = result.scalar_one_or_none()
            if subscription is None:
                raise web.HTTPNotFound(text="Service not found")

            live = await self.services.vpn.get_client_data(user, subscription.id)
            if live is None:
                raise web.HTTPNotFound(text="Live service not found in 3X-UI")

            payload = self._serialize_live_subscription(subscription, live)
            payload["subscription_url"] = await self.services.vpn.get_key(user, subscription.id)
            return web.json_response(payload)

    async def transactions(self, request: web.Request) -> web.Response:
        tg_id, _ = await self._authenticate(request)
        try:
            limit = min(50, max(1, int(request.query.get("limit", "20"))))
        except ValueError:
            limit = 20
        async with self.db.session() as session:
            return web.json_response({"transactions": await self._recent_transactions(session, tg_id, limit)})

    async def wallet(self, request: web.Request) -> web.Response:
        tg_id, _ = await self._authenticate(request)
        return web.json_response(
            {
                "balance": await self.services.wallet.get_balance(tg_id),
                "transactions": [
                    self._serialize_wallet_transaction(item)
                    for item in await self.services.wallet.get_recent_transactions(tg_id, 30)
                ],
            }
        )

    async def support(self, request: web.Request) -> web.Response:
        tg_id, _ = await self._authenticate(request)
        async with self.db.session() as session:
            user = await self._get_user(session, tg_id)
            result = await session.execute(
                select(SupportTicket)
                .options(selectinload(SupportTicket.messages))
                .where(SupportTicket.user_id == user.id)
                .order_by(SupportTicket.updated_at.desc())
                .limit(20)
            )
            tickets = result.scalars().all()
            return web.json_response(
                {
                    "tickets": [
                        {
                            "id": ticket.id,
                            "status": ticket.status,
                            "created_at": _iso(ticket.created_at),
                            "updated_at": _iso(ticket.updated_at),
                            "messages": [
                                {
                                    "id": message.id,
                                    "sender_type": message.sender_type,
                                    "text": message.text,
                                    "created_at": _iso(message.created_at),
                                }
                                for message in ticket.messages[-30:]
                            ],
                        }
                        for ticket in tickets
                    ]
                }
            )

    async def admin_overview(self, request: web.Request) -> web.Response:
        tg_id, _ = await self._authenticate(request)
        if tg_id not in self.admin_ids:
            raise web.HTTPForbidden(text="Admin access required")
        async with self.db.session() as session:
            users = await session.scalar(select(func.count()).select_from(User)) or 0
            subscriptions = await session.scalar(select(func.count()).select_from(Subscription)) or 0
            transactions = await session.scalar(select(func.count()).select_from(Transaction)) or 0
            completed = await session.scalar(
                select(func.count()).select_from(Transaction).where(Transaction.status == "completed")
            ) or 0
            servers = await session.execute(select(Server).order_by(Server.name))
            server_rows = servers.scalars().all()
            wallet_total = await session.scalar(
                select(func.coalesce(func.sum(WalletTransaction.amount), 0))
            ) or 0
            return web.json_response(
                {
                    "users": int(users),
                    "subscriptions": int(subscriptions),
                    "transactions": int(transactions),
                    "completed_transactions": int(completed),
                    "wallet_net": int(wallet_total),
                    "servers": [
                        {
                            "id": server.id,
                            "name": server.name,
                            "location": server.location,
                            "online": server.online,
                        }
                        for server in server_rows
                    ],
                }
            )

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "service": "miniapp"})

    async def _recent_transactions(self, session, tg_id: int, limit: int) -> list[dict[str, object]]:
        result = await session.execute(
            select(Transaction)
            .where(Transaction.tg_id == tg_id)
            .order_by(Transaction.created_at.desc())
            .limit(limit)
        )
        return [
            {
                "id": item.id,
                "payment_id": item.payment_id,
                "subscription": item.subscription,
                "status": _tx_status(item.status),
                "created_at": _iso(item.created_at),
            }
            for item in result.scalars().all()
        ]

    @staticmethod
    def _serialize_wallet_transaction(item) -> dict[str, object]:
        return {
            "id": item.id,
            "amount": int(item.amount),
            "type": _tx_status(item.transaction_type),
            "created_at": _iso(item.created_at),
        }

    async def _support_summary(self, session, user_id: int) -> dict[str, object]:
        result = await session.execute(
            select(SupportTicket)
            .where(SupportTicket.user_id == user_id)
            .order_by(SupportTicket.updated_at.desc())
            .limit(8)
        )
        tickets = result.scalars().all()
        return {
            "open_count": sum(1 for ticket in tickets if ticket.status not in {"closed", "resolved"}),
            "tickets": [
                {
                    "id": ticket.id,
                    "status": ticket.status,
                    "created_at": _iso(ticket.created_at),
                    "updated_at": _iso(ticket.updated_at),
                }
                for ticket in tickets
            ],
        }

    @staticmethod
    def _build_recent_activity(services, transactions, wallet_transactions, support) -> list[dict[str, object]]:
        items: list[dict[str, object]] = []
        for item in services:
            items.append({"type": "service", "icon": "🌐", "title": item["name"], "date": item["updated_at"], "status": item["status"]})
        for item in transactions:
            items.append({"type": "transaction", "icon": "💳", "title": f"تراکنش #{item['id']}", "date": item["created_at"], "status": item["status"]})
        for item in wallet_transactions:
            items.append({"type": "wallet", "icon": "💰", "title": f"کیف پول #{item.id}", "date": _iso(item.created_at), "status": _tx_status(item.transaction_type)})
        for item in support["tickets"]:
            items.append({"type": "support", "icon": "🎧", "title": f"تیکت پشتیبانی #{item['id']}", "date": item["updated_at"], "status": item["status"]})
        return sorted(items, key=lambda item: item.get("date") or "", reverse=True)

    @staticmethod
    def _serialize_live_subscription(subscription, live) -> dict[str, object]:
        expire_date = _iso(subscription.expire_date)
        traffic_total = int(getattr(live, "traffic_total", -1) or -1)
        traffic_used = int(getattr(live, "traffic_used", 0) or 0)
        traffic_remaining = int(getattr(live, "traffic_remaining", -1) or -1)
        expired = bool(expire_date and subscription.expire_date.timestamp() <= time.time())
        enabled = subscription.status == "active" and not expired
        raw_devices = getattr(live, "max_devices", subscription.devices)
        devices = -1 if isinstance(raw_devices, str) else int(raw_devices or 0)
        return {
            "id": subscription.id,
            "name": getattr(live, "config_name", None) or subscription.config_name,
            "status": "expired" if expired else ("active" if enabled else "inactive"),
            "traffic_total": traffic_total,
            "traffic_used": traffic_used,
            "traffic_remaining": traffic_remaining,
            "traffic_up": int(getattr(live, "traffic_up", 0) or 0),
            "traffic_down": int(getattr(live, "traffic_down", 0) or 0),
            "volume_gb": subscription.volume_gb,
            "duration_days": subscription.duration_days,
            "devices": devices,
            "start_date": _iso(subscription.start_date),
            "expire_date": expire_date,
            "created_at": _iso(subscription.created_at),
            "updated_at": _iso(subscription.updated_at),
            "online": None,
            "inbound_id": getattr(live, "inbound_id", None),
            "client_id": getattr(live, "client_id", None),
            "sub_id": getattr(live, "sub_id", None),
            "flow": getattr(live, "flow", None),
            "server": (
                {
                    "name": subscription.server.name,
                    "location": subscription.server.location,
                    "online": subscription.server.online,
                }
                if subscription.server
                else None
            ),
        }


def register(
    app: web.Application,
    db,
    bot_token: str,
    admin_ids: list[int],
    services: ServicesContainer,
) -> None:
    controller = MiniAppController(db=db, bot_token=bot_token, admin_ids=admin_ids, services=services)
    app.router.add_get("/miniapp", controller.index)
    app.router.add_get("/miniapp/", controller.index)
    app.router.add_get("/miniapp/api/me", controller.me)
    app.router.add_get("/miniapp/api/plans", controller.plans)
    app.router.add_get("/miniapp/api/services/{subscription_id}", controller.service)
    app.router.add_get("/miniapp/api/transactions", controller.transactions)
    app.router.add_get("/miniapp/api/wallet", controller.wallet)
    app.router.add_get("/miniapp/api/support", controller.support)
    app.router.add_get("/miniapp/api/admin/overview", controller.admin_overview)
    app.router.add_get("/miniapp/api/health", controller.health)


__all__ = ["register", "_mini_app_url", "_validate_init_data", "MiniAppController"]
