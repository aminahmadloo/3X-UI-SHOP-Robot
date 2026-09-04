import pytest

from app.bot.services.channel_templates import (
    TEMPLATE_DEFINITIONS,
    create_draft_from_template,
    missing_required_variables,
    render_template,
    variable_assignment_text,
)
from app.db.models import ChannelContentTemplate


def _template() -> ChannelContentTemplate:
    definition = TEMPLATE_DEFINITIONS["special_offer"]
    template = ChannelContentTemplate(slug="offer", title=definition["title"], body=definition["body"], purpose=definition["purpose"])
    template.variable_definitions = definition["variables"]
    return template


def test_all_required_templates_exist():
    assert {"special_offer", "server_notice", "maintenance", "referral", "renewal", "custom"} <= TEMPLATE_DEFINITIONS.keys()


def test_template_variable_rendering_replaces_documented_variables_only():
    template = _template()
    rendered = render_template("{service_name} {unknown} {old_price}", {"service_name": "Gold"}, template.variable_definitions)
    assert rendered == "Gold {unknown}"


def test_missing_required_variables_are_reported():
    missing = missing_required_variables(_template().variable_definitions, {"service_name": "Gold"})
    assert {item["key"] for item in missing} == {"volume", "duration", "price", "discount", "buy_link"}


def test_draft_creation_from_template_renders_documented_values():
    template = _template()
    content = create_draft_from_template(template, 42, {"service_name": "Gold", "volume": "100GB", "duration": "30 روز", "price": "100 تومان", "discount": "20٪", "buy_link": "https://buy"})
    assert content.channel_id == 42
    assert content.status == "draft"
    assert "Gold" in content.body and "https://buy" in content.body


def test_draft_creation_rejects_missing_required_variables():
    with pytest.raises(ValueError, match="متغیرهای ضروری"):
        create_draft_from_template(_template(), 42, {"service_name": "Gold"})


def test_template_variable_listing_is_template_specific():
    assert variable_assignment_text(TEMPLATE_DEFINITIONS["server_notice"]["variables"]) == "service_name=\nsupport_link="
    assert "volume=" not in variable_assignment_text(TEMPLATE_DEFINITIONS["server_notice"]["variables"])
