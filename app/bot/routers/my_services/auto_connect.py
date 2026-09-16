from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from urllib.parse import quote

import qrcode
from aiogram import F, Router
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    CopyTextButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    TelegramObject,
)
from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import ServicesContainer
from app.bot.utils.navigation import NavMain, NavSupport
from app.db.models import Server, Subscription, User

logger = logging.getLogger(__name__)

router = Router(name="my_services_auto_connect")


# Client list is deliberately limited to clients for which a documented,
# usable import URL scheme exists. Apps that only support copy/paste or QR
# import are not presented as "automatic" clients.
CLIENTS: dict[str, dict[str, str]] = {
    "android": {
        "v2rayng": "V2RayNG",
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
    """Build a client-specific subscription import URL."""
    encoded_url = quote(subscription_url, safe="")
    encoded_name = quote(name or "ToonelVPN", safe="")

    if client == "v2rayng":
        return f"v2rayng://install-sub?url={encoded_url}"
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


def _platform_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📱 Android", callback_data="my_services:auto:platform:android"),
        InlineKeyboardButton(text="🍎 iOS", callback_data="my_services:auto:platform:ios"),
    )
    builder.row(
        InlineKeyboardButton(text="⬅️ بازگشت به جزئیات سرویس", callback_data="my_services:auto:back"),
    )
    return builder.as_markup()


def _clients_keyboard(platform: str, subscription_url: str, name: str, subscription_id: int | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for client_key, label in CLIENTS.get(platform, {}).items():
        deep_link = _client_deep_link(client_key, subscription_url, name)
        if deep_link:
            builder.row(InlineKeyboardButton(text=label, url=deep_link))

    back_data = "my_services:auto:back"
    if subscription_id is not None:
        back_data = f"my_services:view:{subscription_id}"
    builder.row(InlineKeyboardButton(text="⬅️ بازگشت", callback_data=back_data))
    return builder.as_markup()


async def _active_subscription(
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    subscription_id: int | None = None,
) -> tuple[Subscription | None, str | None]:
    query = select(Subscription).where(
        Subscription.user_id == user.id,
        Subscription.status == "active",
        Subscription.server_id.is_not(None),
    )
    if subscription_id is not None:
        query = query.where(Subscription.id == subscription_id)
    else:
        query = query.order_by(Subscription.id.desc())

    result = await session.execute(query.limit(1))
    subscription = result.scalar_one_or_none()
    if not subscription:
        return None, None

    key = await services.vpn.get_key(user, subscription_id=subscription.id)
    if not key:
        return None, None
    return subscription, key


async def _show_platforms(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    subscription_id: int | None = None,
) -> None:
    subscription, key = await _active_subscription(user, session, services, subscription_id)
    if not subscription or not key:
        await callback.answer("این سرویس فعال نیست یا لینک اتصال در دسترس نیست.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        text="📱 <b>اتصال خودکار</b>\n\nسیستم‌عامل دستگاهت را انتخاب کن:",
        reply_markup=_platform_keyboard(),
    )


@router.callback_query(F.data.regexp(r"^my_services:auto:(?:last|\d+)$"))
async def callback_auto_connect_entry(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    subscription_id = None
    if callback.data and callback.data.rsplit(":", 1)[-1].isdigit():
        subscription_id = int(callback.data.rsplit(":", 1)[-1])
    await _show_platforms(callback, user, session, services, subscription_id)


@router.callback_query(F.data == "my_services:auto:platform:android")
@router.callback_query(F.data == "my_services:auto:platform:ios")
async def callback_auto_connect_platform(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    platform = callback.data.rsplit(":", 1)[1]
    subscription, key = await _active_subscription(user, session, services)
    if not subscription or not key:
        await callback.answer("این سرویس فعال نیست یا لینک اتصال در دسترس نیست.", show_alert=True)
        return

    await callback.answer()
    platform_title = "Android" if platform == "android" else "iOS"
    await callback.message.edit_text(
        text=(
            f"📱 <b>{platform_title}</b>\n\n"
            "برنامه‌ای را که روی دستگاهت نصب داری انتخاب کن:"
        ),
        reply_markup=_clients_keyboard(
            platform,
            key,
            subscription.config_name,
            subscription.id,
        ),
    )


@router.callback_query(F.data == "my_services:auto:back")
async def callback_auto_connect_back(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    # Re-use the existing service-detail handler rather than duplicating its
    # presentation/data logic. The callback is routed to the original handler.
    subscription_result = await session.execute(
        select(Subscription.id)
        .where(
            Subscription.user_id == user.id,
            Subscription.status == "active",
        )
        .order_by(Subscription.id.desc())
        .limit(1)
    )
    subscription_id = subscription_result.scalar_one_or_none()
    if subscription_id is None:
        await callback.answer()
        await callback.message.edit_text(
            "📦 <b>سرویس‌های من</b>",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)]
                ]
            ),
        )
        return

    await callback.answer()
    # The normal detail handler is registered on the same router. Calling it
    # through the callback data is not possible from inside a handler, so the
    # safest minimal path is to expose a direct link back to the detail page.
    await callback.message.edit_text(
        "برای بازگشت، دکمه زیر را بزن:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📦 جزئیات سرویس", callback_data=f"my_services:view:{subscription_id}")],
                [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)],
            ]
        ),
    )


