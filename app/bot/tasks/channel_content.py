from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db.models import AdvertisingChannel, ChannelContent, ChannelContentEvent

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


async def publish_due(session_factory, bot) -> None:
    try:
        async with session_factory() as session:
            result = await session.execute(
                __import__("sqlalchemy").select(ChannelContent, AdvertisingChannel)
                .join(AdvertisingChannel, AdvertisingChannel.id == ChannelContent.channel_id)
                .where(
                    ChannelContent.status == "scheduled",
                    ChannelContent.scheduled_at.is_not(None),
                    ChannelContent.scheduled_at <= datetime.utcnow(),
                    AdvertisingChannel.is_active.is_(True),
                )
                .order_by(ChannelContent.id)
                .limit(20)
            )
            rows = list(result.all())
            for content, channel in rows:
                try:
                    from app.bot.routers.admin_tools.channel_management_handler import _publish_content
                    sent = await _publish_content(bot, session, content, channel)
                    content.telegram_message_id = sent.message_id
                    content.status = "published"
                    content.published_at = datetime.utcnow()
                    content.scheduled_at = None
                    session.add(ChannelContentEvent(content_id=content.id, event_type="published"))
                    await session.commit()
                except Exception:
                    logger.exception("Scheduled channel post failed content=%s channel=%s", content.id, channel.chat_id)
                    await session.rollback()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Channel content scheduler failed")


def start_scheduler(session_factory, bot) -> None:
    global _scheduler
    if _scheduler is not None:
        return
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        publish_due,
        "interval",
        seconds=30,
        args=[session_factory, bot],
        next_run_time=datetime.now(),
        id="channel_content_publish",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("Channel content scheduler started.")
