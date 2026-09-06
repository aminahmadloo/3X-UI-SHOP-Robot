from __future__ import annotations

import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode

from aiohttp import web
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import Subscription, User


BASE_DIR = Path(__file__).resolve().parent
INDEX_FILE = BASE_DIR / "index.html"
MAX_INIT_DATA_AGE = 24 * 60 * 60


def _mini_app_url(domain: str) -> str:
    domain = domain.strip().rstrip("/")
    if not domain:
        raise ValueError("BOT_DOMAIN must be configured for Mini App")
    if not domain.startswith(("http://", "https://")):
        domain = f"https://{domain}"
    return f"{domain}/miniapp"


def _validate_init_data(init_data: str, bot_token: str) -> dict[str, str]:
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", None)
    if not received_hash:
        raise web.HTTPUnauthorized(text="Missing Telegram init data hash")

    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(pairs.items())
    )
    secret_key = hmac.new(
        b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256
    ).digest()
    expected_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(received_hash, expected_hash):
        raise web.HTTPUnauthorized(text="Invalid Telegram init data")

    try:
        auth_date = int(pairs.get("auth_date", "0"))
    except ValueError as exc:
        raise web.HTTPUnauthorized(text="Invalid auth date") from exc

    if auth_date <= 0 or time.time() - auth_date > MAX_INIT_DATA_AGE:
        raise web.HTTPUnauthorized(text="Expired Telegram init data")

    try:
        telegram_user = json.loads(pairs["user"])
    except (KeyError, json.JSONDecodeError) as exc:
        raise web.HTTPUnauthorized(text="Invalid Telegram user data") from exc

    user_id = telegram_user.get("id")
    if not isinstance(user_id, int):
        raise web.HTTPUnauthorized(text="Invalid Telegram user id")

    pairs["telegram_user"] = telegram_user
    return pairs


class MiniAppController:
    def __init__(self, db, bot_token: str, admin_ids: list[int]) -> None:
        self.db = db
        self.bot_token = bot_token
        self.admin_ids = set(admin_ids)

    async def _authenticate(self, request: web.Request) -> tuple[int, dict]:
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        if not init_data:
            raise web.HTTPUnauthorized(text="Telegram Mini App authentication required")

        validated = _validate_init_data(init_data, self.bot_token)
        telegram_user = validated["telegram_user"]
        tg_id = int(telegram_user["id"])
        if tg_id not in self.admin_ids:
            raise web.HTTPForbidden(text="Mini App is currently available to admins only")
        return tg_id, telegram_user

    async def index(self, request: web.Request) -> web.StreamResponse:
        if not INDEX_FILE.exists():
            raise web.HTTPNotFound(text="Mini App frontend not found")
        return web.FileResponse(INDEX_FILE)

    async def me(self, request: web.Request) -> web.Response:
        tg_id, telegram_user = await self._authenticate(request)
        async with self.db.session() as session:  # type: AsyncSession
            user = await User.get(session=session, tg_id=tg_id)
            if user is None:
                raise web.HTTPNotFound(text="User not found")

            result = await session.execute(
                select(Subscription)
                .options(selectinload(Subscription.server))
                .where(Subscription.user_id == user.id)
                .order_by(Subscription.created_at.desc())
            )
            subscriptions = list(result.scalars().all())

            active = [
                item for item in subscriptions
                if item.status == "active" and item.expire_date is not None
            ]
            active.sort(key=lambda item: item.expire_date or 0, reverse=True)

            return web.json_response(
                {
                    "user": {
                        "id": user.tg_id,
                        "first_name": user.first_name,
                        "username": user.username,
                        "language_code": user.language_code,
                        "created_at": user.created_at.isoformat(),
                    },
                    "telegram": {
                        "first_name": telegram_user.get("first_name"),
                        "username": telegram_user.get("username"),
                        "photo_url": telegram_user.get("photo_url"),
                    },
                    "dashboard": {
                        "total_services": len(subscriptions),
                        "active_services": len(active),
                        "expired_services": sum(1 for item in subscriptions if item.status != "active"),
                    },
                    "services": [self._serialize_subscription(item) for item in subscriptions],
                }
            )

    @staticmethod
    def _serialize_subscription(subscription: Subscription) -> dict:
        return {
            "id": subscription.id,
            "name": subscription.config_name,
            "status": subscription.status,
            "volume_gb": subscription.volume_gb,
            "duration_days": subscription.duration_days,
            "devices": subscription.devices,
            "start_date": subscription.start_date.isoformat() if subscription.start_date else None,
            "expire_date": subscription.expire_date.isoformat() if subscription.expire_date else None,
            "server": {
                "name": subscription.server.name,
                "location": subscription.server.location,
                "online": subscription.server.online,
            } if subscription.server else None,
        }

    async def health(self, request: web.Request) -> web.Response:
        await self._authenticate(request)
        async with self.db.session() as session:  # type: AsyncSession
            await session.execute(select(User.id).limit(1))
        return web.json_response({"ok": True, "database": "ok"})


def register(app: web.Application, db, bot_token: str, admin_ids: list[int]) -> None:
    controller = MiniAppController(db=db, bot_token=bot_token, admin_ids=admin_ids)
    app.router.add_get("/miniapp", controller.index)
    app.router.add_get("/miniapp/", controller.index)
    app.router.add_get("/miniapp/api/me", controller.me)
    app.router.add_get("/miniapp/api/health", controller.health)


__all__ = ["register", "_mini_app_url"]
