"""Compatibility adapter for raw 3X-UI inbound responses.

py3xui 0.7.x validates inbound payloads with a Pydantic model.
Some 3X-UI versions return streamSettings without the `security`
field for plain TCP inbounds.

This adapter deliberately bypasses py3xui's get_list() validation,
reads the raw API response, applies only the minimum compatibility
normalization, and then converts the payload into py3xui Inbound
objects.
"""

from __future__ import annotations

from typing import Any

from py3xui import Inbound
from py3xui.api.api_base import ApiFields


def normalize_inbound_payload(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize one raw 3X-UI inbound payload."""

    normalized = dict(data)

    stream = normalized.get("streamSettings")

    if isinstance(stream, dict):
        stream = dict(stream)

        # Some 3X-UI versions omit security for plain TCP.
        # py3xui 0.7.x requires this field.
        if "security" not in stream or stream.get("security") is None:
            stream["security"] = ""

        normalized["streamSettings"] = stream

    return normalized


def inbound_from_payload(data: dict[str, Any]) -> Inbound:
    """Convert one raw 3X-UI inbound payload into an Inbound object."""

    normalized = normalize_inbound_payload(data)
    return Inbound.model_validate(normalized)


def inbounds_from_payload(data: Any) -> list[Inbound]:
    """Convert the `obj` field from a 3X-UI inbounds/list response."""

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

    We intentionally do NOT call api.inbound.get_list(), because that
    method validates the response before our compatibility normalization
    can run.
    """

    endpoint = "panel/api/inbounds/list"

    # AsyncInboundApi inherits _url() and _get() from AsyncBaseApi.
    url = api.inbound._url(endpoint)
    headers = {"Accept": "application/json"}

    response = await api.inbound._get(url, headers)

    payload = response.json()

    obj = payload.get(ApiFields.OBJ)

    return inbounds_from_payload(obj)
