from __future__ import annotations

import os
import platform
import shutil
import socket
import time

_START_TIME = time.time()


def _format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(value)
    for unit in units:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


async def get_system_health_report() -> dict:
    """Collect runtime health information for admin dashboard."""
    uptime = int(time.time() - _START_TIME)
    disk = shutil.disk_usage("/")

    return {
        "status": "ok",
        "hostname": socket.gethostname(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "uptime_seconds": uptime,
        "cpu_count": os.cpu_count() or 0,
        "disk": {
            "total": _format_bytes(disk.total),
            "free": _format_bytes(disk.free),
            "used": _format_bytes(disk.used),
        },
        "nodes": [
            {"name": "Germany", "status": "configured"},
            {"name": "Netherlands", "status": "configured"},
        ],
    }
