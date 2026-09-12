from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.services.server_pool import ServerPoolService
from app.bot.services.xui_inbound_adapter import get_inbounds
from app.bot.utils.constants import TELEGRAM_WEBHOOK
from app.config import Config
from app.db.models import Server

logger = logging.getLogger(__name__)

SETTINGS_PATHS = (Path("/app/data/system_health_settings.json"), Path("data/system_health_settings.json"))
DEFAULT_SETTINGS = {"enabled": False, "interval_minutes": 15, "errors_only": True}
INTERVALS = (5, 15, 30, 60, 360, 720, 1440)


def _settings_path() -> Path:
    for path in SETTINGS_PATHS:
        if path.parent.exists():
            return path
    return SETTINGS_PATHS[0]


def load_health_settings() -> dict[str, Any]:
    path = _settings_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        result = DEFAULT_SETTINGS | data
        result["interval_minutes"] = int(result["interval_minutes"])
        if result["interval_minutes"] not in INTERVALS:
            result["interval_minutes"] = DEFAULT_SETTINGS["interval_minutes"]
        return result
    except Exception:
        logger.exception("Failed to load system health settings")
        return DEFAULT_SETTINGS.copy()


def save_health_settings(**changes: Any) -> dict[str, Any]:
    settings = load_health_settings()
    settings.update(changes)
    settings["enabled"] = bool(settings["enabled"])
    settings["errors_only"] = bool(settings["errors_only"])
    settings["interval_minutes"] = int(settings["interval_minutes"])
    if settings["interval_minutes"] not in INTERVALS:
        raise ValueError("Unsupported health report interval")
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return settings


