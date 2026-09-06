from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
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
    controller = MiniAppController(db=None, bot_token=TOKEN, admin_ids=[ADMIN_ID])
    request = SimpleNamespace(
        headers={"X-Telegram-Init-Data": _signed_init_data(user_id=123456789)}
    )
    with pytest.raises(web.HTTPForbidden):
        await controller._authenticate(request)


def test_serialize_subscription_marks_past_expiry_as_expired(monkeypatch):
    monkeypatch.setattr("app.mini_app.time.time", lambda: NOW)
    subscription = SimpleNamespace(
        id=1,
        config_name="Test Service",
        status="active",
        volume_gb=20,
        duration_days=30,
        devices=2,
        start_date=None,
        expire_date=datetime.fromtimestamp(NOW - 1),
        server=None,
    )
    result = MiniAppController._serialize_subscription(subscription, now=NOW)
    assert result["status"] == "expired"
