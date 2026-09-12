from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from app.bot.services import system_health as _base
from app.bot.services.system_health import HealthCollector
from app.bot.services.system_health_comprehensive import ComprehensiveHealthCollector

_HEALTHY = "healthy"
_WARNING = "warning"
_CRITICAL = "critical"


def _timestamp(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime):
        return int(value.timestamp())
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _webhook_health(bot, config):
    expected = _base.urljoin(config.bot.DOMAIN, _base.TELEGRAM_WEBHOOK)
    try:
        info = await bot.get_webhook_info()
        actual = info.url or ""
        pending = int(info.pending_update_count or 0)
        last_error = info.last_error_message or ""
        last_error_date = _timestamp(getattr(info, "last_error_date", None))
        url_ok = actual == expected

        if not url_ok:
            severity = _CRITICAL
            ok = False
            message = "Webhook URL mismatch"
        elif pending > 0 and last_error and last_error_date and time.time() - last_error_date <= 300:
            severity = _CRITICAL
            ok = False
            message = last_error
        elif last_error or pending > 0:
            severity = _WARNING
            ok = True
            message = last_error or f"{pending} update(s) pending"
        else:
            severity = _HEALTHY
            ok = True
            message = ""

        return {
            "status": "healthy" if severity == _HEALTHY else "warning" if severity == _WARNING else "unhealthy",
            "ok": ok,
            "severity": severity,
            "message": message,
            "expected": expected,
            "actual": actual,
            "pending_updates": pending,
            "last_error": last_error,
            "last_error_date": last_error_date,
            "last_error_age_seconds": (int(time.time()) - last_error_date) if last_error_date else None,
        }
    except Exception as exc:
        return {
            "status": "unhealthy",
            "ok": False,
            "severity": _CRITICAL,
            "message": str(exc),
            "expected": expected,
            "actual": "",
            "pending_updates": 0,
            "last_error": str(exc),
            "last_error_date": None,
            "last_error_age_seconds": None,
        }


_original_collect = HealthCollector.collect


async def _collect(self):
    report = await _original_collect(self)
    webhook = report.get("robot", {}).get("webhook", {})
    critical: list[str] = []
    warnings: list[str] = []

    if webhook.get("severity") == _CRITICAL:
        critical.append("webhook")
    elif webhook.get("severity") == _WARNING:
        warnings.append("webhook")

    for server in report.get("servers", []):
        if server.get("status") != "healthy":
            critical.append(f"server:{server.get('name', '-')}")
    for node in report.get("nodes", []):
        if node.get("enabled", True) and not node.get("ok", False):
            critical.append(f"node:{node.get('name', '-')}")

    robot = report.get("robot", {})
    if not (robot.get("sqlite", {}) or {}).get("ok", False):
        critical.append("sqlite")
    if not (robot.get("process", {}) or {}).get("ok", False):
        critical.append("process")

    for name, value in (robot.get("docker", {}) or {}).items():
        if value.get("ok") is False:
            critical.append(f"docker:{name}")

    severity = _CRITICAL if critical else _WARNING if warnings else _HEALTHY
    report["severity"] = severity
    report["critical_checks"] = critical
    report["warning_checks"] = warnings
    report["overall"] = severity
    return report


HealthCollector.collect = _collect
_base._webhook_health = _webhook_health


_original_render = ComprehensiveHealthCollector.render


def _render(report):
    text = _original_render(report)
    severity = report.get("severity", report.get("overall"))
    label = {
        _HEALTHY: "🟢 سالم",
        _WARNING: "🟡 هشدار",
        _CRITICAL: "🔴 بحرانی",
    }.get(severity, "🔴 دارای خطا")
    text = text.replace("وضعیت کلی: <b>🔴 دارای خطا</b>", f"وضعیت کلی: <b>{label}</b>")
    text = text.replace("وضعیت کلی: <b>🟢 سالم</b>", f"وضعیت کلی: <b>{label}</b>")

    webhook = report.get("robot", {}).get("webhook", {})
    icon = {
        _HEALTHY: "🟢",
        _WARNING: "🟡",
        _CRITICAL: "🔴",
    }.get(webhook.get("severity"), "🔴")
    marker = "🔗 <b>وضعیت Webhook</b>\n"
    if marker in text:
        before, after = text.split(marker, 1)
        first, sep, rest = after.partition("\n")
        if first in {"🟢", "🟡", "🔴", "⚪️"}:
            after = icon + sep + rest
        text = before + marker + after

    if webhook.get("last_error") and webhook.get("last_error_age_seconds") is not None:
        age = max(0, int(webhook["last_error_age_seconds"]))
        if age < 60:
            age_text = "همین الان"
        elif age < 3600:
            age_text = f"{age // 60} دقیقه قبل"
        elif age < 86400:
            age_text = f"{age // 3600} ساعت قبل"
        else:
            age_text = f"{age // 86400} روز قبل"
        old = f"آخرین خطا: {webhook['last_error']}"
        new = f"آخرین خطا: {webhook['last_error']} | زمان: {age_text}"
        text = text.replace(old, new)
    return text


ComprehensiveHealthCollector.render = staticmethod(_render)
