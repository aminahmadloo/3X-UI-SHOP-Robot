from __future__ import annotations

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.bot.services.test_account import TestAccountService

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def cleanup_test_accounts(
    test_account_service: TestAccountService,
) -> None:
    try:
        await test_account_service.cleanup_expired()
    except Exception:
        logger.exception("Test account cleanup job failed.")


def reschedule_cleanup(hours: int) -> None:
    global _scheduler

    try:
        interval = int(hours)
    except (TypeError, ValueError):
        interval = 12

    interval = max(1, min(interval, 168))

    if _scheduler is None:
        logger.warning(
            "Test account cleanup scheduler is not initialized; "
            "interval %s hours will be used after restart.",
            interval,
        )
        return

    _scheduler.reschedule_job(
        "test_account_cleanup",
        trigger=IntervalTrigger(hours=interval),
    )

    logger.info(
        "Test account cleanup scheduler rescheduled: every %s hour(s).",
        interval,
    )


async def start_scheduler(
    test_account_service: TestAccountService,
) -> None:
    global _scheduler

    interval = 12

    try:
        async with test_account_service.session_factory() as session:
            settings = await test_account_service.get_settings(session)
            interval = int(settings.cleanup_interval_hours)
    except Exception:
        logger.exception(
            "Could not load test account cleanup interval from database; "
            "falling back to 12 hours."
        )

    interval = max(1, min(interval, 168))

    scheduler = AsyncIOScheduler()

    scheduler.add_job(
        cleanup_test_accounts,
        "interval",
        hours=interval,
        args=[test_account_service],
        next_run_time=datetime.now(),
        id="test_account_cleanup",
        replace_existing=True,
    )

    _scheduler = scheduler
    scheduler.start()

    logger.info(
        "Test account cleanup scheduler started "
        "(every %s hour(s)).",
        interval,
    )
