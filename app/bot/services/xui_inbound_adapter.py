"""Compatibility adapter for raw 3X-UI inbound responses.

py3xui validates inbound payloads with a Pydantic model whose required
streamSettings/sniffing fields are stricter than the 3X-UI wire format.
3X-UI treats streamSettings and sniffing as optional/defaulted fields, so
the adapter normalizes those compatibility cases before model validation.
"""

from __future__ import annotations

from typing import Any

from py3xui import Inbound
from py3xui.api.api_base import ApiFields


_DEFAULT_SNIFFING = {
    "enabled": False,
    "destOverride": [],
    "metadataOnly": False,
    "routeOnly": False,
}


def normalize_inbound_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize one raw 3X-UI inbound payload without mutating the source."""

    normalized = dict(data)

    stream = normalized.get("streamSettings")
    if stream is None:
        # 3X-UI's current wire schema treats streamSettings as optional.
        # py3xui requires it, so represent the Xray default transport.
        normalized["streamSettings"] = {
            "network": "tcp",
            "security": "",
        }
    elif isinstance(stream, dict):
        stream = dict(stream)

        # Plain TCP and a few legacy records may omit security/network.
        # Preserve all other transport-specific settings unchanged.
        if "security" not in stream or stream.get("security") is None:
            stream["security"] = ""
        if "network" not in stream or stream.get("network") is None:
            stream["network"] = "tcp"

        normalized["streamSettings"] = stream

    sniffing = normalized.get("sniffing")
    if sniffing is None:
        # 3X-UI defaults sniffing to disabled when it is absent/null.
        normalized["sniffing"] = dict(_DEFAULT_SNIFFING)
    elif isinstance(sniffing, dict):
        sniffing = dict(sniffing)
        if "enabled" not in sniffing or sniffing.get("enabled") is None:
            sniffing["enabled"] = False
        normalized["sniffing"] = sniffing

    return normalized


def inbound_from_payload(data: dict[str, Any]) -> Inbound:
    """Convert one raw 3X-UI inbound payload into an Inbound object."""

    normalized = normalize_inbound_payload(data)
    return Inbound.model_validate(normalized)


def inbounds_from_payload(data: Any) -> list[Inbound]:
    """Convert the obj field from a 3X-UI inbounds/list response."""

    if not isinstance(data, list):
        return []

    result: list[Inbound] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        result.append(inbound_from_payload(item))

    return result


async def get_inbounds(api: Any) -> list[Inbound]:
    """Fetch raw inbounds through py3xui's authenticated HTTP layer.

    We intentionally do not call api.inbound.get_list(), because that method
    validates the response before compatibility normalization can run.
    """

    endpoint = "panel/api/inbounds/list"
    url = api.inbound._url(endpoint)
    headers = {"Accept": "application/json"}

    response = await api.inbound._get(url, headers)
    payload = response.json()
    obj = payload.get(ApiFields.OBJ)

    return inbounds_from_payload(obj)
