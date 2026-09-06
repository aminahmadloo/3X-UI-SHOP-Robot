from __future__ import annotations

import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from app.mini_app import _validate_init_data


TOKEN = "123456:TEST_TOKEN"


def _signed_init_data(user_id: int = 78797797) -> str:
    values = {
        "auth_date": "1799082000",
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
    monkeypatch.setattr("app.mini_app.time.time", lambda: 1799082010)
    result = _validate_init_data(_signed_init_data(), TOKEN)
    assert result["telegram_user"]["id"] == 78797797


def test_validate_init_data_rejects_tampering(monkeypatch):
    monkeypatch.setattr("app.mini_app.time.time", lambda: 1799082010)
    data = _signed_init_data().replace("Test", "Tampered")
    with pytest.raises(Exception):
        _validate_init_data(data, TOKEN)
