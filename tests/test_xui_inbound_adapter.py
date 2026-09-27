from py3xui import Inbound

from app.bot.services.xui_inbound_adapter import (
    inbound_from_payload,
    normalize_inbound_payload,
)


def _vless_inbound(**overrides):
    payload = {
        "id": 1,
        "remark": "test",
        "enable": True,
        "port": 12345,
        "protocol": "vless",
        "settings": {
            "clients": [],
            "decryption": "none",
            "fallbacks": [],
        },
        "streamSettings": {
            "network": "tcp",
            "security": "none",
        },
        "sniffing": {
            "enabled": False,
            "destOverride": [],
        },
    }
    payload.update(overrides)
    return payload


def test_normalizes_null_optional_xui_fields():
    raw = _vless_inbound(streamSettings=None, sniffing=None)

    normalized = normalize_inbound_payload(raw)

    assert normalized["streamSettings"] == {
        "network": "tcp",
        "security": "",
    }
    assert normalized["sniffing"]["enabled"] is False
    assert raw["streamSettings"] is None
    assert raw["sniffing"] is None


def test_normalizes_missing_stream_and_sniffing():
    raw = _vless_inbound()
    raw.pop("streamSettings")
    raw.pop("sniffing")

    normalized = normalize_inbound_payload(raw)

    assert normalized["streamSettings"]["network"] == "tcp"
    assert normalized["streamSettings"]["security"] == ""
    assert normalized["sniffing"]["enabled"] is False


def test_normalizes_partial_stream_and_sniffing():
    raw = _vless_inbound(
        streamSettings={"tcpSettings": {"acceptProxyProtocol": False}},
        sniffing={},
    )

    normalized = normalize_inbound_payload(raw)

    assert normalized["streamSettings"]["network"] == "tcp"
    assert normalized["streamSettings"]["security"] == ""
    assert normalized["streamSettings"]["tcpSettings"]["acceptProxyProtocol"] is False
    assert normalized["sniffing"]["enabled"] is False


def test_normalized_payload_is_accepted_by_py3xui():
    raw = _vless_inbound(streamSettings=None, sniffing=None)

    inbound = inbound_from_payload(raw)

    assert isinstance(inbound, Inbound)
    assert inbound.id == 1
    assert inbound.port == 12345
    assert inbound.settings.clients == []
    assert inbound.stream_settings.network == "tcp"
    assert inbound.stream_settings.security == ""
    assert inbound.sniffing.enabled is False
