from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.bot.services.channel_campaign import ChannelAnalyticsService
from app.db.models import AdvertisingChannel

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


async def snapshot_active_channels(session_factory, bot) -> None:
    try:
        async with session_factory() as session:
            channels = list((await session.execute(
                __import__("sqlalchemy").select(AdvertisingChannel).where(AdvertisingChannel.is_active.is_(True))
            )).scalars())
            for channel in channels:
                try:
                    await ChannelAnalyticsService.snapshot_channel(session, bot, channel.chat_id)
                except Exception:
                    logger.exception("Channel member snapshot failed channel=%s", channel.chat_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Channel analytics scheduler failed")


def start_scheduler(session_factory, bot) -> None:
    global _scheduler
    if _scheduler is not None:
        return
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        snapshot_active_channels,
        "interval",
        hours=24,
        args=[session_factory, bot],
        next_run_time=datetime.now(),
        id="channel_member_daily_snapshot",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info("Channel analytics scheduler started.")
