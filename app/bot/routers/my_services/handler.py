from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from io import BytesIO

from aiogram import F, Router
from aiogram.enums import ButtonStyle
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import qrcode

from app.bot.models import ServicesContainer
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import Server, Subscription, User
from app.bot.utils.jalali import format_jalali

logger = logging.getLogger(__name__)
router = Router(name=__name__)


async def _countdown_delete_text_message(message, text: str, delay: int = 10) -> None:
    """Update a temporary text message countdown and always delete it."""
    try:
        for remaining in range(delay - 1, 0, -1):
            await asyncio.sleep(1)
            try:
                await message.edit_text(
                    text=(
                        f"{text}\n\n"
                        f"⏱️ این پیام پس از {remaining} ثانیه حذف می‌شود."
                    )
                )
            except Exception:
                logger.debug(
                    "Could not update temporary text message %s at %s seconds.",
                    getattr(message, "message_id", None),
                    remaining,
                    exc_info=True,
                )

        await asyncio.sleep(1)
    except asyncio.CancelledError:
        raise
    finally:
        try:
            await message.delete()
        except Exception:
            logger.debug(
                "Could not delete temporary text message %s.",
                getattr(message, "message_id", None),
                exc_info=True,
            )


async def _countdown_delete_photo_message(
    message,
    caption: str,
    delay: int = 10,
) -> None:
    """Update a temporary QR caption countdown and always delete it."""
    try:
        for remaining in range(delay - 1, 0, -1):
            await asyncio.sleep(1)
            try:
                await message.edit_caption(
                    caption=(
                        f"{caption}\n"
                        f"⏱️ این پیام پس از {remaining} ثانیه حذف می‌شود."
                    )
                )
            except Exception:
                logger.debug(
                    "Could not update temporary QR message %s at %s seconds.",
                    getattr(message, "message_id", None),
                    remaining,
                    exc_info=True,
                )

        await asyncio.sleep(1)
    except asyncio.CancelledError:
        raise
    finally:
        try:
            await message.delete()
        except Exception:
            logger.debug(
                "Could not delete temporary QR message %s.",
                getattr(message, "message_id", None),
                exc_info=True,
            )


def _schedule_text_countdown(message, text: str, delay: int = 10) -> None:
    asyncio.create_task(_countdown_delete_text_message(message, text, delay))


def _schedule_photo_countdown(message, caption: str, delay: int = 10) -> None:
    asyncio.create_task(_countdown_delete_photo_message(message, caption, delay))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _effective_start_date(subscription: Subscription) -> datetime | None:
    if subscription.start_date:
        return _as_utc(subscription.start_date)
    if subscription.duration_days > 0 and subscription.created_at:
        return _as_utc(subscription.created_at)
    return None


def _effective_expire_date(subscription: Subscription) -> datetime | None:
    if subscription.expire_date:
        return _as_utc(subscription.expire_date)
    if subscription.duration_days <= 0:
        return None
    start = _effective_start_date(subscription)
    if not start:
        return None
    return start + timedelta(days=subscription.duration_days)


def _status(subscription: Subscription) -> tuple[str, str]:
    """Return the user-facing status, with expiry taking priority over disabled."""
    expire = _effective_expire_date(subscription)
    if expire and (expire - datetime.now(timezone.utc)).total_seconds() <= 0:
        return "🔴", "منقضی شده"
    if subscription.status != "active":
        return "⚫", "غیرفعال"
    if expire:
        days_left = (expire - datetime.now(timezone.utc)).total_seconds() / 86400
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


