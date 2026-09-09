from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot.models import SubscriptionData
from app.bot.payment_gateways.blupal_gateway import BluPalGateway
from app.bot.routers.blupal_smart_card_compat import _blupal_success, _ORIGINAL_BLUPAL_SUCCESS
from app.bot.utils.constants import TransactionStatus
from app.bot.utils.navigation import NavSubscription


class _FakeSessionContext:
    def __init__(self, db=None):
        self.db = db if db is not None else object()

    async def __aenter__(self):
        return self.db

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeRedisLock:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeRedis:
    def lock(self, *args, **kwargs):
        return _FakeRedisLock()


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


class BluPalWalletCompatibilityTests(unittest.IsolatedAsyncioTestCase):
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


class BluPalWalletInvoiceVerificationTests(unittest.IsolatedAsyncioTestCase):
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


class BluPalGatewayIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_blupal_transaction_is_rejected_before_invoice_lookup(self):
        transaction = _transaction(gateway="pay_aban")

        gateway = object.__new__(BluPalGateway)
        gateway.storage = SimpleNamespace(redis=_FakeRedis())
        gateway.get_invoice = AsyncMock()
        gateway._on_payment_succeeded = AsyncMock()

        fake_db = object()
        gateway.session = lambda: _FakeSessionContext(fake_db)

        with patch(
            "app.db.models.Transaction.get_by_id",
            new=AsyncMock(return_value=transaction),
        ) as get_by_id:
            with self.assertRaisesRegex(RuntimeError, "does not belong to BluPal"):
                await _ORIGINAL_BLUPAL_SUCCESS(gateway, "12345")

        get_by_id.assert_awaited_once_with(
            session=fake_db,
            payment_id="12345",
        )
        gateway.get_invoice.assert_not_awaited()
        gateway._on_payment_succeeded.assert_not_awaited()

    async def test_completed_blupal_transaction_is_idempotent(self):
        transaction = _transaction(status=TransactionStatus.COMPLETED)

        gateway = object.__new__(BluPalGateway)
        gateway.storage = SimpleNamespace(redis=_FakeRedis())
        gateway.get_invoice = AsyncMock()
        gateway._on_payment_succeeded = AsyncMock()

        fake_db = object()
        gateway.session = lambda: _FakeSessionContext(fake_db)

        with patch(
            "app.db.models.Transaction.get_by_id",
            new=AsyncMock(return_value=transaction),
        ) as get_by_id:
            await _ORIGINAL_BLUPAL_SUCCESS(gateway, "12345")
            await _ORIGINAL_BLUPAL_SUCCESS(gateway, "12345")

        self.assertEqual(get_by_id.await_count, 2)
        gateway.get_invoice.assert_not_awaited()
        gateway._on_payment_succeeded.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
