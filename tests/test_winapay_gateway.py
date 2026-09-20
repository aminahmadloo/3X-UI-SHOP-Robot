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
