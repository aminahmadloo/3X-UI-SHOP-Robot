from decimal import Decimal

import pytest

from app.bot.payment_gateways.blupal_gateway import BluPalGateway


def test_blupal_toman_to_rial_conversion() -> None:
    assert BluPalGateway._to_rial(100_000) == 1_000_000
    assert BluPalGateway._to_rial(Decimal("1250.5")) == 12_505


def test_blupal_rejects_non_positive_amount() -> None:
    with pytest.raises(ValueError):
        BluPalGateway._to_rial(0)

    with pytest.raises(ValueError):
        BluPalGateway._to_rial(-10)
