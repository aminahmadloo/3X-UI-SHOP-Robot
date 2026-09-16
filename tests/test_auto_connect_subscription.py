from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

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


def _callback(data: str) -> SimpleNamespace:
    message = SimpleNamespace(edit_text=AsyncMock(), answer_photo=AsyncMock())
    return SimpleNamespace(data=data, answer=AsyncMock(), message=message)


def _service_context() -> tuple[SimpleNamespace, SimpleNamespace, SimpleNamespace]:
    subscription = SimpleNamespace(id=42, client_id="test-subscription", config_name="Amin", status="active")
    session_result = SimpleNamespace(
        scalar_one_or_none=lambda: subscription,
        scalars=lambda: SimpleNamespace(first=lambda: subscription),
    )
    session = SimpleNamespace(execute=AsyncMock(return_value=session_result))
    services = SimpleNamespace(vpn=SimpleNamespace(get_key=AsyncMock(return_value=SUB_URL)))
    user = SimpleNamespace(id=7, tg_id=123)
    return user, session, services


def test_auto_connect_entry_callback_executes() -> None:
    async def run() -> None:
        user, session, services = _service_context()
        callback = _callback("my_services:auto:42")
        await auto_connect.callback_auto_connect_entry(callback, user, session, services)
        callback.answer.assert_awaited_once()
        callback.message.edit_text.assert_awaited_once()
        markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
        assert markup.inline_keyboard[0][0].callback_data == "my_services:auto:android:42"
        assert markup.inline_keyboard[0][1].callback_data == "my_services:auto:ios:42"

    asyncio.run(run())


def test_auto_connect_platform_callback_executes() -> None:
    async def run() -> None:
        user, session, services = _service_context()
        callback = _callback("my_services:auto:android:42")
        config = SimpleNamespace(bot=SimpleNamespace(TOKEN=SECRET))
        await auto_connect.callback_auto_connect_platform(callback, user, session, services, config)
        callback.answer.assert_awaited_once()
        callback.message.edit_text.assert_awaited_once()
        markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
        urls = [row[0].url for row in markup.inline_keyboard if row and row[0].url]
        assert urls
        assert all(url.startswith("https://sub.elfuu.ir/connect/") for url in urls)

    asyncio.run(run())


def test_purchase_success_refresh_callback_executes() -> None:
    async def run() -> None:
        user, session, services = _service_context()
        callback = _callback("my_services:af:test-subscription")
        config = SimpleNamespace(bot=SimpleNamespace(TOKEN=SECRET))
        original_gettext = auto_connect._
        auto_connect._ = lambda text: text
        try:
            await auto_connect.callback_success_refresh(callback, user, session, services, config)
        finally:
            auto_connect._ = original_gettext
        callback.answer.assert_awaited_once()
        callback.message.edit_text.assert_awaited_once()
        markup = callback.message.edit_text.await_args.kwargs["reply_markup"]
        assert markup.inline_keyboard[0][0].callback_data == "my_services:auto:test-subscription"

    asyncio.run(run())
