from __future__ import annotations

import asyncio
import logging
import time

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.models import ServicesContainer
from app.bot.services.network_health import (
    INCIDENT_PING_COUNT,
    NORMAL_PING_COUNT,
    collect_network_health,
    render_network_alert,
    update_alert_state,
    _load_state,
)
from app.bot.services.system_health import load_health_settings
from app.bot.services.system_health_comprehensive import ComprehensiveHealthCollector
from app.config import Config

logger = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None
_collector_config: Config | None = None
_services: ServicesContainer | None = None
_bot: Bot | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_last_state: str | None = None
_network_run_lock = asyncio.Lock()

NETWORK_NORMAL_INTERVAL_SECONDS = 300
NETWORK_INCIDENT_INTERVAL_SECONDS = 60
NETWORK_INTERVAL_OPTIONS = (30, 60, 120, 300, 600, 900, 1800, 3600)


def _job_id() -> str:
    return "toonel_system_health_report"


def _network_job_id() -> str:
    return "toonel_network_health_monitor"


async def _send_to_admins(text: str) -> None:
    if _bot is None or _collector_config is None:
        return
    for chat_id in _collector_config.bot.ADMINS:
        try:
            await _bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception("Failed to send system health report to admin %s", chat_id)


def _network_settings() -> tuple[bool, int, int]:
    settings = load_health_settings()
    # Adaptive monitoring is opt-in. Without an explicit persisted setting,
    # the administrator's selected normal interval is the real scheduler interval.
    adaptive = bool(settings.get("network_adaptive_enabled", False))
    normal = int(settings.get("network_interval_seconds", 60))
    incident = int(settings.get("network_incident_interval_seconds", NETWORK_INCIDENT_INTERVAL_SECONDS))
    if normal not in NETWORK_INTERVAL_OPTIONS:
        normal = 60
    if incident not in NETWORK_INTERVAL_OPTIONS:
        incident = NETWORK_INCIDENT_INTERVAL_SECONDS
    return adaptive, normal, incident


def _network_incident_mode() -> bool:
    state = _load_state()
    current = str(state.get("current", "unknown"))
    alert_level = str(state.get("alert_level", "healthy"))
    return current in {"warning", "problem", "critical"} or alert_level in {"warning", "problem", "critical"}


def _network_interval_seconds() -> int:
    adaptive, normal, incident = _network_settings()
    if not adaptive:
        return normal
    return incident if _network_incident_mode() else normal


def _network_ping_count() -> int:
    adaptive, _, _ = _network_settings()
    if adaptive and _network_incident_mode():
        return INCIDENT_PING_COUNT
    return NORMAL_PING_COUNT


def reschedule_network_job() -> None:
    """Apply the effective adaptive interval without restarting the scheduler."""
    if _scheduler is None or not _scheduler.running:
        return
    job = _scheduler.get_job(_network_job_id())
    if job is None:
        return
    seconds = _network_interval_seconds()
    job.reschedule(trigger=IntervalTrigger(seconds=seconds))
    logger.info(
        "Network health scheduler interval updated: interval=%ss adaptive=%s incident=%s ping_count=%s",
        seconds,
        _network_settings()[0],
        _network_incident_mode(),
        _network_ping_count(),
    )


async def run_network_once() -> bool:
    """Run one network check, rejecting overlapping manual/scheduled executions."""
    if _network_run_lock.locked():
        logger.info("Network health check skipped: another check is already running")
        return False

    async with _network_run_lock:
        if _bot is None or _collector_config is None or _services is None or _session_factory is None:
            logger.warning("Network health check skipped: scheduler dependencies are not initialized")
            return False
        settings = load_health_settings()
        if not settings.get("network_monitor_enabled", True):
            logger.info("Network health check skipped: network_monitor_enabled=False")
            return False

        started = time.monotonic()
        ping_count = _network_ping_count()
        effective_interval = _network_interval_seconds()
        logger.info(
            "Network health check started: adaptive=%s incident=%s interval=%ss ping_count=%s",
            _network_settings()[0],
            _network_incident_mode(),
            effective_interval,
            ping_count,
        )
        try:
            async with _session_factory() as session:
                report = await collect_network_health(
                    _collector_config,
                    _services.server_pool,
                    session,
                    ping_count=ping_count,
                )
            alert, previous = update_alert_state(report)

            servers = report.get("servers", [])
            node_count = sum(len(server.get("nodes", [])) for server in servers)
            current = "unknown"
            state_path = None
            try:
                from app.bot.services.network_health import _history_path

                state = _load_state()
                current = state.get("current", "unknown")
                state_path = str(_history_path())
            except Exception:
                logger.exception("Failed to read network health state for runtime diagnostics")

            next_interval = _network_interval_seconds()
            next_ping_count = _network_ping_count()
            logger.info(
                "Network health check completed: severity=%s previous=%s alert=%s servers=%d nodes=%d history=%s duration=%.2fs next_interval=%ss next_ping_count=%s",
                current,
                previous,
                alert or "none",
                len(servers),
                node_count,
                state_path or "unknown",
                time.monotonic() - started,
                next_interval,
                next_ping_count,
            )

            # Move the scheduler after state persistence so degraded samples immediately
            # switch the next cycle to incident mode; recovery keeps incident mode until
            # the existing RECOVERY_SAMPLES threshold is satisfied.
            reschedule_network_job()

            if alert == "degraded":
                await _send_to_admins(render_network_alert(report, recovered=False))
            elif alert == "recovered":
                await _send_to_admins(render_network_alert(report, recovered=True))
            return True
        except Exception:
            logger.exception("Automatic network health check failed")
            return False


async def run_once() -> None:
    global _last_state
    if _bot is None or _collector_config is None or _services is None or _session_factory is None:
        return

    settings = load_health_settings()
    if not settings["enabled"]:
        return

    try:
        async with _session_factory() as session:
            collector = ComprehensiveHealthCollector(
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
    _scheduler.add_job(
        run_network_once,
        trigger=IntervalTrigger(seconds=_network_interval_seconds()),
        id=_network_job_id(),
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info(
        "System health scheduler started: enabled=%s interval=%sm errors_only=%s network_monitor=%s network_adaptive=%s network_interval=%ss incident_interval=%ss ping_normal=%s ping_incident=%s",
        settings["enabled"],
        settings["interval_minutes"],
        settings["errors_only"],
        settings.get("network_monitor_enabled", True),
        _network_settings()[0],
        _network_settings()[1],
        _network_settings()[2],
        NORMAL_PING_COUNT,
        INCIDENT_PING_COUNT,
    )
    # The Network Health UI historically reschedules this job immediately after
    # start_scheduler(). Re-apply the effective adaptive interval one event-loop
    # turn later so the UI cannot accidentally disable adaptive startup behavior.
    try:
        asyncio.get_running_loop().call_soon(reschedule_network_job)
    except RuntimeError:
        pass


def restart_scheduler() -> None:
    if _scheduler is None:
        return
    settings = load_health_settings()
    job = _scheduler.get_job(_job_id())
    if job is not None:
        job.reschedule(trigger=IntervalTrigger(minutes=settings["interval_minutes"]))
    reschedule_network_job()
