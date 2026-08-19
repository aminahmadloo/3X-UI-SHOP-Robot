from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.models import ServicesContainer
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import Server, Subscription, SubscriptionSettings, User

from .handler import (
    _days_left,
    _effective_expire_date,
    _effective_start_date,
    _format_bytes,
    _progress,
    _status,
    _sync_subscriptions_with_xui,
    _time_progress,
)

logger = logging.getLogger(__name__)
router = Router(name=__name__)


async def _set_subscription_client_enabled(
    subscription: Subscription,
    enabled: bool,
    services: ServicesContainer,
) -> bool:
    if not subscription.server:
        return False

    client_id = str(subscription.client_id or "").strip()
    if not client_id:
        return False

    connection = await services.server_pool.get_connection_for_server(subscription.server)
    if connection is None:
        return False

    try:
        inbounds = await connection.api.inbound.get_list()
        matches = []

        for inbound in inbounds:
            for client in inbound.settings.clients or []:
                if str(client.id or "").strip() == client_id or str(client.sub_id or "").strip() == client_id:
                    matches.append((client, inbound))

        if not matches:
            logger.warning(
                "Subscription %s client %s was not found on XUI server %s.",
                subscription.id,
                client_id,
                subscription.server.name,
            )
            return False

        for client, _inbound in matches:
            if not client.id:
                continue
            client.enable = enabled
            await connection.api.client.update(
                client_uuid=client.id,
                client=client,
            )

        return True
    except Exception as exception:
        logger.error(
            "Failed to change client %s for subscription %s on server %s: %s",
            client_id,
            subscription.id,
            subscription.server.name,
            exception,
        )
        return False


async def _render_details(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    subscription: Subscription,
) -> None:
    settings = await SubscriptionSettings.get_or_create(session)
    icon, status_text = _status(subscription)
    days = _days_left(subscription)
    server_name = subscription.server.name if subscription.server else "نامشخص"
    expire = _effective_expire_date(subscription)
    time_bar = _time_progress(subscription)
    client_data = await services.vpn.get_client_data(user, subscription_id=subscription.id)

    text = (
        "📦 <b>جزئیات سرویس</b>\n\n"
        "      ━━━━━━━━━━━━━━\n"
        f"{icon} <b>وضعیت:</b> {status_text}\n\n"
        f"📌 <b>نام سرویس:</b>\n<code>{subscription.config_name}</code>\n\n"
        f"💾 <b>حجم کل:</b> {subscription.volume_gb} GB\n"
        f"📅 <b>مدت:</b> {subscription.duration_days} روز\n"
        f"📱 <b>دستگاه مجاز:</b> {subscription.devices}\n"
        f"🖥 <b>سرور:</b> {server_name}\n"
    )

    if client_data:
        text += (
            f"🆔 <b>Client ID:</b> <code>{client_data.client_id or '-'}</code>\n"
            f"🔑 <b>Sub ID:</b> <code>{client_data.sub_id or '-'}</code>\n"
            f"👤 <b>Telegram User ID:</b> <code>{client_data.tg_id or user.tg_id}</code>\n"
            f"⚙️ <b>Flow:</b> <code>{client_data.flow or '-'}</code>\n"
            f"📥 <b>Inbound ID:</b> <code>{client_data.inbound_id or '-'}</code>\n"
        )

    start = _effective_start_date(subscription)
    if start:
        text += f"🗓 <b>شروع:</b> {start.strftime('%Y/%m/%d %H:%M')}\n"
    if expire:
        text += f"⏳ <b>انقضا:</b> {expire.strftime('%Y/%m/%d %H:%M')}\n"
        if days is not None:
            if days <= 3 and days > 0:
                text += f"🟠 <b>فقط {days} روز باقی‌مانده</b>\n"
            elif days == 0:
                text += "🔴 <b>سرویس منقضی شده</b>\n"
            else:
                text += f"📆 <b>باقی‌مانده:</b> {days} روز\n"
        if time_bar:
            text += f"\n⏳ <b>اعتبار سرویس</b>\n{time_bar}\n"
    elif subscription.duration_days <= 0:
        text += "♾️ <b>بدون محدودیت زمانی</b>\n"

    if client_data and subscription.status == "active" and status_text not in {"منقضی شده", "غیرفعال"}:
        if client_data.traffic_total > 0:
            used = client_data.traffic_used
            total = client_data.traffic_total
            remaining = max(0, total - used)
            used_percent = round((used / total) * 100) if total else 0
            text += (
                "\n📊 <b>مصرف ترافیک</b>\n"
                f"{_progress(used, total)}  <b>{used_percent}%</b>\n"
                f"مصرف‌شده: <b>{_format_bytes(used)}</b> از <b>{_format_bytes(total)}</b>\n"
                f"باقی‌مانده: <b>{_format_bytes(remaining)}</b>\n"
            )

    builder = InlineKeyboardBuilder()
    can_toggle = (
        settings.allow_user_client_toggle
        and status_text in {"فعال", "غیرفعال", "رو به اتمام"}
        and subscription.status in {"active", "inactive"}
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
                callback_data=NavSubscription.RENEW_SERVICE,
            )
        )

    builder.row(InlineKeyboardButton(text="🛒 خرید سرویس جدید", callback_data=NavSubscription.BUY))

    if can_toggle:
        if subscription.status == "active":
            builder.row(
                InlineKeyboardButton(
                    text="⛔ غیرفعال کردن سرویس",
                    callback_data=f"my_services:toggle:{subscription.id}",
                )
            )
        else:
            builder.row(
                InlineKeyboardButton(
                    text="✅ فعال کردن سرویس",
                    callback_data=f"my_services:toggle:{subscription.id}",
                )
            )

    builder.row(InlineKeyboardButton(text="⬅️ بازگشت به سرویس‌های من", callback_data=NavMain.MY_SERVICES))
    builder.row(InlineKeyboardButton(text="🏠 بازگشت به منوی اصلی", callback_data=NavMain.MAIN_MENU))

    await callback.message.edit_text(text=text, reply_markup=builder.as_markup())


