import logging
from datetime import datetime, timedelta, timezone

from aiogram.utils.i18n import I18n
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from redis.asyncio.client import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.bot.models import ClientData
from app.bot.services import NotificationService, VPNService
from app.db.models import Subscription

logger = logging.getLogger(__name__)


async def _get_subscription_client_data(
    subscription: Subscription,
    vpn_service: VPNService,
) -> ClientData | None:
    """Read one subscription's XUI client while its server relationship is attached."""
    if subscription.server is None or not subscription.client_id:
        return None

    connection = await vpn_service.server_pool_service.get_connection_for_server(
        subscription.server
    )
    if not connection:
        return None

    try:
        inbounds = await connection.api.inbound.get_list()
        target_client_id = str(subscription.client_id).strip()
        client = None
        matched_inbound = None

        for inbound in inbounds:
            for inbound_client in inbound.settings.clients or []:
                if (
                    str(inbound_client.id or "").strip() == target_client_id
                    or str(inbound_client.sub_id or "").strip() == target_client_id
                ):
                    client = inbound_client
                    matched_inbound = inbound
                    break
            if client:
                break

        if not client:
            logger.warning(
                "Client for subscription %s was not found on server %s.",
                subscription.id,
                subscription.server.name,
            )
            return None

        stats_client = None
        for inbound in inbounds:
            for stat in inbound.client_stats or []:
                if str(stat.email or "") == str(client.email or ""):
                    stats_client = stat
                    break
            if stats_client:
                break

        source = stats_client or client
        limit_ip = client.limit_ip
        max_devices = -1 if limit_ip == 0 else limit_ip
        traffic_total = source.total
        expiry_time = -1 if source.expiry_time == 0 else source.expiry_time

        if traffic_total <= 0:
            traffic_remaining = -1
            traffic_total = -1
        else:
            traffic_remaining = max(0, source.total - (source.up + source.down))

        return ClientData(
            max_devices=max_devices,
            traffic_total=traffic_total,
            traffic_remaining=traffic_remaining,
            traffic_used=source.up + source.down,
            traffic_up=source.up,
            traffic_down=source.down,
            expiry_time=expiry_time,
            client_id=str(client.id or "") or None,
            sub_id=str(client.sub_id or "") or None,
            tg_id=getattr(client, "tg_id", None),
            flow=getattr(client, "flow", None),
            inbound_id=int(matched_inbound.id) if matched_inbound is not None else None,
            config_name=str(client.email or "") or None,
        )
    except Exception as exception:
        logger.error(
            "Error retrieving client data for subscription %s: %s",
            subscription.id,
            exception,
        )
        return None


async def notify_users_with_expiring_subscription(
    session_factory: async_sessionmaker,
    redis: Redis,
    i18n: I18n,
    vpn_service: VPNService,
    notification_service: NotificationService,
) -> None:
    session: AsyncSession
    async with session_factory() as session:
        result = await session.execute(
            select(Subscription)
            .options(
                selectinload(Subscription.user),
                selectinload(Subscription.server),
            )
            .where(
                Subscription.status == "active",
                Subscription.server_id.is_not(None),
            )
            .order_by(Subscription.id.asc())
        )
        subscriptions = list(result.scalars().all())

        logger.info(
            "[Background task] Starting subscription expiration check for %s subscriptions.",
            len(subscriptions),
        )

        for subscription in subscriptions:
            user = subscription.user
            if user is None:
                continue

            notification_key = f"subscription:notified:{subscription.id}"
            if await redis.get(notification_key):
                continue

            client_data = await _get_subscription_client_data(subscription, vpn_service)
            if not client_data or client_data._expiry_time == -1:
                continue

            now = datetime.now(timezone.utc)
            expiry_datetime = datetime.fromtimestamp(
                client_data._expiry_time / 1000,
                timezone.utc,
            )
            time_left = expiry_datetime - now

            if not (timedelta(0) < time_left <= timedelta(hours=24)):
                continue

            await notification_service.notify_by_id(
                chat_id=user.tg_id,
                text=i18n.gettext(
                    "task:message:subscription_expiry",
                    locale=user.language_code,
                ).format(
                    devices=client_data.max_devices,
                    expiry_time=client_data.expiry_time,
                ),
            )

            await redis.set(notification_key, "true", ex=timedelta(hours=24))
            logger.info(
                "[Background task] Sent expiry notification for subscription %s to user %s.",
                subscription.id,
                user.tg_id,
            )

        logger.info("[Background task] Subscription check finished.")


def start_scheduler(
    session_factory: async_sessionmaker,
    redis: Redis,
    i18n: I18n,
    vpn_service: VPNService,
    notification_service: NotificationService,
) -> None:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        notify_users_with_expiring_subscription,
        "interval",
        minutes=15,
        args=[session_factory, redis, i18n, vpn_service, notification_service],
        next_run_time=datetime.now(tz=timezone.utc),
    )
    scheduler.start()