async def _discover_user_subscriptions_from_xui(
    session: AsyncSession,
    user: User,
    services: ServicesContainer,
) -> list[Subscription]:
    """Discover the user's live clients directly from every 3X-UI server.

    3X-UI is queried even when the local database contains zero subscriptions.
    A client is associated with the Telegram user by tg_id, vpn_id/sub_id, or
    legacy email=Telegram-ID matching.

    One Subscription is created per unique XUI client/server pair, even when
    that client exists in multiple inbounds.
    """
    result = await session.execute(
        select(Server).order_by(Server.id.asc())
    )
    servers = list(result.scalars().all())

    discovered: dict[tuple[int, str], object] = {}
    live_identities_by_server: dict[int, set[str]] = {}
    changed = False

    for server in servers:
        connection = await services.server_pool.get_connection_for_server(server)

        if connection is None:
            logger.warning(
                "MY_SERVICES LIVE DISCOVERY | Cannot connect to XUI server %s.",
                server.name,
            )
            continue

        try:
            inbounds = await connection.api.inbound.get_list()
        except Exception as exception:
            logger.warning(
                "MY_SERVICES LIVE DISCOVERY | Failed to read inbounds from %s: %s",
                server.name,
                exception,
            )
            continue

        logger.info(
            "MY_SERVICES LIVE DISCOVERY | Checking XUI server %s for user tg_id=%s.",
            server.name,
            user.tg_id,
        )

        # A successful XUI read is authoritative for this server.
        # Track every live client identity for safe orphan cleanup.
        live_identities = live_identities_by_server.setdefault(server.id, set())

        for inbound in inbounds:
            for client in inbound.settings.clients or []:
                client_tg_id = str(getattr(client, "tg_id", "") or "").strip()
                client_sub_id = str(getattr(client, "sub_id", "") or "").strip()
                client_email = str(getattr(client, "email", "") or "").strip()
                user_vpn_id = str(user.vpn_id or "").strip()
                user_tg_id = str(user.tg_id)

                is_match = (
                    client_tg_id == user_tg_id
                    or (
                        user_vpn_id
                        and client_sub_id == user_vpn_id
                    )
                    or client_email == user_tg_id
                )

                if not is_match:
                    continue

                client_id = str(getattr(client, "id", "") or "").strip()
                live_identities.update(
                    value
                    for value in (client_id, client_sub_id, client_email)
                    if value
                )
                identity = client_id or client_sub_id or client_email

                if not identity:
                    logger.warning(
                        "MY_SERVICES LIVE DISCOVERY | Matched client without usable identity "
                        "on server %s inbound %s.",
                        server.name,
                        inbound.id,
                    )
                    continue

                key = (server.id, identity)

                # Same XUI client may exist in several inbounds.
                if key in discovered:
                    continue

                discovered[key] = client

                logger.info(
                    "MY_SERVICES LIVE DISCOVERY | FOUND client=%s name=%s "
                    "server=%s inbound=%s tg_id=%s sub_id=%s.",
                    client_id or "unknown",
                    client_email or "unknown",
                    server.name,
                    inbound.id,
                    client_tg_id or "unknown",
                    client_sub_id or "unknown",
                )

                # First try exact XUI client identity.
                existing_result = await session.execute(
                    select(Subscription)
                    .where(
                        Subscription.user_id == user.id,
                        Subscription.server_id == server.id,
                        Subscription.client_id == identity,
                    )
                    .limit(1)
                )
                subscription = existing_result.scalar_one_or_none()

                # Legacy records may have the correct config name but a stale
                # client_id. Try the XUI email as a secondary identity.
                if subscription is None and client_email:
                    existing_result = await session.execute(
                        select(Subscription)
                        .where(
                            Subscription.user_id == user.id,
                            Subscription.server_id == server.id,
                            Subscription.config_name == client_email,
                        )
                        .limit(1)
                    )
                    subscription = existing_result.scalar_one_or_none()

                try:
                    xui_limit_ip = int(getattr(client, "limit_ip", 0) or 0)
                except (TypeError, ValueError):
                    xui_limit_ip = 0

                try:
                    xui_total_bytes = int(getattr(client, "total_gb", 0) or 0)
                except (TypeError, ValueError):
                    xui_total_bytes = 0

                volume_gb = (
                    max(1, round(xui_total_bytes / (1024 ** 3)))
                    if xui_total_bytes > 0
                    else 0
                )

                try:
                    raw_expiry = int(getattr(client, "expiry_time", 0) or 0)
                except (TypeError, ValueError):
                    raw_expiry = 0

                expire_date = (
                    datetime.fromtimestamp(
                        raw_expiry / 1000,
                        tz=timezone.utc,
                    )
                    if raw_expiry > 0
                    else None
                )

                duration_days = 0
                if expire_date is not None:
                    duration_days = max(
                        0,
                        round(
                            (
                                expire_date
                                - datetime.now(timezone.utc)
                            ).total_seconds()
                            / 86400
                        ),
                    )

                new_status = (
                    "active"
                    if bool(getattr(client, "enable", False))
                    else "inactive"
                )

                config_name = client_email or identity

                if subscription is None:
                    subscription = Subscription(
                        user_id=user.id,
                        server_id=server.id,
                        plan_id=None,
                        config_name=config_name,
                        client_id=client_id or identity,
                        volume_gb=volume_gb,
                        duration_days=duration_days,
                        devices=xui_limit_ip,
                        status=new_status,
                        start_date=None,
                        expire_date=expire_date,
                    )
                    session.add(subscription)
                    changed = True

                    logger.info(
                        "MY_SERVICES LIVE DISCOVERY | CREATED DB subscription "
                        "for XUI client=%s server=%s user=%s.",
                        client_id or identity,
                        server.name,
                        user.tg_id,
                    )
                    continue

                # Existing record: synchronize it from live XUI.
                actual_client_id = client_id or identity

                if subscription.client_id != actual_client_id:
                    subscription.client_id = actual_client_id
                    changed = True

                if config_name and subscription.config_name != config_name:
                    subscription.config_name = config_name
                    changed = True

                if subscription.status != new_status:
                    subscription.status = new_status
                    changed = True

                if subscription.devices != xui_limit_ip:
                    subscription.devices = xui_limit_ip
                    changed = True

                if subscription.volume_gb != volume_gb:
                    subscription.volume_gb = volume_gb
                    changed = True

                current_expire = (
                    _as_utc(subscription.expire_date)
                    if subscription.expire_date
                    else None
                )

                if current_expire != expire_date:
                    subscription.expire_date = expire_date
                    changed = True

                if subscription.duration_days != duration_days:
                    subscription.duration_days = duration_days
                    changed = True

                logger.info(
                    "MY_SERVICES LIVE DISCOVERY | SYNCHRONIZED subscription=%s "
                    "with XUI client=%s server=%s.",
                    subscription.id,
                    actual_client_id,
                    server.name,
                )

    # Remove stale DB subscriptions only for servers whose XUI read
    # succeeded. An API/connection failure never causes deletion.
    for server_id, live_identities in live_identities_by_server.items():
        result = await session.execute(
            select(Subscription).where(
                Subscription.user_id == user.id,
                Subscription.server_id == server_id,
            )
        )
        server_subscriptions = list(result.scalars().all())
        for subscription in server_subscriptions:
            stored_client_id = str(subscription.client_id or "").strip()
            stored_name = str(subscription.config_name or "").strip()
            if stored_client_id in live_identities or stored_name in live_identities:
                continue

            logger.warning(
                "MY_SERVICES LIVE DISCOVERY | Removing orphan DB subscription=%s "
                "client_id=%s name=%s from server_id=%s: client is absent from live XUI.",
                subscription.id,
                stored_client_id or "unknown",
                stored_name or "unknown",
                server_id,
            )
            await session.execute(
                delete(Subscription).where(Subscription.id == subscription.id)
            )
            changed = True

    if changed:
        await session.commit()

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

    subscriptions = list(result.scalars().all())

    logger.info(
        "MY_SERVICES LIVE DISCOVERY | User %s now has %s synchronized subscriptions.",
        user.tg_id,
        len(subscriptions),
    )

    return subscriptions


