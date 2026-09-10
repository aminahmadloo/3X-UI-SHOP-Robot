from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class SystemHealthNotificationSettings:
    """Runtime settings for automated admin health reports.

    Persistence can be connected to the existing settings storage later without
    changing the scheduler interface.
    """

    enabled: bool = True
    interval_hours: int = 6
    errors_only: bool = False


_ALLOWED_INTERVALS = (1, 3, 6, 12, 24)


def normalize_health_interval(hours: int) -> int:
    if hours in _ALLOWED_INTERVALS:
        return hours
    return 6


def build_health_notification_text(settings: SystemHealthNotificationSettings) -> str:
    state = "فعال" if settings.enabled else "غیرفعال"
    mode = "فقط خطاها" if settings.errors_only else "گزارش کامل"
    return (
        "🩺 تنظیمات گزارش سلامت سیستم\n\n"
        f"وضعیت: {state}\n"
        f"بازه ارسال: هر {settings.interval_hours} ساعت\n"
        f"نوع گزارش: {mode}"
    )
