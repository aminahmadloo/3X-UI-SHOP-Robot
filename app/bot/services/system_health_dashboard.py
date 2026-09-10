from __future__ import annotations

import os
import shutil
from pathlib import Path


def _sqlite_size() -> int:
    for path in (Path("data/bot_database.sqlite3"), Path("/app/data/bot_database.sqlite3")):
        if path.exists():
            return path.stat().st_size
    return 0


async def get_system_health_dashboard() -> dict:
    disk = shutil.disk_usage("/")
    return {
        "servers": [{"name": "Germany", "status": "configured"}, {"name": "Netherlands", "status": "configured"}],
        "robot": {"docker": "runtime-check", "process": "runtime-check", "webhook": "runtime-check"},
        "database": {"sqlite_size": _sqlite_size(), "connections": "runtime"},
        "resources": {"cpu": os.cpu_count() or 0, "disk_total": disk.total, "disk_used": disk.used, "disk_free": disk.free},
        "reports": {"enabled": True, "interval": "configurable", "errors_only": False},
    }
