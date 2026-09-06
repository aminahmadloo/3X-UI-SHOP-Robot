from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.bot.routers.my_services.handler import _discover_user_subscriptions_from_xui
from app.db.models import Subscription, User

BASE_DIR = Path(__file__).resolve().parent
INDEX_FILE = BASE_DIR / "miniapp" / "index.html"
MAX_INIT_DATA_AGE = 60 * 60
MAX_CLOCK_SKEW = 60
HEX_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


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


class MiniAppController:
    def __init__(self, db, bot_token: str, admin_ids: list[int], vpn_service=None, services=None) -> None:
        self.db = db
        self.bot_token = bot_token
        self.admin_ids = {int(admin_id) for admin_id in admin_ids}
        self.vpn_service = vpn_service
        self.services = services

    async def _authenticate(self, request: web.Request) -> tuple[int, dict[str, object]]:
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        if not init_data:
            raise web.HTTPUnauthorized(text="Telegram Mini App authentication required")
        validated = _validate_init_data(init_data, self.bot_token)
        telegram_user = validated["telegram_user"]
        assert isinstance(telegram_user, dict)
        tg_id = int(telegram_user["id"])
        # Keep this gate until the Mini App is approved for customer rollout.
        if tg_id not in self.admin_ids:
            raise web.HTTPForbidden(text="Mini App is currently available to admins only")
        return tg_id, telegram_user

    async def index(self, request: web.Request) -> web.StreamResponse:
        if not INDEX_FILE.is_file():
            raise web.HTTPNotFound(text="Mini App frontend not found")
        return web.FileResponse(INDEX_FILE)

    async def me(self, request: web.Request) -> web.Response:
        tg_id, telegram_user = await self._authenticate(request)
        if self.vpn_service is None or self.services is None:
            raise web.HTTPServiceUnavailable(text="Mini App VPN services are not initialized")
        async with self.db.session() as session:
            user = await User.get(session=session, tg_id=tg_id)
            if user is None:
                raise web.HTTPNotFound(text="User not found")
            # Reuse the same live-XUI discovery used by My Services. Local DB rows
            # are not treated as the source of truth for what the user owns now.
            await _discover_user_subscriptions_from_xui(session, user, self.services)
            await session.commit()
            result = await session.execute(
                select(Subscription)
                .options(selectinload(Subscription.server))
                .where(Subscription.user_id == user.id, Subscription.server_id.is_not(None))
                .order_by(Subscription.id.desc())
            )
            subscriptions = list(result.scalars().all())
            services_payload: list[dict[str, object]] = []
            for subscription in subscriptions:
                live = await self.vpn_service.get_client_data(user, subscription.id)
                if live is None:
                    continue
                services_payload.append(self._serialize_live_subscription(subscription, live))
            active = [item for item in services_payload if item["status"] == "active"]
            expired = [item for item in services_payload if item["status"] == "expired"]
            nearest = min((item for item in services_payload if item.get("expire_date")), key=lambda item: item["expire_date"], default=None)
            servers = []
            seen_servers = set()
            for item in services_payload:
                server = item.get("server") or {}
                key = (server.get("name"), server.get("location"))
                if key not in seen_servers:
                    seen_servers.add(key)
                    servers.append(server)
            used = sum(int(item.get("traffic_used", 0) or 0) for item in services_payload)
            total = sum(int(item.get("traffic_total", 0) or 0) for item in services_payload if int(item.get("traffic_total", 0) or 0) > 0)
            recent = sorted([{"type": "service", "title": item["name"], "date": item.get("updated_at") or item.get("created_at"), "status": item["status"]} for item in services_payload], key=lambda item: item["date"] or "", reverse=True)[:5]
            return web.json_response({
                "user": {"id": user.tg_id, "first_name": user.first_name, "username": user.username, "language_code": user.language_code, "created_at": user.created_at.isoformat()},
                "telegram": {"first_name": telegram_user.get("first_name"), "username": telegram_user.get("username"), "photo_url": telegram_user.get("photo_url")},
                "dashboard": {
                    "total_services": len(services_payload), "active_services": len(active), "expired_services": len(expired),
                    "traffic_used": used, "traffic_total": total, "traffic_remaining": max(0, total - used) if total else -1,
                    "nearest_expiry": nearest.get("expire_date") if nearest else None, "servers": servers, "recent_activity": recent, "generated_at": time.time(),
                },
                "services": services_payload,
            })

    async def service(self, request: web.Request) -> web.Response:
        tg_id, _ = await self._authenticate(request)
        if self.vpn_service is None:
            raise web.HTTPServiceUnavailable(text="Mini App VPN service is not initialized")
        try:
            subscription_id = int(request.match_info["subscription_id"])
        except (KeyError, ValueError):
            raise web.HTTPBadRequest(text="Invalid service id")
        async with self.db.session() as session:
            user = await User.get(session=session, tg_id=tg_id)
            if user is None:
                raise web.HTTPNotFound(text="User not found")
            result = await session.execute(select(Subscription).options(selectinload(Subscription.server)).where(Subscription.id == subscription_id, Subscription.user_id == user.id))
            subscription = result.scalar_one_or_none()
            if subscription is None:
                raise web.HTTPNotFound(text="Service not found")
            live = await self.vpn_service.get_client_data(user, subscription.id)
            if live is None:
                raise web.HTTPNotFound(text="Live service not found in 3X-UI")
            payload = self._serialize_live_subscription(subscription, live)
            payload["subscription_url"] = await self.vpn_service.get_key(user, subscription.id)
            return web.json_response(payload)

    @staticmethod
    def _serialize_live_subscription(subscription, live) -> dict[str, object]:
        expire_date = subscription.expire_date.isoformat() if subscription.expire_date else None
        traffic_total = int(getattr(live, "traffic_total", -1) or -1)
        traffic_used = int(getattr(live, "traffic_used", 0) or 0)
        traffic_remaining = int(getattr(live, "traffic_remaining", -1) or -1)
        expired = bool(expire_date and subscription.expire_date.timestamp() <= time.time())
        enabled = subscription.status == "active" and not expired
        raw_devices = getattr(live, "max_devices", subscription.devices)
        devices = -1 if isinstance(raw_devices, str) else int(raw_devices or 0)
        return {
            "id": subscription.id, "name": getattr(live, "config_name", None) or subscription.config_name,
            "status": "expired" if expired else ("active" if enabled else "inactive"),
            "traffic_total": traffic_total, "traffic_used": traffic_used, "traffic_remaining": traffic_remaining,
            "volume_gb": subscription.volume_gb, "duration_days": subscription.duration_days, "devices": devices,
            "start_date": subscription.start_date.isoformat() if subscription.start_date else None, "expire_date": expire_date,
            "created_at": subscription.created_at.isoformat() if subscription.created_at else None, "updated_at": subscription.updated_at.isoformat() if subscription.updated_at else None,
            "online": None, "inbound_id": getattr(live, "inbound_id", None), "client_id": getattr(live, "client_id", None),
            "server": {"name": subscription.server.name, "location": subscription.server.location, "online": subscription.server.online} if subscription.server else None,
        }

    async def health(self, request: web.Request) -> web.Response:
        await self._authenticate(request)
        async with self.db.session() as session:
            await session.execute(select(User.id).limit(1))
        return web.json_response({"ok": True, "database": "ok"})


def register(app: web.Application, db, bot_token: str, admin_ids: list[int], vpn_service=None, services=None) -> None:
    controller = MiniAppController(db=db, bot_token=bot_token, admin_ids=admin_ids, vpn_service=vpn_service, services=services)
    app.router.add_get("/miniapp", controller.index)
    app.router.add_get("/miniapp/", controller.index)
    app.router.add_get("/miniapp/api/me", controller.me)
    app.router.add_get("/miniapp/api/services/{subscription_id}", controller.service)
    app.router.add_get("/miniapp/api/health", controller.health)


__all__ = ["register", "_mini_app_url", "_validate_init_data", "MiniAppController"]
