import logging

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
        wallet = await Wallet.get_or_create(session, user_tg_id)

        if wallet.balance + delta < 0:
            raise ValueError("Insufficient wallet balance.")

        wallet.balance += delta
        session.add(
            WalletTransaction(
                user_tg_id=user_tg_id,
                amount=delta,
                transaction_type=transaction_type,
                description=description,
                reference_id=reference_id,
            )
        )
        await session.commit()
        logger.info(
            "Wallet changed for user %s: delta=%s balance=%s type=%s",
            user_tg_id,
            delta,
            wallet.balance,
            transaction_type,
        )
        return wallet.balance
