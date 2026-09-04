from app.bot.services.channel_templates import TEMPLATE_DEFINITIONS, render_template


def test_all_required_templates_exist():
    assert {"special_offer", "server_notice", "maintenance", "referral", "renewal", "custom"} <= TEMPLATE_DEFINITIONS.keys()


def test_renderer_only_replaces_supported_variables():
    assert render_template("{service_name} {unknown} {price}", {"service_name": "Gold", "price": "10"}) == "Gold {unknown} 10"
