from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.models import ServicesContainer
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import Server, Subscription, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _effective_start_date(subscription: Subscription) -> datetime | None:
    """Return the best available start date for time-limited subscriptions."""
    if subscription.start_date:
        return _as_utc(subscription.start_date)
    if subscription.duration_days > 0 and subscription.created_at:
        return _as_utc(subscription.created_at)
    return None


def _effective_expire_date(subscription: Subscription) -> datetime | None:
    """Use stored expiry, or derive it from start/creation date + duration."""
    if subscription.expire_date:
        return _as_utc(subscription.expire_date)
    if subscription.duration_days <= 0:
        return None
    start = _effective_start_date(subscription)
    if not start:
        return None
    return start + timedelta(days=subscription.duration_days)


def _status(subscription: Subscription) -> tuple[str, str]:
    now = datetime.now(timezone.utc)
    if subscription.status != "active":
        return "🔴", "منقضی / غیرفعال"

    expire = _effective_expire_date(subscription)
    if expire:
        days_left = (expire - now).total_seconds() / 86400
        if days_left <= 0:
            return "🔴", "منقضی شده"
        if days_left <= 3:
            return "🟠", "رو به اتمام"
    return "🟢", "فعال"


def _days_left(subscription: Subscription) -> int | None:
    expire = _effective_expire_date(subscription)
    if not expire:
        return None
    seconds = (expire - datetime.now(timezone.utc)).total_seconds()
    return max(0, int(seconds // 86400))


def _format_bytes(value: int) -> str:
    if value < 0:
        return "نامحدود"
    if value >= 1024**3:
        return f"{value / 1024**3:.1f} GB"
    if value >= 1024**2:
        return f"{value / 1024**2:.1f} MB"
    return f"{value / 1024:.1f} KB"


def _progress(used: int, total: int, width: int = 14) -> str:
    if total <= 0:
        return "▫️" * width
    ratio = max(0.0, min(1.0, used / total))
    filled = round(ratio * width)
    return "█" * filled + "░" * (width - filled)


def _time_progress(subscription: Subscription, width: int = 14) -> str | None:
    start = _effective_start_date(subscription)
    expire = _effective_expire_date(subscription)
    if not start or not expire or expire <= start:
        return None
    now = datetime.now(timezone.utc)
    ratio = (now - start).total_seconds() / (expire - start).total_seconds()
    ratio = max(0.0, min(1.0, ratio))
    filled = round(ratio * width)
    return "█" * filled + "░" * (width - filled)


def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🛒 خرید سرویس جدید", callback_data=NavSubscription.BUY)],
            [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)],
        ]
    )


async def _get_subscriptions(session: AsyncSession, user: User) -> list[Subscription]:
    """Return database subscriptions whose server still exists."""
    result = await session.execute(
        select(Subscription)
        .join(Server, Subscription.server_id == Server.id)
        .options(selectinload(Subscription.server))
        .where(
            Subscription.user_id == user.id,
            Subscription.server_id.is_not(None),
        )
        .order_by(Subscription.id.desc())
    )
    return list(result.scalars().all())


async def _sync_subscriptions_with_xui(
    session: AsyncSession,
    subscriptions: list[Subscription],
    services: ServicesContainer,
) -> list[Subscription]:
    """Synchronize My Services with the live clients currently present in 3X-UI.

    A subscription is a real service only while its stored client_id exists on
    its assigned server. Missing clients are removed from the experimental
    subscription table. Existing disabled clients remain visible but are
    marked inactive by setting subscription.status to ``inactive``.

    If a server/XUI API cannot be reached, no subscriptions for that server are
    deleted or changed because an API failure must never be mistaken for a
    deleted client.
    """
    subscriptions_by_server: dict[int, list[Subscription]] = {}
    for subscription in subscriptions:
        if subscription.server_id is not None:
            subscriptions_by_server.setdefault(subscription.server_id, []).append(subscription)

    deleted_ids: set[int] = set()
    changed = False

    for server_id, server_subscriptions in subscriptions_by_server.items():
        server = server_subscriptions[0].server
        if server is None:
            continue

        connection = await services.server_pool.get_connection_for_server(server)
        if connection is None:
            logger.warning(
                "Could not connect to XUI server %s while synchronizing My Services; "
                "leaving its subscriptions unchanged.",
                server.name,
            )
            continue

        try:
            inbounds = await connection.api.inbound.get_list()
        except Exception as exception:
            logger.warning(
                "Could not read XUI clients from server %s while synchronizing My Services: %s",
                server.name,
                exception,
            )
            continue

        live_clients: dict[str, bool] = {}
        for inbound in inbounds:
            for client in inbound.settings.clients or []:
                client_id = str(client.id or "").strip()
                if not client_id:
                    continue
                # A client is represented in multiple attached inbounds. Treat
                # it as enabled if at least one live copy is enabled.
                live_clients[client_id] = live_clients.get(client_id, False) or bool(client.enable)

        for subscription in server_subscriptions:
            client_id = str(subscription.client_id or "").strip()
            if not client_id:
                logger.warning(
                    "Subscription %s has no client_id; keeping it unchanged for safety.",
                    subscription.id,
                )
                continue

            if client_id not in live_clients:
                deleted_ids.add(subscription.id)
                await session.execute(
                    delete(Subscription).where(Subscription.id == subscription.id)
                )
                changed = True
                logger.info(
                    "Removed orphan subscription %s (%s): client %s no longer exists on XUI server %s.",
                    subscription.id,
                    subscription.config_name,
                    client_id,
                    server.name,
                )
                continue

            new_status = "active" if live_clients[client_id] else "inactive"
            if subscription.status != new_status:
                subscription.status = new_status
                changed = True
                logger.info(
                    "Synchronized subscription %s (%s) with XUI client %s: status=%s.",
                    subscription.id,
                    subscription.config_name,
                    client_id,
                    new_status,
                )

    if changed:
        await session.commit()

    return [subscription for subscription in subscriptions if subscription.id not in deleted_ids]


