from types import SimpleNamespace

import pytest

from app.bot.routers.admin_tools import ai_content_handler  # noqa: F401
from app.bot.services.ai_content import (
    DEFAULT_PRODUCTION_CONTROLS,
    DEFAULT_SMART_RULES,
    SMART_CATEGORIES,
    AIContentError,
    AIContentService,
)


def _settings(**overrides):
    values = {
        "production_controls": "{}",
        "smart_rules": "{}",
        "smart_risk_level": "balanced",
        "mode": "smart",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_default_production_controls_enable_all_categories():
    settings = _settings()
    controls = AIContentService.production_controls(settings)
    assert controls == DEFAULT_PRODUCTION_CONTROLS
    assert AIContentService.enabled_categories(settings) == set(SMART_CATEGORIES)


def test_production_controls_preserve_missing_categories_as_enabled():
    settings = _settings(production_controls='{"news": false}')
    controls = AIContentService.production_controls(settings)
    assert controls["news"] is False
    assert controls["education"] is True
    assert "news" not in AIContentService.enabled_categories(settings)


def test_smart_rules_remain_independent_from_production_controls():
    settings = _settings(
        production_controls='{"education": false}',
        smart_rules='{"education": "auto"}',
    )
    assert AIContentService.smart_rules(settings)["education"] == "auto"
    assert "education" not in AIContentService.enabled_categories(settings)


@pytest.mark.asyncio
async def test_create_content_rejects_disabled_selected_category():
    settings = _settings(production_controls='{"news": false}')
    service = AIContentService(api_key="test")
    with pytest.raises(AIContentError, match="غیرفعال"):
        await service.create_content(None, 1, settings, category="news")


@pytest.mark.asyncio
async def test_create_content_rejects_unknown_selected_category():
    settings = _settings()
    service = AIContentService(api_key="test")
    with pytest.raises(AIContentError, match="معتبر"):
        await service.create_content(None, 1, settings, category="unknown")


def test_smart_rules_defaults_are_unchanged():
    settings = _settings()
    assert AIContentService.smart_rules(settings) == DEFAULT_SMART_RULES
