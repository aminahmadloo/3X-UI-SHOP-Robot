from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.services.server_pool import ServerPoolService
from app.bot.services.system_health import _managed_nodes, _status
from app.config import Config
from app.db.models import Server

logger = logging.getLogger(__name__)

HISTORY_PATHS = (Path("/app/data/network_health_history.json"), Path("data/network_health_history.json"))
PING_COUNT = 20
PING_TIMEOUT = 2
RECOVERY_SAMPLES = 2
ALERT_SAMPLES = 3
MAX_HISTORY = 360
TARGETS = ("1.1.1.1", "8.8.8.8")
ORDER = {"unknown": 0, "healthy": 1, "warning": 2, "problem": 3, "critical": 4}


def _history_path() -> Path:
    for path in HISTORY_PATHS:
        if path.parent.exists():
            return path
    return HISTORY_PATHS[0]


def _load_state() -> dict[str, Any]:
    path = _history_path()
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        return value if isinstance(value, dict) else {}
    except Exception:
        logger.exception("Failed to load network health history")
        return {}


def _save_state(state: dict[str, Any]) -> None:
    path = _history_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _severity(loss: float | None, avg: float | None) -> str:
    if loss is None and avg is None:
        return "unknown"
    loss = float(loss or 0)
    avg = float(avg or 0)
    if loss >= 10 or avg >= 400:
        return "critical"
    if loss >= 5 or avg >= 200:
        return "problem"
    if loss >= 1 or avg >= 100:
        return "warning"
    return "healthy"


