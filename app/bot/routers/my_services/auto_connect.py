from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import os
from io import BytesIO
from urllib.parse import quote

import qrcode
from aiogram import F, Router
from aiogram.types import BufferedInputFile, CallbackQuery, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiohttp import web
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.models import ServicesContainer
from app.bot.utils.navigation import NavMain, NavSupport
from app.db.models import Subscription, User

logger = logging.getLogger(__name__)
router = Router(name="my_services_auto_connect")

CLIENTS: dict[str, dict[str, str]] = {
    "android": {
        "v2rayng": "V2RayNG",
        "nekobox": "NekoBox",
        "v2box": "V2Box",
        "hiddify": "Hiddify",
        "singbox": "sing-box",
        "v2raytun": "V2RayTun",
        "happ": "Happ",
        "incy": "Incy",
    },
    "ios": {
        "shadowrocket": "Shadowrocket",
        "v2box": "V2Box",
        "hiddify": "Hiddify",
        "singbox": "sing-box",
        "v2raytun": "V2RayTun",
        "happ": "Happ",
        "incy": "Incy",
        "streisand": "Streisand",
    },
}

_GATEWAY_BASE_URL = os.getenv(
    "AUTO_CONNECT_GATEWAY_BASE_URL",
    "https://sub.elfuu.ir/connect",
).rstrip("/")


def _client_deep_link(client: str, subscription_url: str, name: str) -> str | None:
    encoded_url = quote(subscription_url, safe="")
    encoded_name = quote(name or "ToonelVPN", safe="")
    if client == "v2rayng":
        return f"v2rayng://install-sub?url={encoded_url}"
    if client == "nekobox":
        return f"clash://install-config?url={encoded_url}&name={encoded_name}"
    if client == "v2box":
        return f"v2box://install-sub?url={encoded_url}&name={encoded_name}"
    if client == "hiddify":
        return f"hiddify://import/{subscription_url}#{encoded_name}"
    if client == "singbox":
        return f"sing-box://import-remote-profile?url={encoded_url}#{encoded_name}"
    if client == "v2raytun":
        return f"v2raytun://import/{subscription_url}"
    if client == "happ":
        return f"happ://add/{subscription_url}"
    if client == "incy":
        return f"incy://add/{subscription_url}"
    if client == "shadowrocket":
        return f"shadowrocket://add/{subscription_url}"
    if client == "streisand":
        return f"streisand://import/{subscription_url}"
    return None


def _gateway_token(subscription_id: int, client: str, secret: str) -> str:
    payload = f"{subscription_id}:{client}".encode()
    encoded_payload = base64.urlsafe_b64encode(payload).decode().rstrip("=")
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()[:32]
    return f"{encoded_payload}.{signature}"


def _parse_gateway_token(token: str, secret: str) -> tuple[int, str] | None:
    try:
        encoded_payload, signature = token.split(".", 1)
        payload = base64.urlsafe_b64decode(encoded_payload + "=" * (-len(encoded_payload) % 4))
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()[:32]
        if not hmac.compare_digest(signature, expected):
            return None
        subscription_id_text, client = payload.decode().split(":", 1)
        subscription_id = int(subscription_id_text)
        if client not in {key for clients in CLIENTS.values() for key in clients}:
            return None
        return subscription_id, client
    except (ValueError, UnicodeDecodeError, base64.binascii.Error):
        return None


def _gateway_url(subscription_id: int, client: str, secret: str) -> str:
    return f"{_GATEWAY_BASE_URL}/{_gateway_token(subscription_id, client, secret)}"


def register_gateway(
    app: web.Application,
    session_factory: async_sessionmaker[AsyncSession],
    services: ServicesContainer,
    secret: str,
) -> None:
    if getattr(app, "_auto_connect_gateway_registered", False):
        return

    async def redirect_to_client(request: web.Request) -> web.StreamResponse:
        token = request.match_info.get("token", "")
        parsed = _parse_gateway_token(token, secret)
        if parsed is None:
            raise web.HTTPNotFound(text="Invalid or expired connection link")

        subscription_id, client = parsed
        async with session_factory() as session:
            result = await session.execute(
                select(Subscription, User)
                .join(User, Subscription.user_id == User.id)
                .where(
                    Subscription.id == subscription_id,
                    Subscription.status == "active",
                    Subscription.server_id.is_not(None),
                )
            )
            row = result.first()
            if row is None:
                raise web.HTTPGone(text="Subscription is not active")
            subscription, user = row
            key = await services.vpn.get_key(user, subscription_id=subscription.id)

        if not key:
            raise web.HTTPGone(text="Subscription link is unavailable")

        deep_link = _client_deep_link(client, key, subscription.config_name)
        if not deep_link:
            raise web.HTTPNotFound(text="Client is not supported")

        raise web.HTTPFound(
            location=deep_link,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    app.router.add_get("/connect/{token}", redirect_to_client)
    setattr(app, "_auto_connect_gateway_registered", True)


async def _active_subscription(
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    subscription_id: int,
) -> tuple[Subscription | None, str | None]:
    result = await session.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
            Subscription.status == "active",
            Subscription.server_id.is_not(None),
        )
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        return None, None
    key = await services.vpn.get_key(user, subscription_id=subscription.id)
    return (subscription, key) if key else (None, None)