@router.callback_query(F.data == NavMain.MY_SERVICES)
async def callback_my_services(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    logger.info("User %s opened My Services dashboard.", user.tg_id)
    await callback.answer()

    subscriptions = await _get_subscriptions(session, user)
    subscriptions = await _sync_subscriptions_with_xui(session, subscriptions, services)

    active_count = sum(1 for item in subscriptions if _status(item)[1] in {"فعال", "رو به اتمام"})
    expired_count = len(subscriptions) - active_count

    if not subscriptions:
        text = (
            "📦 <b>سرویس‌های من</b>\n\n"
            "هنوز هیچ سرویسی برای شما ثبت نشده است.\n\n"
            "🚀 برای دسترسی به اینترنت امن و پایدار، اولین سرویس خود را تهیه کنید.\n\n"
            "🛒 با انتخاب گزینه زیر می‌توانید سرویس مورد نظر خود را خریداری کنید."
        )
        await callback.message.edit_text(text=text, reply_markup=_main_keyboard())
        return

    lines = [
        "📦 <b>سرویس‌های من</b>",
        "",
        f"🟢 فعال: <b>{active_count}</b>   🔴 منقضی/غیرفعال: <b>{expired_count}</b>",
        "",
    ]

    for subscription in subscriptions[:8]:
        icon, status_text = _status(subscription)
        days = _days_left(subscription)
        if subscription.duration_days > 0 and days is not None:
            remaining = f"{days} روز باقی‌مانده"
        elif subscription.duration_days <= 0:
            remaining = "♾️ بدون محدودیت زمانی"
        else:
            remaining = f"{subscription.duration_days} روزه"
        lines.extend(
            [
                "━━━━━━━━━━━━━━━━━━",
                f"{icon} <b>{subscription.config_name}</b>",
                f"💾 {subscription.volume_gb} GB  •  📅 {subscription.duration_days} روز",
                f"⏳ {remaining}  •  {status_text}",
            ]
        )

    lines.extend(["━━━━━━━━━━━━━━━━━━", "👇 برای مشاهده جزئیات، سرویس مورد نظر را انتخاب کنید."])

    builder = InlineKeyboardBuilder()
    for subscription in subscriptions[:8]:
        icon, _ = _status(subscription)
        builder.button(
            text=f"{icon} {subscription.config_name}",
            callback_data=f"my_services:view:{subscription.id}",
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🛒 خرید سرویس جدید", callback_data=NavSubscription.BUY))
    builder.row(InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU))

    await callback.message.edit_text(text="\n".join(lines), reply_markup=builder.as_markup())


@router.callback_query(F.data.regexp(r"^my_services:view:\d+$"))
async def callback_my_service_details(
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

    subscriptions = await _sync_subscriptions_with_xui(session, [subscription], services)
    if not subscriptions:
        await callback.answer("این سرویس دیگر در 3X-UI وجود ندارد.", show_alert=True)
        return
    subscription = subscriptions[0]

    icon, status_text = _status(subscription)
    days = _days_left(subscription)
    server_name = subscription.server.name if subscription.server else "نامشخص"
    expire = _effective_expire_date(subscription)
    time_bar = _time_progress(subscription)

    text = (
        "📦 <b>جزئیات سرویس</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"{icon} <b>وضعیت:</b> {status_text}\n\n"
        f"📌 <b>نام سرویس:</b>\n<code>{subscription.config_name}</code>\n\n"
        f"💾 <b>حجم کل:</b> {subscription.volume_gb} GB\n"
        f"📅 <b>مدت:</b> {subscription.duration_days} روز\n"
        f"📱 <b>دستگاه مجاز:</b> {subscription.devices}\n"
        f"🖥 <b>سرور:</b> {server_name}\n"
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

    if subscription.status == "active":
        client_data = await services.vpn.get_client_data(user)
        if client_data and client_data.traffic_total > 0:
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
    if subscription.status == "active":
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
    builder.row(InlineKeyboardButton(text="⬅️ بازگشت به سرویس‌های من", callback_data=NavMain.MY_SERVICES))
    builder.row(InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU))

    await callback.answer()
    await callback.message.edit_text(text=text, reply_markup=builder.as_markup())


@router.callback_query(F.data.regexp(r"^my_services:key:\d+$"))
async def callback_my_service_key(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    subscription_id = int(callback.data.rsplit(":", 1)[1])
    result = await session.execute(
        select(Subscription).where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
            Subscription.status == "active",
        )
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        await callback.answer("این سرویس فعال نیست.", show_alert=True)
        return

    synced = await _sync_subscriptions_with_xui(session, [subscription], services)
    if not synced or synced[0].status != "active":
        await callback.answer("این سرویس در 3X-UI فعال نیست.", show_alert=True)
        return
    subscription = synced[0]

    key = await services.vpn.get_key(user)
    if not key:
        await callback.answer("لینک اتصال سرویس در حال حاضر در دسترس نیست.", show_alert=True)
        return

    text = (
        "🔗 <b>لینک اتصال سرویس</b>\n\n"
        f"📌 سرویس: <code>{subscription.config_name}</code>\n\n"
        f"<code>{key}</code>\n\n"
        "⚠️ این لینک خصوصی است؛ آن را در اختیار دیگران قرار ندهید."
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="⬅️ بازگشت به جزئیات سرویس", callback_data=f"my_services:view:{subscription.id}"))
    builder.row(InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU))
    await callback.answer()
    await callback.message.edit_text(text=text, reply_markup=builder.as_markup())
