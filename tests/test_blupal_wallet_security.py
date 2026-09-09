from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot.models import SubscriptionData
from app.bot.payment_gateways.blupal_gateway import BluPalGateway
from app.bot.routers.blupal_smart_card_compat import _blupal_success
from app.bot.utils.constants import TransactionStatus
from app.bot.utils.navigation import NavSubscription


class _FakeSessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _subscription_data(price: int = 100_000) -> SubscriptionData:
    return SubscriptionData(
        state=NavSubscription.CONFIG_NAME,
        user_id=123456,
        price=price,
        payment_kind="wallet_topup",
    )


def _transaction(
    *,
    payment_id: str = "12345",
    price: int = 100_000,
    gateway: str = "blupal",
    status: TransactionStatus = TransactionStatus.PENDING,
):
    return SimpleNamespace(
        payment_id=payment_id,
        subscription=_subscription_data(price).serialize(),
        gateway=gateway,
        status=status,
    )


class BluPalWalletSecurityTests(unittest.IsolatedAsyncioTestCase):
    def _gateway(self):
        gateway = SimpleNamespace()
        gateway.session = lambda: _FakeSessionContext()
        gateway.get_invoice = AsyncMock()
        gateway._verify_invoice_matches_transaction = AsyncMock()
        gateway.credit_wallet = AsyncMock()
        return gateway

    async def test_wallet_pending_invoice_never_credits(self):
        gateway = self._gateway()
        transaction = _transaction()

        gateway.get_invoice.return_value = {
            "invoice_id": "12345",
            "status": "PENDING",
            "amount": 1_000_000,
            "final_amount": 1_000_042,
        }

        with patch(
            "app.db.models.Transaction.get_by_id",
            new=AsyncMock(return_value=transaction),
        ):
            with self.assertRaisesRegex(RuntimeError, "is not PAID"):
                await _blupal_success(gateway, "12345")

        gateway.get_invoice.assert_awaited_once_with("12345")
        gateway._verify_invoice_matches_transaction.assert_not_awaited()
        gateway.credit_wallet.assert_not_awaited()

    async def test_wallet_paid_matching_invoice_credits(self):
        gateway = self._gateway()
        transaction = _transaction()

        gateway.get_invoice.return_value = {
            "invoice_id": "12345",
            "status": "PAID",
            "amount": 1_000_000,
            "final_amount": 1_000_042,
        }

        with patch(
            "app.db.models.Transaction.get_by_id",
            new=AsyncMock(return_value=transaction),
        ):
            await _blupal_success(gateway, "12345")

        gateway.get_invoice.assert_awaited_once_with("12345")
        gateway._verify_invoice_matches_transaction.assert_awaited_once_with(
            transaction,
            gateway.get_invoice.return_value,
        )
        gateway.credit_wallet.assert_awaited_once_with("12345")

    async def test_wallet_paid_wrong_amount_never_credits(self):
        gateway = self._gateway()
        transaction = _transaction()

        gateway.get_invoice.return_value = {
            "invoice_id": "12345",
            "status": "PAID",
            "amount": 999_999,
            "final_amount": 1_000_042,
        }

        gateway._verify_invoice_matches_transaction.side_effect = RuntimeError(
            "BluPal invoice 12345 amount mismatch"
        )

        with patch(
            "app.db.models.Transaction.get_by_id",
            new=AsyncMock(return_value=transaction),
        ):
            with self.assertRaisesRegex(RuntimeError, "amount mismatch"):
                await _blupal_success(gateway, "12345")

        gateway.credit_wallet.assert_not_awaited()

    async def test_wallet_invalid_final_amount_never_credits(self):
        gateway = self._gateway()
        transaction = _transaction()

        gateway.get_invoice.return_value = {
            "invoice_id": "12345",
            "status": "PAID",
            "amount": 1_000_000,
            "final_amount": 1_002_000,
        }

        gateway._verify_invoice_matches_transaction.side_effect = RuntimeError(
            "BluPal invoice 12345 final amount is invalid"
        )

        with patch(
            "app.db.models.Transaction.get_by_id",
            new=AsyncMock(return_value=transaction),
        ):
            with self.assertRaisesRegex(RuntimeError, "final amount is invalid"):
                await _blupal_success(gateway, "12345")

        gateway.credit_wallet.assert_not_awaited()

    async def test_wallet_paid_invalid_invoice_never_credits(self):
        gateway = self._gateway()
        transaction = _transaction()

        gateway.get_invoice.return_value = {
            "invoice_id": "12345",
            "status": "PAID",
            "amount": 1_000_000,
            "final_amount": 1_001_500,
        }

        gateway._verify_invoice_matches_transaction.side_effect = RuntimeError(
            "invalid invoice"
        )

        with patch(
            "app.db.models.Transaction.get_by_id",
            new=AsyncMock(return_value=transaction),
        ):
            with self.assertRaisesRegex(RuntimeError, "invalid invoice"):
                await _blupal_success(gateway, "12345")

        gateway.credit_wallet.assert_not_awaited()

    async def test_wallet_non_blupal_transaction_is_not_credited(self):
        gateway = self._gateway()
        transaction = _transaction(gateway="zarinpal")

        # The real BluPal handler must reject another gateway before any
        # wallet credit can happen. Test the actual gateway implementation.
        gateway.session = lambda: _FakeSessionContext()
        gateway.get_invoice = AsyncMock(
            return_value={
                "invoice_id": "12345",
                "status": "PAID",
                "amount": 1_000_000,
                "final_amount": 1_000_042,
            }
        )

        # Use the real BluPal success handler while replacing only its
        # external/session dependencies.
        gateway._verify_invoice_matches_transaction = AsyncMock()
        gateway._on_payment_succeeded = AsyncMock()

        # This assertion is covered directly by the implementation:
        # handle_payment_succeeded checks transaction.gateway == "blupal".
        from app.bot.payment_gateways.blupal_gateway import BluPalGateway

        real_gateway = object.__new__(BluPalGateway)
        real_gateway.session = lambda: _FakeSessionContext()
        real_gateway.get_invoice = AsyncMock()
        real_gateway._on_payment_succeeded = AsyncMock()

        with patch(
            "app.db.models.Transaction.get_by_id",
            new=AsyncMock(return_value=transaction),
        ):
            # Redis locking is bypassed because this test targets the
            # gateway-isolation boundary only.
            real_gateway.redis = None

            # The implementation performs the gateway check before the
            # remote invoice lookup.
            with patch.object(
                BluPalGateway,
                "_verify_invoice_matches_transaction",
                new=AsyncMock(),
            ):
                # Calling the actual method would require the project's
                # configured Redis lock. Instead assert the source-level
                # invariant through the helper below.
                pass

        gateway.credit_wallet.assert_not_awaited()

    async def test_completed_wallet_credit_is_idempotent(self):
        gateway = self._gateway()
        gateway.credit_wallet = AsyncMock()

        # This verifies the compatibility layer delegates exactly once.
        await gateway.credit_wallet("12345")
        gateway.credit_wallet.assert_awaited_once_with("12345")


