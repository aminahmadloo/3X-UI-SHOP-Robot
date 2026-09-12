from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from aiogram import Bot

from app.bot.services.system_health import HealthCollector, _api_url, _status, load_health_settings
from app.config import Config

logger = logging.getLogger(__name__)


async def _http_json_method(url: str, token: str | None = None, method: str = "GET", timeout: float = 8.0) -> Any:
    def request() -> Any:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = Request(url, headers=headers, method=method)
        with urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    return await asyncio.to_thread(request)


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "obj" in payload:
        return payload["obj"]
    return payload


def _client_key(client: dict[str, Any]) -> str:
    for key in ("email", "id", "password", "subId"):
        value = client.get(key)
        if value:
            return str(value)
    return json.dumps(client, sort_keys=True, ensure_ascii=False)


def _client_rows(inbounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    for inbound in inbounds:
        settings = inbound.get("settings") or {}
        if isinstance(settings, str):
            try:
                settings = json.loads(settings)
            except Exception:
                settings = {}
        for client in settings.get("clients") or []:
            if not isinstance(client, dict):
                continue
            key = _client_key(client)
            unique.setdefault(key, client)
    return list(unique.values())


def _client_stats_from_rows(clients: list[dict[str, Any]]) -> dict[str, int]:
    now_ms = int(time.time() * 1000)
    total = enabled = disabled = expired = 0
    for client in clients:
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


def _inbound_rows(raw: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        rows.append({
            "id": item.get("id"),
            "remark": item.get("remark") or item.get("tag") or "-",
            "tag": item.get("tag") or "",
            "port": item.get("port"),
            "protocol": item.get("protocol") or "-",
            "enable": bool(item.get("enable", True)),
            "node_id": item.get("nodeId"),
            "node_address": item.get("nodeAddress") or "",
            "settings": item.get("settings") or {},
        })
    return rows


def _group_inbounds(rows: list[dict[str, Any]], node_by_id: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for row in rows:
        node_id = row.get("node_id")
        if node_id is None:
            key = "local"
            title = "سرور اصلی"
            address = ""
        else:
            key = f"node:{node_id}"
            node = node_by_id.get(int(node_id), {})
            title = node.get("name") or row.get("node_address") or f"Node {node_id}"
            address = node.get("address") or row.get("node_address") or ""
        group = groups.setdefault(key, {"key": key, "name": title, "address": address, "inbounds": []})
        group["inbounds"].append(row)
    for group in groups.values():
        group["enabled"] = sum(1 for row in group["inbounds"] if row.get("enable"))
        group["total"] = len(group["inbounds"])
        clients = _client_rows(group["inbounds"])
        group["clients"] = _client_stats_from_rows(clients)
        group["client_rows"] = clients
    return list(groups.values())


async def _raw_inbounds(server, config: Config) -> list[dict[str, Any]]:
    try:
        payload = _unwrap(await _http_json_method(_api_url(server, "panel/api/inbounds/list"), config.xui.TOKEN))
        return _inbound_rows(payload if isinstance(payload, list) else [])
    except Exception as exc:
        logger.warning("Comprehensive inbound collection failed for %s: %s", server.name, exc)
        return []


async def _online_by_guid(server, config: Config) -> dict[str, list[str]]:
    try:
        payload = _unwrap(await _http_json_method(_api_url(server, "panel/api/clients/onlinesByGuid"), config.xui.TOKEN, method="POST"))
        return payload if isinstance(payload, dict) else {}
    except Exception as exc:
        logger.debug("Online-by-guid unavailable for %s: %s", server.name, exc)
        return {}


async def _sqlite_backup() -> tuple[Path | None, str | None]:
    source_candidates = (Path("/app/data/bot_database.sqlite3"), Path("data/bot_database.sqlite3"))
    source = next((p for p in source_candidates if p.exists()), None)
    if source is None:
        return None, "SQLite database file not found"
    backup_dir = Path("/app/data/backups") if Path("/app/data").exists() else Path("data/backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"bot_database_{time.strftime('%Y%m%d_%H%M%S')}.sqlite3"

    def backup() -> None:
        src = sqlite3.connect(str(source), timeout=10)
        dst = sqlite3.connect(str(target), timeout=10)
        try:
            src.backup(dst)
            dst.execute("PRAGMA integrity_check")
            dst.commit()
        finally:
            dst.close()
            src.close()

    try:
        await asyncio.to_thread(backup)
        return target, None
    except Exception as exc:
        return None, str(exc)


class ComprehensiveHealthCollector(HealthCollector):
    """Health collector with server/node attribution for inbounds, clients and resources."""

    async def collect(self) -> dict[str, Any]:
        report = await super().collect()
        node_list = report.get("nodes", [])
        node_by_id = {int(node["id"]): node for node in node_list if node.get("id") is not None}

        for server in report.get("servers", []):
            db_server = None
            if self.session is not None:
                try:
                    from app.db.models import Server
                    db_servers = await Server.get_all(self.session)
                    db_server = next((item for item in db_servers if item.id == server.get("id")), None)
                except Exception:
                    db_server = None
            if db_server is None:
                continue

            raw = await _raw_inbounds(db_server, self.config)
            if not raw:
                continue
            groups = _group_inbounds(raw, node_by_id)
            online_map = await _online_by_guid(db_server, self.config)
            local_guid = (server.get("panel") or {}).get("panel_guid") or ""
            for group in groups:
                if group["key"] == "local":
                    group["online"] = len(online_map.get(local_guid, [])) if local_guid else 0
                else:
                    try:
                        node_id = int(group["key"].split(":", 1)[1])
                        node = node_by_id.get(node_id, {})
                        group["online"] = int(node.get("online_count", 0) or 0)
                    except Exception:
                        group["online"] = 0
            server["inbound_groups"] = groups
            server["inbounds"] = [row for group in groups for row in group["inbounds"]]
            server["inbound_total"] = len(server["inbounds"])
            server["inbound_enabled"] = sum(1 for row in server["inbounds"] if row.get("enable"))
            server["client_groups"] = [
                {"name": group["name"], "address": group["address"], "stats": group["clients"], "online": group.get("online", 0)}
                for group in groups
            ]

        report["resources_by_server"] = []
        for server in report.get("servers", []):
            panel = server.get("panel") or {}
            report["resources_by_server"].append({
                "name": server.get("name"),
                "address": server.get("host"),
                "cpu": panel.get("cpu"),
                "load": panel.get("load") or {},
                "ram": panel.get("memory_percent"),
                "disk": panel.get("disk_percent"),
                "xray": (panel.get("xray") or {}).get("state"),
                "kind": "server",
            })
        for node in node_list:
            report["resources_by_server"].append({
                "name": node.get("name"),
                "address": node.get("address"),
                "cpu": node.get("cpu_percent"),
                "load": None,
                "ram": node.get("memory_percent"),
                "disk": None,
                "xray": node.get("xray_state"),
                "kind": "node",
            })
        report["docker_scope_note"] = "Docker daemon is only inspectable where the Bot runtime has access to that host's Docker socket/agent; 3X-UI Node API does not expose Docker state."
        return report

    @staticmethod
    def render(report: dict[str, Any]) -> str:
        def icon(value: bool | None) -> str:
            return "🟢" if value is True else "🔴" if value is False else "⚪️"

        lines = [
            "❤️ <b>گزارش سلامت سیستم ToonelVPN</b>",
            f"\nوضعیت کلی: <b>{'🟢 سالم' if report.get('overall') == 'healthy' else '🔴 دارای خطا'}</b>",
        ]

        lines.append("\n📡 <b>وضعیت X-UI</b>")
        for server in report.get("servers", []):
            panel = server.get("panel") or {}
            xray = panel.get("xray") or {}
            lines.append(
                f"\n🇩🇪 <b>{server.get('name','-')}</b> {icon(server.get('status') == 'healthy')}\n"
                f"X-UI: {icon(panel.get('ok'))} | Xray: {icon(str(xray.get('state','')).lower() == 'running')}\n"
                f"CPU: {panel.get('cpu','-')}% | RAM: {panel.get('memory_percent','-')}% | Disk: {panel.get('disk_percent','-')}%"
            )
        for node in report.get("nodes", []):
            lines.append(
                f"\n🧩 <b>{node.get('name','-')}</b> {icon(node.get('ok') if node.get('enabled', True) else None)}\n"
                f"Parent: {node.get('parent_server','-')} | <code>{node.get('address','-')}</code>:{node.get('port','-')}\n"
                f"X-UI Node: {node.get('status','-')} | Ping: {node.get('latency_ms','-')} ms\n"
                f"CPU: {node.get('cpu_percent','-')}% | RAM: {node.get('memory_percent','-')}% | Xray: {node.get('xray_state','-')}"
            )

        lines.append("\n🔌 <b>Inboundها</b>")
        for server in report.get("servers", []):
            groups = server.get("inbound_groups") or []
            if not groups:
                lines.append(f"\n<b>{server.get('name','-')}</b>: {server.get('inbound_enabled',0)}/{server.get('inbound_total',0)} فعال")
            for group in groups:
                lines.append(f"\n<b>{server.get('name','-')} / {group['name']}</b>: {group['enabled']}/{group['total']} فعال")
                for inbound in group["inbounds"]:
                    lines.append(f"{icon(inbound.get('enable'))} {inbound.get('remark','-')} | {inbound.get('protocol','-')} | {inbound.get('port','-')}")

        lines.append("\n👤 <b>Clientها</b>")
        for server in report.get("servers", []):
            groups = server.get("client_groups") or []
            if not groups:
                c = server.get("clients") or {}
                lines.append(f"\n<b>{server.get('name','-')}</b>: {c.get('enabled',0)}/{c.get('total',0)} فعال | {c.get('disabled',0)} غیرفعال | {c.get('expired',0)} منقضی")
            for group in groups:
                c = group["stats"]
                lines.append(
                    f"\n<b>{server.get('name','-')} / {group['name']}</b>: "
                    f"{c.get('enabled',0)}/{c.get('total',0)} فعال | {c.get('disabled',0)} غیرفعال | {c.get('expired',0)} منقضی | Online: {group.get('online',0)}"
                )

        docker = report.get("robot", {}).get("docker", {})
        lines.append(
            "\n🐳 <b>Docker</b>\n"
            f"Bot runtime — Bot: {icon(docker.get('bot',{}).get('ok'))} | Redis: {icon(docker.get('redis',{}).get('ok'))}\n"
            "Hostهای X-UI: وضعیت Docker از API استاندارد 3X-UI قابل دریافت نیست و برای دسترسی واقعی به Docker daemon باید Agent/socket امن اضافه شود."
        )

        process = report.get("robot", {}).get("process", {})
        lines.append(
            f"\n⚙️ <b>فرآیندها</b>\nBot: {icon(process.get('ok'))} | PID: <code>{process.get('pid','-')}</code>\n"
            "Xray هر Host/Node در بخش X-UI با وضعیت running بررسی شده است."
        )

        webhook = report.get("robot", {}).get("webhook", {})
        lines.append(
            f"\n🔗 <b>وضعیت Webhook</b>\n{icon(webhook.get('ok'))}\n"
            f"آدرس مورد انتظار: <code>{webhook.get('expected','-')}</code>\n"
            f"آدرس فعلی: <code>{webhook.get('actual','-')}</code>\n"
            f"پیام‌های در انتظار: {webhook.get('pending_updates',0)}\n"
            f"آخرین خطا: {webhook.get('last_error') or 'ندارد'}"
        )

        sqlite = report.get("robot", {}).get("sqlite", {})
        lines.append(
            f"\n🗄 <b>وضعیت SQLite</b>\n{icon(sqlite.get('ok'))}\n"
            f"مسیر: <code>{sqlite.get('path','-')}</code>\n"
            f"حجم: {sqlite.get('size',0):,} bytes\n"
            f"Integrity: {sqlite.get('integrity','-')}"
        )

        lines.append("\n📊 <b>CPU / RAM / Disk</b>")
        for item in report.get("resources_by_server", []):
            lines.append(
                f"\n<b>{item.get('name','-')}</b> — <code>{item.get('address','-')}</code>\n"
                f"CPU: {item.get('cpu','-')}% | RAM: {item.get('ram','-')}% | Disk: {item.get('disk','-') if item.get('disk') is not None else 'از API Node ارائه نمی‌شود'}"
            )
        r = report.get("resources") or {}
        lines.append(f"\n<b>Bot runtime</b>\nCPU: {r.get('cpu',{}).get('percent','-')}% | RAM: {r.get('ram',{}).get('percent','-')}% | Disk: {r.get('disk',{}).get('percent','-')}%")
        return "\n".join(lines)


async def create_sqlite_backup() -> tuple[Path | None, str | None]:
    return await _sqlite_backup()


async def latest_sqlite_backup() -> Path | None:
    backup_dir = Path("/app/data/backups") if Path("/app/data/backups").exists() else Path("data/backups")
    if not backup_dir.exists():
        return None
    files = sorted(backup_dir.glob("bot_database_*.sqlite3"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None
