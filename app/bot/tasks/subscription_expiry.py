import logging
from datetime import datetime, timedelta, timezone

from aiogram.utils.i18n import I18n
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from redis.asyncio.client import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.bot.services import NotificationService, VPNService
from app.db.models import Subscription

logger = logging.getLogger(__name__)


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
            .options(selectinload(Subscription.user))
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

            client_data = await vpn_service.get_client_data(
                user,
                subscription_id=subscription.id,
            )

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
