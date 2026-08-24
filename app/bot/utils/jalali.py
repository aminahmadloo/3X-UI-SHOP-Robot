from datetime import datetime
from zoneinfo import ZoneInfo

from persiantools.jdatetime import JalaliDateTime


def format_jalali(dt: datetime | None) -> str:
    if not dt:
        return "نامشخص"

    if dt.tzinfo:
        dt = dt.astimezone(ZoneInfo("Asia/Tehran"))

    return JalaliDateTime(dt).strftime("%Y/%m/%d %H:%M")
