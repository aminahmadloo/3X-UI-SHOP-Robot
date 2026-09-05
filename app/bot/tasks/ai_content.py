from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from app.bot.services.ai_content import AIContentError, AIContentService
from app.db.models import AdvertisingChannel, AIContentSettings

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None


async def generate_due(session_factory) -> None:
    async with session_factory() as session:
        settings = (await session.execute(select(AIContentSettings).order_by(AIContentSettings.id).limit(1))).scalar_one_or_none()
        if not settings or not settings.enabled or not settings.auto_schedule:
            return
        now = datetime.utcnow()
        if settings.next_run_at and settings.next_run_at > now:
            return
        channel = (await session.execute(select(AdvertisingChannel).where(AdvertisingChannel.is_active.is_(True)).order_by(AdvertisingChannel.id).limit(1))).scalar_one_or_none()
        if not channel:
            return
        service = AIContentService(__import__("os").getenv("OPENAI_API_KEY"), settings.model)
        try:
            await service.create_content(session, channel.id, settings)
            service.schedule_next(settings)
            await session.commit()
        except AIContentError:
            await session.rollback()
            logger.exception("Automatic AI content generation failed")
        except Exception:
            await session.rollback()
            logger.exception("Automatic AI content task failed")


def start_scheduler(session_factory) -> None:
    global _scheduler
    if _scheduler is not None:
        return
    scheduler = AsyncIOScheduler()
    scheduler.add_job(generate_due, "interval", minutes=5, args=[session_factory], id="ai_content_generation", replace_existing=True, max_instances=1, coalesce=True, next_run_time=datetime.now())
    scheduler.start()
    _scheduler = scheduler
    logger.info("AI content scheduler started.")