def _host_from_value(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    parsed = urlparse(value if "://" in value else f"//{value}")
    return parsed.hostname or value.split("/", 1)[0].split(":", 1)[0]


def _parse_ping(stdout: str, returncode: int) -> dict[str, Any]:
    loss_match = re.search(r"([0-9]+(?:\.[0-9]+)?)%\s*packet loss", stdout, re.I)
    avg_match = re.search(r"(?:rtt|round-trip).*?=\s*([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+)", stdout, re.I)
    if avg_match is None:
        avg_match = re.search(r"=\s*([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+)\s*ms", stdout)
    loss = float(loss_match.group(1)) if loss_match else None
    avg = float(avg_match.group(2)) if avg_match else None
    minimum = float(avg_match.group(1)) if avg_match else None
    maximum = float(avg_match.group(3)) if avg_match else None
    jitter = float(avg_match.group(4)) if avg_match else None
    if loss is None and returncode != 0:
        loss = 100.0
    return {
        "loss_percent": loss,
        "avg_ms": avg,
        "min_ms": minimum,
        "max_ms": maximum,
        "jitter_ms": jitter,
        "severity": _severity(loss, avg),
        "reachable": bool(loss is not None and loss < 100),
    }


async def _ping(host: str) -> dict[str, Any]:
    if not host:
        return _status(False, "No ping target") | {"host": host, "available": False, "severity": "unknown"}
    if not shutil.which("ping"):
        return _status(False, "ICMP ping utility is not installed") | {
            "host": host, "available": False, "severity": "unknown"
        }
    try:
        proc = await asyncio.create_subprocess_exec(
            "ping", "-n", "-c", str(PING_COUNT), "-W", str(PING_TIMEOUT), host,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=PING_COUNT * PING_TIMEOUT + 5)
        result = _parse_ping(stdout.decode(errors="replace"), proc.returncode or 0)
        result.update({"host": host, "available": True, "timestamp": int(time.time())})
        return result
    except Exception as exc:
        return _status(False, str(exc)) | {
            "host": host, "available": True, "severity": "critical", "loss_percent": 100.0
        }


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    usable = [r for r in results if r.get("available") and r.get("loss_percent") is not None]
    if not usable:
        return {"severity": "unknown", "loss_percent": None, "avg_ms": None, "targets": results}
    loss = max(float(r.get("loss_percent") or 0) for r in usable)
    avgs = [float(r["avg_ms"]) for r in usable if r.get("avg_ms") is not None]
    avg = max(avgs) if avgs else None
    severity = max((r.get("severity", "unknown") for r in usable), key=lambda value: ORDER.get(value, 0))
    return {
        "severity": severity,
        "loss_percent": round(loss, 2),
        "avg_ms": round(avg, 2) if avg is not None else None,
        "targets": results,
    }


def _diagnosis(endpoint: dict[str, Any] | None, public: dict[str, Any]) -> str:
    if not endpoint or endpoint.get("severity") == "unknown":
        return "اختلال مسیر/خروجی سرور بر اساس تست‌های عمومی قابل ارزیابی نیست."
    es = endpoint.get("severity")
    ps = public.get("severity")
    if es in {"critical", "problem"} and ps == "healthy":
        return "احتمالاً مشکل مسیر دسترسی به مقصد/نود است؛ خروجی عمومی سرور سالم است."
    if es in {"critical", "problem"} and ps in {"critical", "problem"}:
        return "احتمال مشکل در خروجی، uplink یا مسیر بالادستی سرور وجود دارد."
    if es == "warning":
        return "افزایش latency/loss مشاهده شده و باید روند آن زیر نظر باشد."
    if ps in {"critical", "problem"}:
        return "خروجی عمومی سرور دچار packet loss/latency شده؛ احتمال مشکل uplink یا route بالادستی وجود دارد."
    return "وضعیت شبکه عادی است."


async def collect_network_health(config: Config, server_pool: ServerPoolService, session: AsyncSession) -> dict[str, Any]:
    del server_pool  # Reserved for future active route/transport checks.
    db_servers = await Server.get_all(session)
    servers: list[dict[str, Any]] = []
    for server in db_servers:
        public_results = await asyncio.gather(*(_ping(target) for target in TARGETS))
        public = _aggregate(public_results)
        endpoint_host = _host_from_value(server.host)
        endpoint = _aggregate([await _ping(endpoint_host)])
        try:
            nodes = await _managed_nodes(server, config)
        except Exception:
            logger.exception("Failed to load managed nodes for network health server=%s", server.name)
            nodes = []
        node_inputs = []
        for node in nodes:
            address = _host_from_value(str(node.get("address") or ""))
            if address:
                node_inputs.append((node, address))
        node_results = await asyncio.gather(*(_ping(address) for _, address in node_inputs))
        node_rows = []
        for (node, address), ping_result in zip(node_inputs, node_results):
            result = _aggregate([ping_result])
            node_rows.append({"id": node.get("id"), "name": node.get("name"), "address": address, **result})
        servers.append({
            "id": server.id,
            "name": server.name,
            "host": endpoint_host,
            "endpoint": endpoint,
            "public": public,
            "nodes": node_rows,
            "diagnosis": _diagnosis(endpoint, public),
        })
    return {"timestamp": int(time.time()), "servers": servers}


def _worst(report: dict[str, Any]) -> str:
    severities = []
    for server in report.get("servers", []):
        severities.append(server.get("endpoint", {}).get("severity", "unknown"))
        severities.append(server.get("public", {}).get("severity", "unknown"))
        severities.extend(node.get("severity", "unknown") for node in server.get("nodes", []))
    return max(severities or ["unknown"], key=lambda value: ORDER.get(value, 0))


def update_alert_state(report: dict[str, Any]) -> tuple[str | None, str | None]:
    state = _load_state()
    current = _worst(report)
    previous = state.get("current", "unknown")
    alert_level = state.get("alert_level", "healthy")
    bad_count = int(state.get("bad_count", 0)) if current in {"warning", "problem", "critical"} else 0
    good_count = int(state.get("good_count", 0)) + 1 if current in {"healthy", "unknown"} else 0
    if current in {"warning", "problem", "critical"}:
        good_count = 0

    alert = None
    if current in {"warning", "problem", "critical"} and bad_count >= ALERT_SAMPLES:
        if ORDER.get(current, 0) > ORDER.get(alert_level, 0):
            alert = "degraded"
            alert_level = current
    elif current in {"healthy", "unknown"} and good_count >= RECOVERY_SAMPLES and ORDER.get(alert_level, 0) > ORDER["healthy"]:
        alert = "recovered"
        alert_level = "healthy"

    state.update({
        "current": current,
        "alert_level": alert_level,
        "bad_count": bad_count,
        "good_count": good_count,
        "last_report": report,
    })
    history = state.get("history") if isinstance(state.get("history"), list) else []
    history.append({"timestamp": report.get("timestamp"), "severity": current})
    state["history"] = history[-MAX_HISTORY:]
    _save_state(state)
    return alert, previous


def render_network_alert(report: dict[str, Any], recovered: bool = False) -> str:
    title = "🟢 بازگشت شبکه به وضعیت عادی" if recovered else "🔴 هشدار افت کیفیت شبکه ToonelVPN"
    lines = [title]
    for server in report.get("servers", []):
        endpoint = server.get("endpoint", {})
        public = server.get("public", {})
        lines.append(
            f"\n🌐 <b>{server.get('name','-')}</b>\n"
            f"Endpoint: {endpoint.get('avg_ms','-')} ms | Loss: {endpoint.get('loss_percent','-')}%\n"
            f"Internet probes: {public.get('avg_ms','-')} ms | Loss: {public.get('loss_percent','-')}%\n"
            f"تشخیص: {server.get('diagnosis','-')}"
        )
        for node in server.get("nodes", []):
            lines.append(
                f"🧩 {node.get('name','-')} ({node.get('address','-')}): "
                f"{node.get('avg_ms','-')} ms | Loss {node.get('loss_percent','-')}%"
            )
    return "\n".join(lines)


def render_network_section(report: dict[str, Any]) -> str:
    lines = ["📡 <b>Network Health</b>"]
    for server in report.get("servers", []):
        public = server.get("public", {})
        severity = public.get("severity")
        icon = "🟢" if severity == "healthy" else "🟡" if severity == "warning" else "🔴"
        lines.append(
            f"\n{icon} <b>{server.get('name','-')}</b> | Internet: "
            f"{public.get('avg_ms','-')} ms | Loss {public.get('loss_percent','-')}%"
        )
        for node in server.get("nodes", []):
            severity = node.get("severity")
            nicon = "🟢" if severity == "healthy" else "🟡" if severity == "warning" else "🔴"
            lines.append(
                f"{nicon} {node.get('name','-')}: {node.get('avg_ms','-')} ms | Loss {node.get('loss_percent','-')}%"
            )
    return "\n".join(lines)
