from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from urllib.request import Request, urlopen

from app.bot.services.system_health import _api_url
from app.config import Config

logger = logging.getLogger(__name__)


async def _http_json(url: str, token: str | None = None, method: str = "GET") -> Any:
    def request() -> Any:
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = Request(url, headers=headers, method=method)
        with urlopen(req, timeout=8.0) as response:
            return json.loads(response.read().decode("utf-8"))

    return await asyncio.to_thread(request)


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "obj" in payload:
        return payload["obj"]
    return payload


async def get_server_nodes(server: Any, config: Config) -> list[dict[str, Any]]:
    """Read the managed nodes directly from the selected master 3X-UI panel."""
    try:
        payload = _unwrap(await _http_json(_api_url(server, "panel/api/nodes/list"), config.xui.TOKEN))
    except Exception as exc:
        logger.warning("Failed to read nodes for %s: %s", server.name, exc)
        return []

    if not isinstance(payload, list):
        return []

    nodes: list[dict[str, Any]] = []
    for node in payload:
        if not isinstance(node, dict):
            continue
        nodes.append(
            {
                "id": node.get("id"),
                "name": node.get("name") or node.get("address") or "Node",
                "address": node.get("address") or "-",
                "port": node.get("port") or 2053,
                "base_path": node.get("basePath") or node.get("base_path") or "/",
                "status": node.get("status") or ("online" if node.get("enable") else "disabled"),
                "enable": bool(node.get("enable", True)),
                "latency_ms": node.get("latencyMs"),
                "cpu_percent": node.get("cpuPct"),
                "memory_percent": node.get("memPct"),
                "xray_version": node.get("xrayVersion") or "-",
                "panel_version": node.get("panelVersion") or "-",
                "xray_state": node.get("xrayState") or "-",
                "inbound_count": node.get("inboundCount", 0),
                "client_count": node.get("clientCount", 0),
                "online_count": node.get("onlineCount", 0),
                "active_count": node.get("activeCount", 0),
                "disabled_count": node.get("disabledCount", 0),
                "depleted_count": node.get("depletedCount", 0),
                "guid": node.get("guid") or "",
            }
        )
    return nodes


async def get_server_inbound_groups(server: Any, config: Config) -> list[dict[str, Any]]:
    """Read master-panel inbounds and preserve 3X-UI node attribution."""
    nodes = await get_server_nodes(server, config)
    node_by_id = {int(node["id"]): node for node in nodes if node.get("id") is not None}

    try:
        payload = _unwrap(await _http_json(_api_url(server, "panel/api/inbounds/list"), config.xui.TOKEN))
    except Exception as exc:
        logger.warning("Failed to read inbounds for %s: %s", server.name, exc)
        return []

    if not isinstance(payload, list):
        return []

    groups: dict[str, dict[str, Any]] = {}
    for inbound in payload:
        if not isinstance(inbound, dict):
            continue

        node_id = inbound.get("nodeId")
        node = node_by_id.get(int(node_id)) if node_id is not None else None
        node_address = inbound.get("nodeAddress") or (node.get("address") if node else None)

        if node_id is None:
            key = "local"
            title = server.name
            subtitle = "سرور اصلی"
            flag = "🖥"
            address = server.host
        else:
            key = f"node:{node_id}"
            title = node["name"] if node else (node_address or f"Node {node_id}")
            subtitle = f"نود زیرمجموعه {server.name}"
            flag = "🧩"
            address = node_address or "-"

        group = groups.setdefault(
            key,
            {
                "key": key,
                "title": title,
                "subtitle": subtitle,
                "flag": flag,
                "address": address,
                "node_id": node_id,
                "inbounds": [],
            },
        )
        settings = inbound.get("settings") or {}
        if isinstance(settings, str):
            try:
                settings = json.loads(settings)
            except Exception:
                settings = {}
        clients = settings.get("clients") if isinstance(settings, dict) else []
        group["inbounds"].append(
            {
                "id": inbound.get("id"),
                "remark": inbound.get("remark") or inbound.get("tag") or "-",
                "protocol": inbound.get("protocol") or "-",
                "port": inbound.get("port") or "-",
                "enable": bool(inbound.get("enable", True)),
                "node_id": node_id,
                "node_address": node_address or address,
                "client_count": len(clients) if isinstance(clients, list) else 0,
            }
        )

    return list(groups.values())


def group_counts(group: dict[str, Any]) -> tuple[int, int]:
    total = len(group.get("inbounds") or [])
    enabled = sum(1 for inbound in group.get("inbounds") or [] if inbound.get("enable"))
    return enabled, total
