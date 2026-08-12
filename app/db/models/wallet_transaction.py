from datetime import datetime
from typing import Self

from sqlalchemy import ForeignKey, Integer, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class WalletTransaction(Base):
    """Immutable ledger entry for a wallet credit or debit."""

    __tablename__ = "wallet_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_tg_id: Mapped[int] = mapped_column(
        ForeignKey("users.tg_id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reference_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)

    @classmethod
    async def get_recent(
        cls, session: AsyncSession, user_tg_id: int, limit: int = 10
    ) -> list[Self]:
        result = await session.execute(
            select(cls)
            .where(cls.user_tg_id == user_tg_id)
            .order_by(cls.created_at.desc(), cls.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        user_tg_id: int,
        amount: int,
        transaction_type: str,
        description: str | None = None,
        reference_id: str | None = None,
    ) -> Self:
        transaction = cls(
            user_tg_id=user_tg_id,
            amount=amount,
            transaction_type=transaction_type,
            description=description,
            reference_id=reference_id,
        )
        session.add(transaction)
        await session.commit()
        await session.refresh(transaction)
        return transaction