def _platform_keyboard(subscription_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📱 Android", callback_data=f"my_services:auto:platform:android:{subscription_id}"),
        InlineKeyboardButton(text="🍎 iOS", callback_data=f"my_services:auto:platform:ios:{subscription_id}"),
    )
    builder.row(InlineKeyboardButton(text="⬅️ بازگشت به جزئیات سرویس", callback_data=f"my_services:view:{subscription_id}"))
    return builder.as_markup()


def _clients_keyboard(platform: str, subscription: Subscription, key: str, secret: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for client, label in CLIENTS.get(platform, {}).items():
        if _client_deep_link(client, key, subscription.config_name):
            builder.row(
                InlineKeyboardButton(
                    text=label,
                    url=_gateway_url(subscription.id, client, secret),
                )
            )
    builder.row(InlineKeyboardButton(text="⬅️ بازگشت به انتخاب سیستم‌عامل", callback_data=f"my_services:auto:{subscription.id}"))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت به جزئیات سرویس", callback_data=f"my_services:view:{subscription.id}"))
    return builder.as_markup()


@router.callback_query(F.data.regexp(r"^my_services:auto:\d+$"))
async def callback_auto_connect_entry(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    subscription_id = int(callback.data.rsplit(":", 1)[1])
    subscription, key = await _active_subscription(user, session, services, subscription_id)
    if not subscription or not key:
        await callback.answer("این سرویس فعال نیست یا لینک اتصال در دسترس نیست.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "📱 <b>اتصال خودکار</b>\n\nسیستم‌عامل دستگاهت را انتخاب کن:",
        reply_markup=_platform_keyboard(subscription.id),
    )


@router.callback_query(F.data.regexp(r"^my_services:auto:platform:(android|ios):\d+$"))
async def callback_auto_connect_platform(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    config,
) -> None:
    parts = callback.data.split(":")
    platform, subscription_id = parts[3], int(parts[4])
    subscription, key = await _active_subscription(user, session, services, subscription_id)
    if not subscription or not key:
        await callback.answer("این سرویس فعال نیست یا لینک اتصال در دسترس نیست.", show_alert=True)
        return
    title = "Android" if platform == "android" else "iOS"
    await callback.answer()
    await callback.message.edit_text(
        f"📱 <b>{title}</b>\n\nبرنامه‌ای را که روی دستگاهت نصب داری انتخاب کن:",
        reply_markup=_clients_keyboard(platform, subscription, key, config.bot.TOKEN),
    )


@router.callback_query(F.data.regexp(r"^my_services:auto:qr:\d+$"))
async def callback_success_qr(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    subscription_id = int(callback.data.rsplit(":", 1)[1])
    subscription, key = await _active_subscription(user, session, services, subscription_id)
    if not subscription or not key:
        await callback.answer("این سرویس فعال نیست یا لینک اتصال در دسترس نیست.", show_alert=True)
        return
    qr = qrcode.make(key)
    output = BytesIO()
    qr.save(output, format="PNG")
    output.seek(0)
    await callback.answer()
    sent = await callback.message.answer_photo(
        BufferedInputFile(output.read(), filename="toonelvpn-subscription-qr.png"),
        caption=f"📷 <b>QR Code اتصال</b>\n\n<code>{key}</code>",
    )
    asyncio.create_task(_delete_later(sent, 30))


@router.callback_query(F.data.regexp(r"^my_services:auto:refresh:\d+$"))
async def callback_success_refresh(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    config,
) -> None:
    subscription_id = int(callback.data.rsplit(":", 1)[1])
    subscription, key = await _active_subscription(user, session, services, subscription_id)
    if not subscription or not key:
        await callback.answer("این سرویس فعال نیست یا لینک اتصال در دسترس نیست.", show_alert=True)
        return
    await callback.answer("🔄 لینک اتصال بروزرسانی شد.")
    await callback.message.edit_text(
        _("payment:message:purchase_success").format(key=key),
        reply_markup=payment_success_keyboard_for_key(subscription.id, key, config.bot.TOKEN),
    )


async def _delete_later(message, delay: int) -> None:
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        logger.debug("Could not delete temporary auto-connect QR message", exc_info=True)


def payment_success_keyboard_for_key(
    subscription_id: int,
    key: str,
    secret: str,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📱 اتصال خودکار", callback_data=f"my_services:auto:{subscription_id}"))
    builder.row(InlineKeyboardButton(text="📋 کپی لینک", copy_text=CopyTextButton(text=key)))
    builder.row(InlineKeyboardButton(text="📷 QR Code", callback_data=f"my_services:auto:qr:{subscription_id}"))
    builder.row(InlineKeyboardButton(text="🔄 بروزرسانی", callback_data=f"my_services:auto:refresh:{subscription_id}"))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data=NavMain.MAIN_MENU))
    return builder.as_markup()
