from decimal import Decimal

import pytest

from app.bot.payment_gateways.winapay_gateway import WinapayGateway


def test_to_toman_accepts_integer_values() -> None:
    assert WinapayGateway._to_toman(1000) == 1000
    assert WinapayGateway._to_toman(Decimal("1250")) == 1250


@pytest.mark.parametrize("value", [0, -1, 99.5])
def test_to_toman_rejects_invalid_values(value: float) -> None:
    with pytest.raises(ValueError):
        WinapayGateway._to_toman(value)


def test_verify_success_accepts_status_100_and_matching_amount() -> None:
    assert WinapayGateway._verify_success({"Status": 100, "Amount": 760000, "RefID": "123"}, 760000)


def test_verify_success_accepts_already_verified_status_101() -> None:
    assert WinapayGateway._verify_success({"Status": 101, "Amount": "760000"}, 760000)


def test_verify_success_rejects_failed_status() -> None:
    assert not WinapayGateway._verify_success({"Status": -16}, 760000)


def test_verify_success_rejects_amount_mismatch() -> None:
    with pytest.raises(RuntimeError, match="amount mismatch"):
        WinapayGateway._verify_success({"Status": 100, "Amount": 760001}, 760000)


def test_subscription_data_deserializes_to_mapping_for_online_ui() -> None:
    from app.bot.models import SubscriptionData
    from app.bot.utils.navigation import NavSubscription

    data = SubscriptionData(
        state=NavSubscription.CONFIG_NAME,
        user_id=78797797,
        duration=30,
        price=760000,
        original_price=800000,
        discount_percent=5,
        discount_level_title="سطح پایه",
        plan_id=12,
        volume_gb=20,
        config_name="20GB-30D-tg78797797-1",
    )

    restored = SubscriptionData.deserialize(data.serialize())

    assert restored.user_id == data.user_id
    assert restored.price == data.price
    assert restored.original_price == data.original_price
    assert restored.plan_id == data.plan_id
    assert restored.config_name == data.config_name


def test_online_gateway_button_is_hidden_without_configured_gateway(monkeypatch) -> None:
    from types import SimpleNamespace
    from app.bot.routers.payment_method_visibility import _online_keys

    monkeypatch.delenv("SHOP_PAYMENT_ZARINPAL_ENABLED", raising=False)
    monkeypatch.delenv("WINAPAY_MERCHANT_ID", raising=False)

    gateways = [
        SimpleNamespace(callback="pay_zarinpal"),
        SimpleNamespace(callback="pay_winapay"),
    ]

    assert _online_keys(gateways) == []


def test_online_gateway_button_reappears_when_winapay_is_configured(monkeypatch) -> None:
    from types import SimpleNamespace
    from app.bot.routers.payment_method_visibility import _online_keys

    monkeypatch.setenv("WINAPAY_MERCHANT_ID", "test-merchant")
    monkeypatch.delenv("SHOP_PAYMENT_ZARINPAL_ENABLED", raising=False)

    gateways = [
        SimpleNamespace(callback="pay_zarinpal"),
        SimpleNamespace(callback="pay_winapay"),
    ]

    assert _online_keys(gateways) == ["pay_winapay"]
