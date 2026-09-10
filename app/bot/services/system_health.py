from __future__ import annotations

import platform
import socket
import time


_START_TIME = time.time()


async def get_system_health_report() -> dict:
    """Collect lightweight runtime health information for admin dashboard."""
    uptime = int(time.time() - _START_TIME)
    return {
        "hostname": socket.gethostname(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "uptime_seconds": uptime,
        "status": "ok",
    }
