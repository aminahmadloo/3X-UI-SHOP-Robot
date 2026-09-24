from decimal import Decimal
import unittest

from app.bot.payment_gateways.blupal_gateway import BluPalGateway


class BluPalGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gateway = object.__new__(BluPalGateway)

    def test_toman_to_rial_conversion(self) -> None:
        self.assertEqual(BluPalGateway._to_rial(100_000), 1_000_000)
        self.assertEqual(BluPalGateway._to_rial(Decimal("1250.5")), 12_505)


    def test_validates_created_invoice_response(self) -> None:
        result = self.gateway._validate_created_invoice_response(
            {
                "invoice_id": "123456",
                "payment_link": "https://blupal.top/payment/123456",
                "amount": 1_000_000,
                "final_amount": 1_000_042,
            },
            1_000_000,
        )
        self.assertEqual(
            result,
            ("123456", "https://blupal.top/payment/123456", 1_000_042),
        )

    def test_rejects_created_invoice_amount_mismatch(self) -> None:
        with self.assertRaises(RuntimeError):
            self.gateway._validate_created_invoice_response(
                {
                    "invoice_id": "123456",
                    "payment_link": "https://blupal.top/payment/123456",
                    "amount": 999_999,
                    "final_amount": 1_000_042,
                },
                1_000_000,
            )

    def test_rejects_created_invoice_final_amount_outside_range(self) -> None:
        base = {
            "invoice_id": "123456",
            "payment_link": "https://blupal.top/payment/123456",
            "amount": 1_000_000,
        }

        with self.assertRaises(RuntimeError):
            BluPalGateway._validate_created_invoice_response(
                {**base, "final_amount": 999_999},
                1_000_000,
            )

        with self.assertRaises(RuntimeError):
            BluPalGateway._validate_created_invoice_response(
                {**base, "final_amount": 1_001_000},
                1_000_000,
            )

    def test_rejects_invalid_created_invoice_id(self) -> None:
        with self.assertRaises(RuntimeError):
            BluPalGateway._validate_created_invoice_response(
                {
                    "invoice_id": "abc",
                    "payment_link": "https://blupal.top/payment/abc",
                    "amount": 1_000_000,
                    "final_amount": 1_000_001,
                },
                1_000_000,
            )

    def test_rejects_non_positive_amount(self) -> None:
        with self.assertRaises(ValueError):
            BluPalGateway._to_rial(0)
        with self.assertRaises(ValueError):
            BluPalGateway._to_rial(-10)


if __name__ == "__main__":
    unittest.main()
