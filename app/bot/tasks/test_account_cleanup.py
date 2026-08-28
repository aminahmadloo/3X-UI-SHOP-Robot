import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.services.test_account import TestAccountService

logger = logging.getLogger(__name__)


async def cleanup_test_accounts(test_account_service: TestAccountService) -> None:
    try:
        await test_account_service.cleanup_expired()
    except Exception:
        logger.exception("Test account cleanup job failed.")


def start_scheduler(
    test_account_service: TestAccountService,
) -> None:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        cleanup_test_accounts,
        "interval",
        hours=12,
        args=[test_account_service],
        next_run_time=datetime.now(),
        id="test_account_cleanup",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("Test account cleanup scheduler started (every 12 hours).")