async def _sync_subscriptions_with_xui(
    session: AsyncSession,
    subscriptions: list[Subscription],
    services: ServicesContainer,
) -> list[Subscription]:
    """Synchronize the user's subscription records from live 3X-UI clients.

    3X-UI is the live source of truth for client state. The user's existing
    My Services UI is preserved; only the data behind it is refreshed.
    One inbound list is fetched per server, then every subscription belonging
    to that server is matched by client UUID/sub-id.
    """
    subscriptions_by_server: dict[int, list[Subscription]] = {}
    for subscription in subscriptions:
        if subscription.server_id is not None:
            subscriptions_by_server.setdefault(subscription.server_id, []).append(subscription)

    changed = False

    for server_id, server_subscriptions in subscriptions_by_server.items():
        # Do not access subscription.server lazily inside AsyncSession.
        # Fetch the Server explicitly to avoid SQLAlchemy MissingGreenlet.
        server_result = await session.execute(
            select(Server).where(Server.id == server_id)
        )
        server = server_result.scalar_one_or_none()

        if server is None:
            logger.warning(
                "Server %s for My Services subscriptions was not found.",
                server_id,
            )
            continue

        connection = await services.server_pool.get_connection_for_server(server)
        if connection is None:
            logger.warning(
                "Could not connect to XUI server %s while synchronizing My Services; leaving subscriptions unchanged.",
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

        live_clients: dict[str, object] = {}
        for inbound in inbounds:
            for client in inbound.settings.clients or []:
                client_id = str(client.id or "").strip()
                sub_id = str(client.sub_id or "").strip()
                if client_id:
                    live_clients.setdefault(client_id, client)
                if sub_id:
                    live_clients.setdefault(sub_id, client)

        for subscription in server_subscriptions:
            stored_client_id = str(subscription.client_id or "").strip()
            if not stored_client_id:
                logger.warning(
                    "Subscription %s has no client_id; keeping it unchanged for safety.",
                    subscription.id,
                )
                continue

            client = live_clients.get(stored_client_id)
            if client is None and subscription.config_name:
                client = live_clients.get(str(subscription.config_name).strip())
            if client is None:
                await session.execute(
                    delete(Subscription).where(Subscription.id == subscription.id)
                )
                changed = True
                logger.warning(
                    "Subscription %s (%s) client %s is missing from XUI server %s; removed orphan DB record.",
                    subscription.id,
                    subscription.config_name,
                    stored_client_id,
                    server.name,
                )
                continue

            # 3X-UI is authoritative for the live client enabled/disabled state.
            new_status = "active" if bool(getattr(client, "enable", False)) else "inactive"
            if subscription.status != new_status:
                subscription.status = new_status
                changed = True
                logger.info(
                    "Synchronized subscription %s (%s) with XUI client %s: status=%s.",
                    subscription.id,
                    subscription.config_name,
                    str(getattr(client, "id", "")),
                    new_status,
                )

            # Keep the DB identity aligned with the actual XUI UUID. Prefer the
            # real client.id because all subscription-specific lookups use it.
            actual_client_id = str(getattr(client, "id", "") or "").strip()
            if actual_client_id and actual_client_id != stored_client_id:
                subscription.client_id = actual_client_id
                changed = True
                logger.info(
                    "Synchronized subscription %s client_id from XUI: %s -> %s.",
                    subscription.id,
                    stored_client_id,
                    actual_client_id,
                )

            xui_name = str(getattr(client, "email", "") or "").strip()
            if xui_name and subscription.config_name != xui_name:
                logger.info(
                    "Synchronized subscription %s config_name from XUI: %s -> %s.",
                    subscription.id,
                    subscription.config_name,
                    xui_name,
                )
                subscription.config_name = xui_name
                changed = True

            try:
                xui_devices = int(getattr(client, "limit_ip", 0) or 0)
            except (TypeError, ValueError):
                xui_devices = subscription.devices
            if subscription.devices != xui_devices:
                subscription.devices = xui_devices
                changed = True

            try:
                xui_total_bytes = int(getattr(client, "total_gb", 0) or 0)
            except (TypeError, ValueError):
                xui_total_bytes = 0
            if xui_total_bytes > 0:
                xui_volume_gb = max(1, round(xui_total_bytes / (1024**3)))
                if subscription.volume_gb != xui_volume_gb:
                    subscription.volume_gb = xui_volume_gb
                    changed = True

            # Synchronize expiry from the live XUI timestamp. A zero timestamp
            # means unlimited lifetime and clears any stale DB expiry.
            try:
                raw_expiry = int(getattr(client, "expiry_time", 0) or 0)
            except (TypeError, ValueError):
                raw_expiry = 0

            if raw_expiry > 0:
                xui_expire = datetime.fromtimestamp(raw_expiry / 1000, tz=timezone.utc)
                current_expire = _as_utc(subscription.expire_date) if subscription.expire_date else None
                if current_expire != xui_expire:
                    subscription.expire_date = xui_expire
                    changed = True

                start = _effective_start_date(subscription)
                if start:
                    calculated_days = max(0, round((xui_expire - start).total_seconds() / 86400))
                    if subscription.duration_days != calculated_days:
                        subscription.duration_days = calculated_days
                        changed = True
            elif subscription.expire_date is not None:
                subscription.expire_date = None
                subscription.duration_days = 0
                changed = True

    if changed:
        await session.commit()
        # Refresh ORM state after commit so the caller renders the synchronized
        # values rather than stale pre-commit attributes.
        for subscription in subscriptions:
            if subscription.server_id is not None:
                await session.refresh(subscription)

    return subscriptions


@router.callback_query(F.data == NavMain.MY_SERVICES)
async def callback_my_services(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    logger.info("User %s opened My Services dashboard.", user.tg_id)
    await callback.answer()

    # IMPORTANT:
    # Query live 3X-UI first. This allows My Services to discover clients
    # that exist in XUI but have no local Subscription row yet.
    subscriptions = await _discover_user_subscriptions_from_xui(
        session=session,
        user=user,
        services=services,
    )

    # Then run the existing synchronization layer so the current My Services
    # presentation continues to use a fully synchronized DB snapshot.
    subscriptions = await _sync_subscriptions_with_xui(
        session=session,
        subscriptions=subscriptions,
        services=services,
    )

    active_count = 0
    expired_count = 0
    disabled_count = 0
    for item in subscriptions:
        _, status_text = _status(item)
        if status_text in {"فعال", "رو به اتمام"}:
            active_count += 1
        elif status_text == "منقضی شده":
            expired_count += 1
        elif status_text == "غیرفعال":
            disabled_count += 1

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
        f"🟢 فعال: <b>{active_count}</b>   🔴 منقضی‌شده: <b>{expired_count}</b>   ⚫ غیرفعال: <b>{disabled_count}</b>",
        "",
    ]

    for subscription in subscriptions:
        icon, status_text = _status(subscription)
        days = _days_left(subscription)
        if status_text == "منقضی شده":
            remaining = "به پایان رسیده"
        elif subscription.duration_days > 0 and days is not None:
            remaining = f"{days} روز باقی‌مانده"
        elif subscription.duration_days <= 0:
            remaining = "♾️ بدون محدودیت زمانی"
        else:
            remaining = f"{subscription.duration_days} روزه"
        lines.extend(
            [
                "      ━━━━━━━━━━━━━━",
                f"{icon} <b>{subscription.config_name}</b>",
                f"💾 {subscription.volume_gb} GB  •  📅 {subscription.duration_days} روز",
                f"⏳ {remaining}  •  {status_text}",
            ]
        )

    lines.extend(["      ━━━━━━━━━━━━━━", "👇 برای مشاهده جزئیات، سرویس مورد نظر را انتخاب کنید."])

    builder = InlineKeyboardBuilder()
    for subscription in subscriptions:
        icon, _ = _status(subscription)
        builder.button(
            text=f"{icon} {subscription.config_name}",
            callback_data=f"my_services:view:{subscription.id}",
        )
    builder.adjust(1)
    builder.row(InlineKeyboardButton(text="🛒 خرید سرویس جدید", callback_data=NavSubscription.BUY))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data=NavMain.MAIN_MENU, style=ButtonStyle.DANGER))

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
    client_data = await services.vpn.get_client_data(user, subscription_id=subscription.id)

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
        text += f"🗓 <b>شروع:</b> {format_jalali(start)}\n"
    if expire:
        text += f"⏳ <b>انقضا:</b> {format_jalali(expire)}\n"
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
    if subscription.status == "active" and status_text not in {"منقضی شده", "غیرفعال"}:
        builder.row(InlineKeyboardButton(text="🔗 دریافت لینک اتصال", callback_data=f"my_services:key:{subscription.id}"))
        builder.row(InlineKeyboardButton(text="🔄 تمدید سرویس", callback_data=f"main_renewal:service:{subscription.id}"))
    builder.row(InlineKeyboardButton(text="🛒 خرید سرویس جدید", callback_data=NavSubscription.BUY))
    builder.row(InlineKeyboardButton(text="⬅️ بازگشت به سرویس‌های من", callback_data=NavMain.MY_SERVICES))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت به منوی اصلی", callback_data=NavMain.MAIN_MENU, style=ButtonStyle.DANGER))

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
        select(Subscription)
        .where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
            Subscription.status == "active",
        )
    )
    subscription = result.scalar_one_or_none()

    if not subscription:
        await callback.answer("این سرویس فعال نیست.", show_alert=True)
        return

    synced = await _sync_subscriptions_with_xui(
        session,
        [subscription],
        services,
    )

    if not synced or synced[0].status != "active":
        await callback.answer(
            "این سرویس در 3X-UI فعال نیست.",
            show_alert=True,
        )
        return

    subscription = synced[0]

    await callback.answer()

    text = (
        "🔗 <b>دریافت اطلاعات اتصال</b>\n\n"
        f"📌 سرویس: <code>{subscription.config_name}</code>\n\n"
        "لطفاً نوع اطلاعات موردنظر را انتخاب کنید:"
    )

    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="🔗 لینک اشتراک",
            callback_data=f"my_services:sub:{subscription.id}",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="📡 لینک‌های اتصال تکی",
            callback_data=f"my_services:links:{subscription.id}",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="🖼 QR Code",
            callback_data=f"my_services:qr:{subscription.id}",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="📦 دریافت همه",
            callback_data=f"my_services:all:{subscription.id}",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="⬅️ بازگشت به جزئیات سرویس",
            callback_data=f"my_services:view:{subscription.id}",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="🏠 منوی اصلی",
            callback_data=NavMain.MAIN_MENU,
        )
    )

    await callback.message.edit_text(
        text=text,
        reply_markup=builder.as_markup(),
    )


