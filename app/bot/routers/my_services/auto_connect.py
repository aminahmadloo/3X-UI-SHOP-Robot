from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from io import BytesIO
from typing import Any
from urllib.parse import quote

import qrcode
from aiogram import F, Router
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import BufferedInputFile, CallbackQuery, CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup, TelegramObject
from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def _active_subscription(user: User, session: AsyncSession, services: ServicesContainer, subscription_id: int | None = None) -> tuple[Subscription | None, str | None]:
    query = select(Subscription).where(
        Subscription.user_id == user.id,
        Subscription.status == "active",
        Subscription.server_id.is_not(None),
    )
    if subscription_id is None:
        query = query.order_by(Subscription.id.desc())
    else:
        query = query.where(Subscription.id == subscription_id)
    result = await session.execute(query.limit(1))
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


def _clients_keyboard(platform: str, subscription: Subscription, key: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for client, label in CLIENTS.get(platform, {}).items():
        deep_link = _client_deep_link(client, key, subscription.config_name)
        if deep_link:
            builder.row(InlineKeyboardButton(text=label, url=deep_link))
    builder.row(InlineKeyboardButton(text="⬅️ بازگشت به انتخاب سیستم‌عامل", callback_data=f"my_services:auto:{subscription.id}"))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت به جزئیات سرویس", callback_data=f"my_services:view:{subscription.id}"))
    return builder.as_markup()


@router.callback_query(F.data.regexp(r"^my_services:auto:(?:last|\d+)$"))
async def callback_auto_connect_entry(callback: CallbackQuery, user: User, session: AsyncSession, services: ServicesContainer) -> None:
    subscription_id = None
    if callback.data and callback.data.rsplit(":", 1)[-1].isdigit():
        subscription_id = int(callback.data.rsplit(":", 1)[-1])
    subscription, key = await _active_subscription(user, session, services, subscription_id)
    if not subscription or not key:
        await callback.answer("این سرویس فعال نیست یا لینک اتصال در دسترس نیست.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text("📱 <b>اتصال خودکار</b>\n\nسیستم‌عامل دستگاهت را انتخاب کن:", reply_markup=_platform_keyboard(subscription.id))


@router.callback_query(F.data.regexp(r"^my_services:auto:platform:(android|ios):\d+$"))
async def callback_auto_connect_platform(callback: CallbackQuery, user: User, session: AsyncSession, services: ServicesContainer) -> None:
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
        reply_markup=_clients_keyboard(platform, subscription, key),
    )


@router.callback_query(F.data.regexp(r"^my_services:auto:(?:qr|refresh):last$"))
async def callback_success_subscription_action(callback: CallbackQuery, user: User, session: AsyncSession, services: ServicesContainer) -> None:
    action = callback.data.split(":")[2]
    subscription, key = await _active_subscription(user, session, services)
    if not subscription or not key:
        await callback.answer("این سرویس فعال نیست یا لینک اتصال در دسترس نیست.", show_alert=True)
        return
    if action == "refresh":
        await callback.answer("🔄 لینک اتصال بروزرسانی شد.")
        await callback.message.edit_text(_("payment:message:purchase_success").format(key=key), reply_markup=payment_success_keyboard_for_key(key))
        return
    qr = qrcode.make(key)
    output = BytesIO()
    qr.save(output, format="PNG")
    output.seek(0)
    await callback.answer()
    sent = await callback.message.answer_photo(BufferedInputFile(output.read(), filename="toonelvpn-subscription-qr.png"), caption=f"📷 <b>QR Code اتصال</b>\n\n<code>{key}</code>")
    asyncio.create_task(_delete_later(sent, 30))


async def _delete_later(message, delay: int) -> None:
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except Exception:
        logger.debug("Could not delete temporary auto-connect QR message", exc_info=True)


def payment_success_keyboard_for_key(key: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📱 اتصال خودکار", callback_data="my_services:auto:last"))
    builder.row(InlineKeyboardButton(text="📋 کپی لینک", copy_text=CopyTextButton(text=key)))
    builder.row(InlineKeyboardButton(text="📷 QR Code", callback_data="my_services:auto:qr:last"))
    builder.row(InlineKeyboardButton(text="🔄 بروزرسانی", callback_data="my_services:auto:refresh:last"))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data=NavMain.MAIN_MENU))
    return builder.as_markup()


class MyServicesDetailsKeyboardMiddleware(BaseMiddleware):
    async def __call__(self, handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]], event: TelegramObject, data: dict[str, Any]) -> Any:
        result = await handler(event, data)
        if not isinstance(event, CallbackQuery) or not event.data or not event.data.startswith("my_services:view:") or event.message is None:
            return result
        try:
            subscription_id = int(event.data.rsplit(":", 1)[1])
            user: User = data["user"]
            session: AsyncSession = data["session"]
            query_result = await session.execute(select(Subscription).where(Subscription.id == subscription_id, Subscription.user_id == user.id, Subscription.server_id.is_not(None)))
            subscription = query_result.scalar_one_or_none()
            if subscription is None:
                return result
            from app.bot.routers.my_services.handler import _status
            _, status_text = _status(subscription)
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text="📱 اتصال خودکار", callback_data=f"my_services:auto:{subscription.id}"))
            if subscription.status == "active" and status_text not in {"منقضی شده", "غیرفعال"}:
                builder.row(InlineKeyboardButton(text="🔗 دریافت لینک اتصال", callback_data=f"my_services:key:{subscription.id}"))
                builder.row(InlineKeyboardButton(text="🔄 تمدید سرویس", callback_data=f"main_renewal:service:{subscription.id}"))
            builder.row(InlineKeyboardButton(text="🛒 خرید سرویس جدید", callback_data="buy"))
            builder.row(InlineKeyboardButton(text="📚 راهنمای اتصال", callback_data=NavSupport.TRAINING))
            builder.row(InlineKeyboardButton(text="⬅️ بازگشت به سرویس‌های من", callback_data=NavMain.MY_SERVICES))
            builder.row(InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data=NavMain.MAIN_MENU, style="danger"))
            await event.message.edit_reply_markup(reply_markup=builder.as_markup())
        except Exception:
            logger.exception("Failed to augment My Services detail keyboard")
        return result
