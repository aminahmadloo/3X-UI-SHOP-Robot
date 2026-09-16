from __future__ import annotations

from app.bot.routers.my_services import auto_connect, auto_connect_install


SUB_URL = "https://sub.elfuu.ir:2096/sub/test-subscription"


def test_android_client_deep_links_are_generated() -> None:
    assert auto_connect._client_deep_link("v2rayng", SUB_URL, "Amin") == (
        "v2rayng://install-sub?url="
        "https%3A%2F%2Fsub.elfuu.ir%3A2096%2Fsub%2Ftest-subscription"
    )
    assert auto_connect._client_deep_link("v2box", SUB_URL, "Amin").startswith(
        "v2box://install-sub?url="
    )
    assert auto_connect._client_deep_link("hiddify", SUB_URL, "Amin").startswith(
        "hiddify://import/https://sub.elfuu.ir:2096/sub/test-subscription#"
    )
    assert auto_connect._client_deep_link("singbox", SUB_URL, "Amin").startswith(
        "sing-box://import-remote-profile?url="
    )
    assert auto_connect._client_deep_link("v2raytun", SUB_URL, "Amin") == (
        "v2raytun://import/https://sub.elfuu.ir:2096/sub/test-subscription"
    )
    assert auto_connect._client_deep_link("happ", SUB_URL, "Amin") == (
        "happ://add/https://sub.elfuu.ir:2096/sub/test-subscription"
    )
    assert auto_connect._client_deep_link("incy", SUB_URL, "Amin") == (
        "incy://add/https://sub.elfuu.ir:2096/sub/test-subscription"
    )
    assert auto_connect._client_deep_link("shadowrocket", SUB_URL, "Amin") == (
        "shadowrocket://add/https://sub.elfuu.ir:2096/sub/test-subscription"
    )
    assert auto_connect._client_deep_link("streisand", SUB_URL, "Amin") == (
        "streisand://import/https://sub.elfuu.ir:2096/sub/test-subscription"
    )


def test_nekobox_is_registered_by_install_hook() -> None:
    assert "nekobox" in auto_connect.CLIENTS["android"]
    link = auto_connect._client_deep_link("nekobox", SUB_URL, "Amin")
    assert link is not None
    assert link.startswith("clash://install-config?url=")


def test_payment_success_keyboard_has_required_actions() -> None:
    markup = auto_connect.payment_success_keyboard_for_key(SUB_URL)
    rows = markup.inline_keyboard
    assert len(rows) == 5
    assert rows[0][0].text == "📱 اتصال خودکار"
    assert rows[1][0].text == "📋 کپی لینک"
    assert rows[1][0].copy_text is not None
    assert rows[1][0].copy_text.text == SUB_URL
    assert rows[2][0].text == "📷 QR Code"
    assert rows[3][0].text == "🔄 بروزرسانی"
    assert rows[4][0].text == "🔙 بازگشت به منوی اصلی"