async def _load_active_subscription_for_connection(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
    subscription_id: int,
) -> Subscription | None:
    result = await session.execute(
        select(Subscription)
        .where(
            Subscription.id == subscription_id,
            Subscription.user_id == user.id,
            Subscription.status == "active",
        )
    )

    subscription = result.scalar_one_or_none()

    if not subscription:
        await callback.answer(
            "این سرویس فعال نیست.",
            show_alert=True,
        )
        return None

    synced = await _sync_subscriptions_with_xui(
        session,
        [subscription],
        services,
    )

    if not synced or synced[0].status != "active":
        await callback.answer(
            "این سرویس در 3X-UI فعال نیست.",
            show_alert=True,
        )
        return None

    return synced[0]


def _connection_menu(subscription_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="🔗 لینک اشتراک",
            callback_data=f"my_services:sub:{subscription_id}",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="📡 لینک‌های اتصال تکی",
            callback_data=f"my_services:links:{subscription_id}",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="🖼 QR Code",
            callback_data=f"my_services:qr:{subscription_id}",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="📦 دریافت همه",
            callback_data=f"my_services:all:{subscription_id}",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="⬅️ بازگشت به جزئیات سرویس",
            callback_data=f"my_services:view:{subscription_id}",
        )
    )

    return builder.as_markup()


