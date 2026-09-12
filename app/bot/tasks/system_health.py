from __future__ import annotations

import logging
from collections.abc import Callable

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.models import ServicesContainer
from app.bot.services.system_health import HealthCollector, load_health_settings
from app.config import Config

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None
_collector_config: Config | None = None
_services: ServicesContainer | None = None
_bot: Bot | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_last_state: str | None = None


def _job_id() -> str:
    return "toonel_system_health_report"


async def _send_to_admins(text: str) -> None:
    if _bot is None or _collector_config is None:
        return
    for chat_id in _collector_config.bot.ADMINS:
        try:
            await _bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception("Failed to send system health report to admin %s", chat_id)


async def run_once() -> None:
    global _last_state
    if _bot is None or _collector_config is None or _services is None or _session_factory is None:
        return

    settings = load_health_settings()
    if not settings["enabled"]:
        return

    try:
        async with _session_factory() as session:
            collector = HealthCollector(
                config=_collector_config,
                server_pool=_services.server_pool,
                bot=_bot,
                session=session,
            )
            report = await collector.collect()

        state = "error" if collector.has_errors(report) else "healthy"
        previous = _last_state
        _last_state = state

        if settings["errors_only"]:
            if previous == state:
                return
            if state == "healthy" and previous == "error":
                await _send_to_admins("✅ <b>System recovered</b>\n\nتمامی بررسی‌های سلامت به وضعیت عادی برگشتند.")
                return
            if state == "error":
                await _send_to_admins(collector.render(report))
            return

        await _send_to_admins(collector.render(report))
    except Exception:
        logger.exception("Automatic system health report failed")


def start_scheduler(
    config: Config,
    services: ServicesContainer,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    global _scheduler, _collector_config, _services, _bot, _session_factory
    if _scheduler is not None and _scheduler.running:
        return

    _collector_config = config
    _services = services
    _bot = bot
    _session_factory = session_factory
    settings = load_health_settings()
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_once,
        trigger=IntervalTrigger(minutes=settings["interval_minutes"]),
        id=_job_id(),
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info(
        "System health scheduler started: enabled=%s interval=%sm errors_only=%s",
        settings["enabled"],
        settings["interval_minutes"],
        settings["errors_only"],
    )


def restart_scheduler() -> None:
    if _scheduler is None:
        return
    settings = load_health_settings()
    job = _scheduler.get_job(_job_id())
    if job is not None:
        job.reschedule(trigger=IntervalTrigger(minutes=settings["interval_minutes"]))
