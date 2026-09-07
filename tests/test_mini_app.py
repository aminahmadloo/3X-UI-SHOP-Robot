from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from aiohttp import web

from app.mini_app import MiniAppController, _validate_init_data


TOKEN = "123456:TEST_TOKEN"
NOW = 1_799_082_010
ADMIN_ID = 78797797


def _signed_init_data(user_id: int = ADMIN_ID, auth_date: int = NOW) -> str:
    values = {
        "auth_date": str(auth_date),
        "query_id": "AAE-test",
        "user": json.dumps(
            {"id": user_id, "first_name": "Test", "language_code": "fa"},
            separators=(",", ":"),
        ),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def _controller() -> MiniAppController:
    return MiniAppController(
        db=None,
        bot_token=TOKEN,
        admin_ids=[ADMIN_ID],
        services=SimpleNamespace(),
    )


def test_validate_init_data_returns_telegram_user(monkeypatch):
    monkeypatch.setattr("app.mini_app.time.time", lambda: NOW)
    result = _validate_init_data(_signed_init_data(), TOKEN)
    assert result["telegram_user"]["id"] == ADMIN_ID


def test_validate_init_data_rejects_tampering(monkeypatch):
    monkeypatch.setattr("app.mini_app.time.time", lambda: NOW)
    data = _signed_init_data().replace("Test", "Tampered")
    with pytest.raises(web.HTTPUnauthorized):
        _validate_init_data(data, TOKEN)


def test_validate_init_data_rejects_expired_data(monkeypatch):
    monkeypatch.setattr("app.mini_app.time.time", lambda: NOW + 3601)
    with pytest.raises(web.HTTPUnauthorized):
        _validate_init_data(_signed_init_data(), TOKEN)


def test_validate_init_data_rejects_future_data(monkeypatch):
    monkeypatch.setattr("app.mini_app.time.time", lambda: NOW)
    with pytest.raises(web.HTTPUnauthorized):
        _validate_init_data(_signed_init_data(auth_date=NOW + 61), TOKEN)


def test_validate_init_data_rejects_duplicate_parameters(monkeypatch):
    monkeypatch.setattr("app.mini_app.time.time", lambda: NOW)
    data = _signed_init_data() + "&auth_date=" + str(NOW)
    with pytest.raises(web.HTTPUnauthorized):
        _validate_init_data(data, TOKEN)


@pytest.mark.asyncio
async def test_authenticate_rejects_non_admin(monkeypatch):
    monkeypatch.setattr("app.mini_app.time.time", lambda: NOW)
    controller = _controller()
    request = SimpleNamespace(
        headers={"X-Telegram-Init-Data": _signed_init_data(user_id=123456789)}
    )
    with pytest.raises(web.HTTPForbidden):
        await controller._authenticate(request)


def test_serialize_live_subscription_marks_past_expiry_as_expired(monkeypatch):
    monkeypatch.setattr("app.mini_app.time.time", lambda: NOW)
    subscription = SimpleNamespace(
        id=1,
        config_name="Test Service",
        status="active",
        volume_gb=20,
        duration_days=30,
        devices=2,
        start_date=None,
        expire_date=datetime.fromtimestamp(NOW - 1, tz=timezone.utc),
        created_at=None,
        updated_at=None,
        server=None,
    )
    live = SimpleNamespace(
        config_name="Test Service",
        traffic_total=20 * 1024**3,
        traffic_used=2 * 1024**3,
        traffic_remaining=18 * 1024**3,
        traffic_up=1 * 1024**3,
        traffic_down=1 * 1024**3,
        max_devices=2,
        inbound_id=1,
        client_id="client-1",
        sub_id="sub-1",
        flow="xtls-rprx-vision",
    )
    result = MiniAppController._serialize_live_subscription(subscription, live)
    assert result["status"] == "expired"
    assert result["traffic_used"] == 2 * 1024**3
    assert result["traffic_remaining"] == 18 * 1024**3
    assert result["client_id"] == "client-1"


def test_serialize_live_subscription_unlimited_devices(monkeypatch):
    monkeypatch.setattr("app.mini_app.time.time", lambda: NOW)
    subscription = SimpleNamespace(
        id=2,
        config_name="Unlimited",
        status="active",
        volume_gb=0,
        duration_days=0,
        devices=0,
        start_date=None,
        expire_date=None,
        created_at=None,
        updated_at=None,
        server=None,
    )
    live = SimpleNamespace(
        config_name="Unlimited",
        traffic_total=-1,
        traffic_used=123,
        traffic_remaining=-1,
        traffic_up=100,
        traffic_down=23,
        max_devices="نامحدود",
        inbound_id=2,
        client_id="client-2",
        sub_id="sub-2",
        flow=None,
    )
    result = MiniAppController._serialize_live_subscription(subscription, live)
    assert result["status"] == "active"
    assert result["devices"] == -1
    assert result["traffic_total"] == -1
    assert result["traffic_remaining"] == -1