@router.callback_query(F.data.regexp(r"^my_services:sub:\d+$"))
async def callback_my_service_subscription(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    subscription_id = int(callback.data.rsplit(":", 1)[1])

    subscription = await _load_active_subscription_for_connection(
        callback,
        user,
        session,
        services,
        subscription_id,
    )

    if subscription is None:
        return

    key = await services.vpn.get_key(
        user,
        subscription_id=subscription.id,
    )

    if not key:
        await callback.answer(
            "لینک اشتراک در حال حاضر در دسترس نیست.",
            show_alert=True,
        )
        return

    await callback.answer()

    text = (
        "🔗 <b>لینک اشتراک</b>\n\n"
        f"📌 سرویس: <code>{subscription.config_name}</code>\n\n"
        f"<code>{key}</code>\n\n"
        "ℹ️ این لینک را می‌توانید در کلاینت‌های سازگار با Subscription وارد کنید."
    )

    message = await callback.message.answer(text=text)
    _schedule_text_countdown(message, text, 10)


@router.callback_query(F.data.regexp(r"^my_services:links:\d+$"))
async def callback_my_service_individual_links(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    subscription_id = int(callback.data.rsplit(":", 1)[1])

    subscription = await _load_active_subscription_for_connection(
        callback,
        user,
        session,
        services,
        subscription_id,
    )

    if subscription is None:
        return

    links = await services.vpn.get_subscription_links(
        user,
        subscription_id=subscription.id,
    )

    if not links:
        await callback.answer(
            "هیچ لینک اتصال فعالی برای این سرویس از 3X-UI دریافت نشد.",
            show_alert=True,
        )
        return

    await callback.answer()

    lines = [
        "📡 <b>لینک‌های اتصال تکی</b>",
        "",
        f"📌 سرویس: <code>{subscription.config_name}</code>",
        "",
    ]

    for index, link in enumerate(links, start=1):
        lines.extend(
            [
                f"🔹 <b>اتصال {index}</b>",
                f"<code>{link}</code>",
                "",
            ]
        )

    links_text = "\n".join(lines)

    message = await callback.message.answer(text=links_text)
    _schedule_text_countdown(message, links_text, 10)


def _make_qr_png(content: str) -> bytes:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(content)
    qr.make(fit=True)

    image = qr.make_image()
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@router.callback_query(F.data.regexp(r"^my_services:qr:\d+$"))
async def callback_my_service_qr(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    subscription_id = int(callback.data.rsplit(":", 1)[1])

    subscription = await _load_active_subscription_for_connection(
        callback,
        user,
        session,
        services,
        subscription_id,
    )

    if subscription is None:
        return

    subscription_url = await services.vpn.get_key(
        user,
        subscription_id=subscription.id,
    )

    links = await services.vpn.get_subscription_links(
        user,
        subscription_id=subscription.id,
    )

    if not subscription_url and not links:
        await callback.answer(
            "QR Code برای این سرویس در دسترس نیست.",
            show_alert=True,
        )
        return

    await callback.answer()

    if subscription_url:
        try:
            png = _make_qr_png(subscription_url)
            caption = (
                "🖼 <b>QR Code لینک اشتراک</b>\n\n"
                f"📌 {subscription.config_name}"
            )

            message = await callback.message.answer_photo(
                BufferedInputFile(
                    png,
                    filename=f"subscription-{subscription.id}.png",
                ),
                caption=caption,
            )
            _schedule_photo_countdown(message, caption, 10)
        except Exception:
            logger.exception(
                "Could not generate subscription QR for subscription %s.",
                subscription.id,
            )

    for index, link in enumerate(links, start=1):
        try:
            png = _make_qr_png(link)
            caption = (
                f"🖼 <b>QR Code اتصال {index}</b>\n\n"
                f"📌 {subscription.config_name}"
            )

            message = await callback.message.answer_photo(
                BufferedInputFile(
                    png,
                    filename=f"connection-{subscription.id}-{index}.png",
                ),
                caption=caption,
            )
            _schedule_photo_countdown(message, caption, 10)
        except Exception:
            logger.exception(
                "Could not generate QR for subscription %s link %s.",
                subscription.id,
                index,
            )

    await callback.message.answer(
        "🔗 <b>گزینه‌های اتصال</b>",
        reply_markup=_connection_menu(subscription.id),
    )


@router.callback_query(F.data.regexp(r"^my_services:all:\d+$"))
async def callback_my_service_all_connection_data(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    subscription_id = int(callback.data.rsplit(":", 1)[1])

    subscription = await _load_active_subscription_for_connection(
        callback,
        user,
        session,
        services,
        subscription_id,
    )

    if subscription is None:
        return

    subscription_url = await services.vpn.get_key(
        user,
        subscription_id=subscription.id,
    )

    links = await services.vpn.get_subscription_links(
        user,
        subscription_id=subscription.id,
    )

    if not subscription_url and not links:
        await callback.answer(
            "اطلاعات اتصال این سرویس در دسترس نیست.",
            show_alert=True,
        )
        return

    await callback.answer()

    lines = [
        "📦 <b>اطلاعات کامل اتصال</b>",
        "",
        f"📌 سرویس: <code>{subscription.config_name}</code>",
        "",
    ]

    if subscription_url:
        lines.extend(
            [
                "🔗 <b>لینک اشتراک</b>",
                f"<code>{subscription_url}</code>",
                "",
            ]
        )

    if links:
        lines.append("📡 <b>لینک‌های اتصال تکی</b>")
        lines.append("")

        for index, link in enumerate(links, start=1):
            lines.extend(
                [
                    f"🔹 اتصال {index}",
                    f"<code>{link}</code>",
                    "",
                ]
            )

    all_text = "\n".join(lines)

    message = await callback.message.answer(text=all_text)
    _schedule_text_countdown(message, all_text, 15)

    # Also deliver QR codes as part of "دریافت همه".
    qr_items: list[tuple[str, str]] = []

    if subscription_url:
        qr_items.append(
            (
                "لینک اشتراک",
                subscription_url,
            )
        )

    for index, link in enumerate(links, start=1):
        qr_items.append(
            (
                f"اتصال {index}",
                link,
            )
        )

    for index, (label, content) in enumerate(qr_items, start=1):
        try:
            png = _make_qr_png(content)
            caption = (
                f"🖼 <b>QR Code {label}</b>\n"
                f"📌 {subscription.config_name}"
            )

            message = await callback.message.answer_photo(
                BufferedInputFile(
                    png,
                    filename=f"toonelvpn-{subscription.id}-{index}.png",
                ),
                caption=caption,
            )
            _schedule_photo_countdown(message, caption, 15)
        except Exception:
            logger.exception(
                "Could not generate QR for subscription %s item %s.",
                subscription.id,
                label,
            )

