import logging
from typing import Self

from sqlalchemy import ForeignKey, Integer, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base

logger = logging.getLogger(__name__)


class Wallet(Base):
    """User wallet containing the current available balance in Toman."""

    __tablename__ = "wallets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_tg_id: Mapped[int] = mapped_column(
        ForeignKey("users.tg_id", ondelete="CASCADE"), unique=True, nullable=False
    )
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    @classmethod
    async def get(cls, session: AsyncSession, user_tg_id: int) -> Self | None:
        result = await session.execute(select(cls).where(cls.user_tg_id == user_tg_id))
        return result.scalar_one_or_none()

    @classmethod
    async def get_or_create(cls, session: AsyncSession, user_tg_id: int) -> Self:
        wallet = await cls.get(session, user_tg_id)
        if wallet:
            return wallet

        wallet = cls(user_tg_id=user_tg_id, balance=0)
        session.add(wallet)
        await session.flush()
        logger.info(f"Wallet created for user {user_tg_id}.")
        return wallet

    @classmethod
    async def get_balance(cls, session: AsyncSession, user_tg_id: int) -> int:
        wallet = await cls.get(session, user_tg_id)
        return wallet.balance if wallet else 0

    @classmethod
    async def change_balance(cls, session: AsyncSession, user_tg_id: int, delta: int) -> int:
        wallet = await cls.get_or_create(session, user_tg_id)
        new_balance = wallet.balance + delta
        if new_balance < 0:
            raise ValueError("Wallet balance cannot be negative.")

        await session.execute(
            update(cls).where(cls.id == wallet.id).values(balance=new_balance)
        )
        await session.commit()
        return new_balance