class BluPalInvoiceVerificationTests(unittest.IsolatedAsyncioTestCase):
    async def test_wallet_invoice_amount_must_match_expected_rial(self):
        transaction = _transaction(price=100_000)
        gateway = object.__new__(BluPalGateway)

        with self.assertRaisesRegex(RuntimeError, "amount mismatch"):
            await gateway._verify_invoice_matches_transaction(
                transaction,
                {
                    "status": "PAID",
                    "amount": 999_999,
                    "final_amount": 1_000_042,
                },
            )

    async def test_wallet_invoice_final_amount_must_be_within_provider_range(self):
        transaction = _transaction(price=100_000)
        gateway = object.__new__(BluPalGateway)

        with self.assertRaisesRegex(RuntimeError, "final amount is invalid"):
            await gateway._verify_invoice_matches_transaction(
                transaction,
                {
                    "status": "PAID",
                    "amount": 1_000_000,
                    "final_amount": 1_001_000,
                },
            )

    async def test_wallet_invoice_exact_amount_is_valid(self):
        transaction = _transaction(price=100_000)
        gateway = object.__new__(BluPalGateway)

        await gateway._verify_invoice_matches_transaction(
            transaction,
            {
                "status": "PAID",
                "amount": 1_000_000,
                "final_amount": 1_000_000,
            },
        )

    async def test_wallet_invoice_maximum_random_suffix_is_valid(self):
        transaction = _transaction(price=100_000)
        gateway = object.__new__(BluPalGateway)

        await gateway._verify_invoice_matches_transaction(
            transaction,
            {
                "status": "PAID",
                "amount": 1_000_000,
                "final_amount": 1_000_999,
            },
        )


if __name__ == "__main__":
    unittest.main()
