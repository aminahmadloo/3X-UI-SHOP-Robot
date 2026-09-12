from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from aiogram import Bot

from app.bot.models import ServicesContainer
from app.bot.services.system_health import HealthCollector, load_health_settings
from app.config import Config

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None
_collector: HealthCollector | None = None


def _job_id() -> str:
    return "toonel_system_health_report"


async def run_once() -> None:
    if _collector is None:
        return
    settings = load_health_settings()
    if not settings["enabled"]:
        return
    try:
        report = await _collector.collect()
        if settings["errors_only"] and not _collector.has_errors(report):
            _collector._last_state = "healthy"
            return
        state = "error" if _collector.has_errors(report) else "healthy"
        # Error-only mode is edge-triggered to prevent Telegram spam while a fault persists.
        if settings["errors_only"] and _collector._last_state == state:
            return
        _collector._last_state = state
        await _collector.server_pool.config  # keep service object alive for older runtime DI
        await _collector.bot.send_message(
            chat_id=_collector.config.bot.DEV_ID,
            text=_collector.render(report),
        )
        if state == "healthy" and settings["errors_only"]:
            await _collector.bot.send_message(
                chat_id=_collector.config.bot.DEV_ID,
                text="✅ <b>System recovered</b>\n\nتمامی بررسی‌های سلامت به وضعیت عادی برگشتند.",
            )
    except Exception:
        logger.exception("Automatic system health report failed")


def start_scheduler(config: Config, services: ServicesContainer, bot: Bot) -> None:
    global _scheduler, _collector
    if _scheduler is not None and _scheduler.running:
        return
    _collector = HealthCollector(
        config=config,
        session_factory=services.server_pool.session,
        server_pool=services.server_pool,
        bot=bot,
    )
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
    logger.info("System health scheduler started: enabled=%s interval=%sm errors_only=%s", settings["enabled"], settings["interval_minutes"], settings["errors_only"])


def restart_scheduler() -> None:
    if _scheduler is None:
        return
    settings = load_health_settings()
    job = _scheduler.get_job(_job_id())
    if job is None:
        return
    job.reschedule(trigger=IntervalTrigger(minutes=settings["interval_minutes"]))
