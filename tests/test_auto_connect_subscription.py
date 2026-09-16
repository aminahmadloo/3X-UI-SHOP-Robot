from __future__ import annotations

from aiohttp import web

from app.bot.routers import my_services
from app.bot.routers.my_services import auto_connect

SUB_URL = "https://sub.elfuu.ir:2096/sub/test-subscription"
SECRET = "isolated-test-secret"


# PR93 isolated test suite: no production services or credentials are used.
def test_all_supported_client_deep_links_are_generated() -> None:
    expected_prefixes = {
        "v2rayng": "v2rayng://install-sub?url=",
        "nekobox": "clash://install-config?url=",
        "v2box": "v2box://install-sub?url=",
        "hiddify": "hiddify://import/",
        "singbox": "sing-box://import-remote-profile?url=",
        "v2raytun": "v2raytun://import/",
        "happ": "happ://add/",
        "incy": "incy://add/",
        "shadowrocket": "shadowrocket://add/",
        "streisand": "streisand://import/",
    }

    for client, prefix in expected_prefixes.items():
        assert auto_connect._client_deep_link(client, SUB_URL, "Amin").startswith(prefix)


def test_payment_success_keyboard_uses_exact_client_identity_and_https_gateway() -> None:
    markup = auto_connect.payment_success_keyboard_for_key(SUB_URL, SECRET)
    rows = markup.inline_keyboard
    assert len(rows) == 5
    assert rows[0][0].text == "📱 اتصال خودکار"
    assert rows[0][0].callback_data == "my_services:auto:test-subscription"
    assert rows[1][0].text == "📋 کپی لینک"
    assert rows[1][0].copy_text is not None
    assert rows[1][0].copy_text.text == SUB_URL
    assert rows[2][0].text == "📷 QR Code"
    assert rows[2][0].callback_data == "my_services:aq:test-subscription"
    assert rows[3][0].text == "🔄 بروزرسانی"
    assert rows[3][0].callback_data == "my_services:af:test-subscription"
    assert rows[4][0].text == "🔙 بازگشت به منوی اصلی"


def test_gateway_token_round_trip_is_signed() -> None:
    token = auto_connect._gateway_token("test-subscription", "v2rayng", SECRET)
    assert auto_connect._parse_gateway_token(token, SECRET) == ("test-subscription", "v2rayng")
    assert auto_connect._parse_gateway_token(token, "wrong-secret") is None
    assert auto_connect._parse_gateway_token(token[:-1] + ("0" if token[-1] != "0" else "1"), SECRET) is None


def test_gateway_registers_https_route() -> None:
    app = web.Application()
    auto_connect.register_gateway(app, session_factory=None, services=None, secret=SECRET)  # type: ignore[arg-type]
    assert any(route.resource.canonical == "/connect/{token}" for route in app.router.routes())


def test_auto_connect_routers_are_attached_without_runtime_patches() -> None:
    names = {router.name for router in my_services.client_control_handler.router.sub_routers}
    assert "my_services_auto_connect_details" in names
    assert "my_services_auto_connect" in names
    assert not hasattr(my_services.client_control_handler.router, "_auto_connect_keyboard_middleware")