def _parse_settings(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
            return value if isinstance(value, dict) else {}
        except Exception:
            return {}
    return {}


def _client_stats(inbounds: list[Any]) -> dict[str, int]:
    total = enabled = disabled = expired = 0
    now_ms = int(time.time() * 1000)
    for inbound in inbounds:
        settings = _parse_settings(getattr(inbound, "settings", None))
        clients = settings.get("clients") or []
        if not isinstance(clients, list):
            continue
        for client in clients:
            if not isinstance(client, dict):
                continue
            total += 1
            if bool(client.get("enable", True)):
                enabled += 1
            else:
                disabled += 1
            expiry = client.get("expiryTime")
            try:
                if expiry and int(expiry) > 0 and int(expiry) < now_ms:
                    expired += 1
            except (TypeError, ValueError):
                pass
    return {"total": total, "enabled": enabled, "disabled": disabled, "expired": expired}


def _status(ok: bool, message: str = "") -> dict[str, Any]:
    return {"status": "healthy" if ok else "unhealthy", "ok": ok, "message": message}


async def _run(command: str, *args: str, timeout: float = 8.0) -> tuple[int, str, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            command,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return process.returncode or 0, stdout.decode(errors="replace").strip(), stderr.decode(errors="replace").strip()
    except Exception as exc:
        return 1, "", str(exc)


async def _docker_container(name: str) -> dict[str, Any]:
    """Check Docker only when this runtime can actually reach the Docker daemon."""
    code, out, err = await _run(
        "docker",
        "inspect",
        "--format",
        "{{.State.Status}}|{{if .State.Health}}{{.State.Health.Status}}{{end}}|{{.RestartCount}}",
        name,
    )
    if code != 0:
        return {"status": "unavailable", "ok": None, "name": name, "message": err or "Docker daemon is not accessible from bot runtime"}
    parts = out.split("|", 2)
    state = parts[0] if parts else "unknown"
    health = parts[1] if len(parts) > 1 and parts[1] else "running"
    restarts = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0
    ok = state == "running" and health not in {"unhealthy", "dead"}
    return _status(ok) | {"name": name, "state": state, "health": health, "restarts": restarts}


async def _process_status() -> dict[str, Any]:
    """Check the current bot process only; host nginx is outside this container."""
    pid = os.getpid()
    return _status(pid > 0, f"bot process pid={pid}") | {"pid": pid}


async def _sqlite_health() -> dict[str, Any]:
    candidates = (Path("/app/data/bot_database.sqlite3"), Path("data/bot_database.sqlite3"))
    db_path = next((p for p in candidates if p.exists()), None)
    if db_path is None:
        return _status(False, "SQLite database file not found")
    try:
        size = db_path.stat().st_size

        def check() -> str:
            conn = sqlite3.connect(str(db_path), timeout=5)
            try:
                return str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            finally:
                conn.close()

        integrity = await asyncio.to_thread(check)
        return _status(integrity.lower() == "ok", integrity) | {"path": str(db_path), "size": size, "integrity": integrity}
    except Exception as exc:
        return _status(False, str(exc)) | {"path": str(db_path)}


async def _resources() -> dict[str, Any]:
    disk = shutil.disk_usage("/")
    cpu_count = os.cpu_count() or 1
    load1 = os.getloadavg()[0] if hasattr(os, "getloadavg") else 0.0
    mem_total = mem_available = mem_used = 0
    try:
        meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
        values = {
            line.split(":", 1)[0]: int(line.split()[1]) * 1024
            for line in meminfo.splitlines()
            if ":" in line and line.split()[1].isdigit()
        }
        mem_total = values.get("MemTotal", 0)
        mem_available = values.get("MemAvailable", values.get("MemFree", 0))
        mem_used = max(0, mem_total - mem_available)
    except Exception:
        logger.exception("Failed to read /proc/meminfo")
    cpu_percent = min(100.0, round((load1 / cpu_count) * 100, 1))
    ram_percent = round((mem_used / mem_total) * 100, 1) if mem_total else 0.0
    disk_percent = round((disk.used / disk.total) * 100, 1)
    return {
        "cpu": {"percent": cpu_percent, "load1": round(load1, 2), "cores": cpu_count},
        "ram": {"percent": ram_percent, "used": mem_used, "total": mem_total, "available": mem_available},
        "disk": {"percent": disk_percent, "used": disk.used, "total": disk.total, "free": disk.free},
    }


async def _webhook_health(bot: Bot, config: Config) -> dict[str, Any]:
    expected = urljoin(config.bot.DOMAIN, TELEGRAM_WEBHOOK)
    try:
        info = await bot.get_webhook_info()
        actual = info.url or ""
        ok = actual == expected and not info.last_error_message
        return _status(ok, info.last_error_message or ("Webhook URL mismatch" if actual != expected else "")) | {
            "expected": expected,
            "actual": actual,
            "pending_updates": info.pending_update_count,
            "last_error": info.last_error_message,
        }
    except Exception as exc:
        return _status(False, str(exc)) | {"expected": expected}


@dataclass
class HealthCollector:
    config: Config
    server_pool: ServerPoolService
    bot: Bot
    session: AsyncSession | None = None
    _last_state: str | None = field(default=None, init=False)

    async def _servers(self) -> list[dict[str, Any]]:
        if self.session is None:
            return [{"name": "ServerPool", "status": "unhealthy", "panel": _status(False, "Database session unavailable"), "inbounds": [], "clients": _client_stats([])}]

        servers: list[dict[str, Any]] = []
        db_servers = await Server.get_all(self.session)
        for server in db_servers:
            item: dict[str, Any] = {"id": server.id, "name": server.name, "host": server.host}
            try:
                # Prefer the already-live ServerPool connection. If a server is not
                # currently in the pool, build a temporary API client for a read-only
                # health probe instead of calling get_connection_for_server(), which
                # may reconnect the server and write its online flag to the database.
                connection = self.server_pool._servers.get(server.id)
                api = connection.api if connection is not None else self.server_pool._build_api(server)
                inbounds = await get_inbounds(api)
                inbound_rows = [
                    {
                        "id": i.id,
                        "remark": getattr(i, "remark", ""),
                        "port": getattr(i, "port", None),
                        "protocol": getattr(i, "protocol", ""),
                        "enable": bool(getattr(i, "enable", True)),
                    }
                    for i in inbounds
                ]
                enabled = sum(1 for i in inbound_rows if i["enable"])
                servers.append(
                    item
                    | {
                        "status": "healthy",
                        "panel": _status(True, "X-UI API reachable"),
                        "inbounds": inbound_rows,
                        "inbound_total": len(inbounds),
                        "inbound_enabled": enabled,
                        "clients": _client_stats(inbounds),
                    }
                )
            except Exception as exc:
                logger.warning("Health check failed for server %s: %s", server.name, exc)
                servers.append(item | {"status": "unhealthy", "panel": _status(False, str(exc)), "inbounds": [], "clients": _client_stats([])})
        return servers

    async def collect(self) -> dict[str, Any]:
        resources, sqlite, webhook = await asyncio.gather(
            _resources(), _sqlite_health(), _webhook_health(self.bot, self.config)
        )
        docker = {
            "bot": await _docker_container("3xui-shop-bot"),
            "redis": await _docker_container("3xui-shop-redis"),
        }
        process = await _process_status()
        try:
            servers = await self._servers()
        except Exception as exc:
            logger.exception("System health server collection failed")
            servers = [{"name": "ServerPool", "status": "unhealthy", "panel": _status(False, str(exc)), "inbounds": [], "clients": _client_stats([])}]

        checks = [bool(webhook["ok"]), bool(sqlite["ok"])]
        checks.extend(s["status"] == "healthy" for s in servers)
        checks.append(bool(process["ok"]))
        for value in docker.values():
            if value.get("ok") is not None:
                checks.append(bool(value["ok"]))
        overall = all(checks) if checks else False
        return {
            "timestamp": int(time.time()),
            "overall": "healthy" if overall else "unhealthy",
            "servers": servers,
            "robot": {"docker": docker, "process": process, "webhook": webhook, "sqlite": sqlite},
            "resources": resources,
            "settings": load_health_settings(),
        }

    @staticmethod
    def has_errors(report: dict[str, Any]) -> bool:
        return report.get("overall") != "healthy"

    @staticmethod
    def render(report: dict[str, Any]) -> str:
        def icon(ok: bool | None) -> str:
            return "🟢" if ok is True else "🔴" if ok is False else "⚪️"

        r = report["resources"]
        lines = [
            "❤️ <b>گزارش سلامت سیستم ToonelVPN</b>",
            f"\nوضعیت کلی: <b>{'🟢 سالم' if report['overall'] == 'healthy' else '🔴 دارای خطا'}</b>",
            f"\n🖥 <b>منابع</b>\nCPU: {r['cpu']['percent']}%\nRAM: {r['ram']['percent']}%\nDisk: {r['disk']['percent']}%",
        ]
        for server in report["servers"]:
            clients = server.get("clients", {})
            lines.append(
                f"\n🌍 <b>{server['name']}</b> {icon(server.get('status') == 'healthy')}\n"
                f"X-UI: {icon(server.get('panel', {}).get('ok'))}\n"
                f"Inbound: {server.get('inbound_enabled', 0)}/{server.get('inbound_total', 0)} فعال\n"
                f"Client: {clients.get('enabled', 0)}/{clients.get('total', 0)} فعال | {clients.get('expired', 0)} منقضی"
            )
        robot = report["robot"]
        lines.append(
            f"\n🐳 <b>Docker</b>\nBot: {icon(robot['docker']['bot'].get('ok'))}\nRedis: {icon(robot['docker']['redis'].get('ok'))}"
            f"\n⚙️ <b>Process</b>\nBot process: {icon(robot['process'].get('ok'))}"
            f"\n🔗 Webhook: {icon(robot['webhook'].get('ok'))}\n🗄 SQLite: {icon(robot['sqlite'].get('ok'))}"
        )
        return "\n".join(lines)


async def get_system_health_dashboard(collector: HealthCollector) -> dict[str, Any]:
    return await collector.collect()