@router.callback_query(F.data.regexp(r"^my_services:auto:(?:copy|qr|refresh):last$"))
async def callback_auto_connect_success_action(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    action = callback.data.split(":")[2]
    subscription, key = await _active_subscription(user, session, services)
    if not subscription or not key:
        await callback.answer("این سرویس فعال نیست یا لینک اتصال در دسترس نیست.", show_alert=True)
        return

    if action == "copy":
        await callback.answer("لینک اتصال آماده است؛ از دکمه کپی استفاده کن.")
        return

    if action == "refresh":
        await callback.answer("🔄 لینک اتصال بروزرسانی شد.")
        await callback.message.edit_text(
            text=_("payment:message:purchase_success").format(key=key),
            reply_markup=payment_success_keyboard_for_key(key),
        )
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
    """Replace only the detail keyboard after the existing handler completes.

    The existing service-detail handler remains the source of truth for all
    text, synchronization, status rules and existing callbacks. This middleware
    only inserts the new Auto Connect and Training actions while preserving the
    established active/inactive button behavior.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        result = await handler(event, data)

        if not isinstance(event, CallbackQuery) or not event.data:
            return result
        if not event.data.startswith("my_services:view:"):
            return result
        if event.message is None:
            return result

        try:
            subscription_id = int(event.data.rsplit(":", 1)[1])
            user: User = data["user"]
            session: AsyncSession = data["session"]
            result = await session.execute(
                select(Subscription).where(
                    Subscription.id == subscription_id,
                    Subscription.user_id == user.id,
                    Subscription.server_id.is_not(None),
                )
            )
            subscription = result.scalar_one_or_none()
            if subscription is None:
                return result

            from app.bot.routers.my_services.handler import _status

            _, status_text = _status(subscription)
            builder = InlineKeyboardBuilder()
            builder.row(
                InlineKeyboardButton(
                    text="📱 اتصال خودکار",
                    callback_data=f"my_services:auto:{subscription.id}",
                )
            )

            if subscription.status == "active" and status_text not in {"منقضی شده", "غیرفعال"}:
                builder.row(
                    InlineKeyboardButton(
                        text="🔗 دریافت لینک اتصال",
                        callback_data=f"my_services:key:{subscription.id}",
                    )
                )
                builder.row(
                    InlineKeyboardButton(
                        text="🔄 تمدید سرویس",
                        callback_data=f"main_renewal:service:{subscription.id}",
                    )
                )

            builder.row(
                InlineKeyboardButton(text="🛒 خرید سرویس جدید", callback_data="buy")
            )
            builder.row(
                InlineKeyboardButton(text="📚 راهنمای اتصال", callback_data=NavSupport.TRAINING)
            )
            builder.row(
                InlineKeyboardButton(text="⬅️ بازگشت به سرویس‌های من", callback_data=NavMain.MY_SERVICES)
            )
            builder.row(
                InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data=NavMain.MAIN_MENU, style="danger")
            )

            await event.message.edit_reply_markup(reply_markup=builder.as_markup())
        except Exception:
            logger.exception("Failed to augment My Services detail keyboard")

        return result


def install() -> None:
    from app.bot.routers.my_services import handler as my_services_handler
    from app.bot.services import notification as notification_module

    if router not in my_services_handler.router.sub_routers:
        my_services_handler.router.include_router(router)

    if not getattr(my_services_handler.router, "_auto_connect_keyboard_middleware", False):
        my_services_handler.router.callback_query.outer_middleware(
            MyServicesDetailsKeyboardMiddleware()
        )
        setattr(my_services_handler.router, "_auto_connect_keyboard_middleware", True)

    notification_module.payment_success_keyboard = payment_success_keyboard_for_key
