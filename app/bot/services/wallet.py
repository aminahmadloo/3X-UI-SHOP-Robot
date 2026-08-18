import logging

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import Wallet, WalletTransaction

logger = logging.getLogger(__name__)


class WalletService:
    """Application service for wallet balance and ledger operations."""

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self.session_factory = session_factory

    async def get_balance(self, user_tg_id: int) -> int:
        async with self.session_factory() as session:
            return await Wallet.get_balance(session, user_tg_id)

    async def get_recent_transactions(
        self, user_tg_id: int, limit: int = 10
    ) -> list[WalletTransaction]:
        async with self.session_factory() as session:
            return await WalletTransaction.get_recent(session, user_tg_id, limit)

    async def credit(
        self,
        user_tg_id: int,
        amount: int,
        transaction_type: str = "topup",
        description: str | None = None,
        reference_id: str | None = None,
    ) -> int:
        if amount <= 0:
            raise ValueError("Wallet credit amount must be positive.")

        async with self.session_factory() as session:
            return await self._change_balance(
                session,
                user_tg_id=user_tg_id,
                delta=amount,
                transaction_type=transaction_type,
                description=description,
                reference_id=reference_id,
            )

    async def debit(
        self,
        user_tg_id: int,
        amount: int,
        transaction_type: str = "purchase",
        description: str | None = None,
        reference_id: str | None = None,
    ) -> int:
        if amount <= 0:
            raise ValueError("Wallet debit amount must be positive.")

        async with self.session_factory() as session:
            return await self._change_balance(
                session,
                user_tg_id=user_tg_id,
                delta=-amount,
                transaction_type=transaction_type,
                description=description,
                reference_id=reference_id,
            )

    async def _change_balance(
        self,
        session: AsyncSession,
        *,
        user_tg_id: int,
        delta: int,
        transaction_type: str,
        description: str | None,
        reference_id: str | None,
    ) -> int:
        # A reference is the idempotency key for wallet mutations. If the
        # same operation is retried after a timeout, never apply it twice.
        if reference_id:
            existing = await session.execute(
                select(WalletTransaction).where(
                    WalletTransaction.reference_id == reference_id
                )
            )
            existing_transaction = existing.scalar_one_or_none()
            if existing_transaction:
                wallet = await Wallet.get_or_create(session, user_tg_id)
                return wallet.balance

        wallet = await Wallet.get_or_create(session, user_tg_id)

        # Do the balance check and mutation in one SQL UPDATE. This avoids
        # the read-modify-write race where two concurrent purchases could
        # both observe the same balance and overspend the wallet.
        balance_condition = (
            Wallet.balance + delta >= 0 if delta < 0 else True
        )
        result = await session.execute(
            update(Wallet)
            .where(Wallet.id == wallet.id, balance_condition)
            .values(balance=Wallet.balance + delta)
        )

        if result.rowcount != 1:
            await session.rollback()
            raise ValueError("Insufficient wallet balance.")

        session.add(
            WalletTransaction(
                user_tg_id=user_tg_id,
                amount=delta,
                transaction_type=transaction_type,
                description=description,
                reference_id=reference_id,
            )
        )

        try:
            await session.commit()
        except IntegrityError:
            # reference_id is unique. A concurrent retry may have inserted
            # the same ledger entry first; in that case this operation must
            # not leave a second balance mutation behind.
            await session.rollback()
            if reference_id:
                async with self.session_factory() as retry_session:
                    existing = await retry_session.execute(
                        select(WalletTransaction).where(
                            WalletTransaction.reference_id == reference_id
                        )
                    )
                    if existing.scalar_one_or_none():
                        wallet = await Wallet.get(retry_session, user_tg_id)
                        return wallet.balance if wallet else 0
            raise

        await session.refresh(wallet)
        logger.info(
            "Wallet changed for user %s: delta=%s balance=%s type=%s",
            user_tg_id,
            delta,
            wallet.balance,
            transaction_type,
        )
        return wallet.balance
