from decimal import Decimal
import unittest

from app.bot.payment_gateways.blupal_gateway import BluPalGateway


class BluPalGatewayTests(unittest.TestCase):
    def test_toman_to_rial_conversion(self) -> None:
        self.assertEqual(BluPalGateway._to_rial(100_000), 1_000_000)
        self.assertEqual(BluPalGateway._to_rial(Decimal("1250.5")), 12_505)

    def test_rejects_non_positive_amount(self) -> None:
        with self.assertRaises(ValueError):
            BluPalGateway._to_rial(0)
        with self.assertRaises(ValueError):
            BluPalGateway._to_rial(-10)


if __name__ == "__main__":
    unittest.main()