@router.callback_query(F.data.regexp(r"^my_services:view:\d+$"))
async def callback_my_service_details_with_control(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    subscription_id = int(callback.data.rsplit(":", 1)[1])
    result = await session.execute(
        select(Subscription)
        .join(Server, Subscription.server_id == Server.id)
        .options(selectinload(Subscription.server))
        .where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
            Subscription.server_id.is_not(None),
        )
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        await callback.answer("سرویس پیدا نشد یا سرور آن دیگر فعال نیست.", show_alert=True)
        return

    synced = await _sync_subscriptions_with_xui(session, [subscription], services)
    if not synced:
        await callback.answer("این سرویس دیگر در 3X-UI وجود ندارد.", show_alert=True)
        return

    await callback.answer()
    await _render_details(callback, user, session, services, synced[0])


@router.callback_query(F.data.regexp(r"^my_services:toggle:\d+$"))
async def callback_my_service_toggle(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    subscription_id = int(callback.data.rsplit(":", 1)[1])

    settings = await SubscriptionSettings.get_or_create(session)
    if not settings.allow_user_client_toggle:
        await callback.answer("این قابلیت در حال حاضر توسط مدیریت فعال نشده است.", show_alert=True)
        return

    result = await session.execute(
        select(Subscription)
        .join(Server, Subscription.server_id == Server.id)
        .options(selectinload(Subscription.server))
        .where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
            Subscription.server_id.is_not(None),
        )
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        await callback.answer("سرویس پیدا نشد یا سرور آن دیگر فعال نیست.", show_alert=True)
        return

    synced = await _sync_subscriptions_with_xui(session, [subscription], services)
    if not synced:
        await callback.answer("این سرویس دیگر در 3X-UI وجود ندارد.", show_alert=True)
        return
    subscription = synced[0]

    _icon, status_text = _status(subscription)
    if status_text == "منقضی شده":
        await callback.answer("سرویس منقضی شده و قابل فعال‌سازی نیست.", show_alert=True)
        return

    enable = subscription.status != "active"
    if not await _set_subscription_client_enabled(subscription, enable, services):
        await callback.answer("تغییر وضعیت کلاینت در 3X-UI انجام نشد.", show_alert=True)
        return

    subscription.status = "active" if enable else "inactive"
    await session.commit()

    await callback.answer("سرویس فعال شد." if enable else "سرویس غیرفعال شد.")
    await _render_details(callback, user, session, services, subscription)
