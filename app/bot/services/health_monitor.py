from __future__ import annotations

import asyncio
import shutil
import time


async def collect_health_report() -> dict:
    """Collect a lightweight local health snapshot for admin reporting."""
    disk = shutil.disk_usage("/")
    return {
        "hostname": __import__("socket").gethostname(),
        "uptime": _uptime(),
        "disk_percent": round((disk.used / disk.total) * 100, 1),
        "checks": {
            "python": True,
            "event_loop": True,
        },
    }


def _uptime() -> str:
    try:
        seconds = int(time.time() - float(open("/proc/uptime").read().split()[0]))
    except Exception:
        return "unknown"
    days, rem = divmod(seconds, 86400)
    hours, _ = divmod(rem, 3600)
    return f"{days}d {hours}h"
