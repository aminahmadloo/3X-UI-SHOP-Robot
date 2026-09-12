from __future__ import annotations

import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.bot.models import ServicesContainer
from app.bot.services.system_health import HealthCollector, load_health_settings
from app.config import Config

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None
_collector: HealthCollector | None = None


def _job_id() -> str:
    return "toonel_system_health_report"


async def _send_to_admins(text: str) -> None:
    if _collector is None:
        return
    for chat_id in _collector.config.bot.ADMINS:
        try:
            await _collector.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception("Failed to send system health report to admin %s", chat_id)


async def run_once() -> None:
    if _collector is None:
        return
    settings = load_health_settings()
    if not settings["enabled"]:
        return
    try:
        report = await _collector.collect()
        state = "error" if _collector.has_errors(report) else "healthy"
        previous = _collector._last_state
        _collector._last_state = state

        if settings["errors_only"]:
            if previous == state:
                return
            if state == "healthy" and previous == "error":
                await _send_to_admins("✅ <b>System recovered</b>\n\nتمامی بررسی‌های سلامت به وضعیت عادی برگشتند.")
                return
            if state == "error":
                await _send_to_admins(_collector.render(report))
            return

        await _send_to_admins(_collector.render(report))
    except Exception:
        logger.exception("Automatic system health report failed")


def start_scheduler(config: Config, services: ServicesContainer, bot: Bot) -> None:
    global _scheduler, _collector
    if _scheduler is not None and _scheduler.running:
        return
    _collector = HealthCollector(config=config, session_factory=services.server_pool.session, server_pool=services.server_pool, bot=bot)
    settings = load_health_settings()
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(run_once, trigger=IntervalTrigger(minutes=settings["interval_minutes"]), id=_job_id(), replace_existing=True, max_instances=1, coalesce=True)
    _scheduler.start()
    logger.info("System health scheduler started: enabled=%s interval=%sm errors_only=%s", settings["enabled"], settings["interval_minutes"], settings["errors_only"])


def restart_scheduler() -> None:
    if _scheduler is None:
        return
    settings = load_health_settings()
    job = _scheduler.get_job(_job_id())
    if job is not None:
        job.reschedule(trigger=IntervalTrigger(minutes=settings["interval_minutes"]))
