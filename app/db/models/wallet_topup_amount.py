from sqlalchemy import Boolean, Integer, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class WalletTopupAmount(Base):
    """Preset wallet top-up amount managed by Telegram admins."""

    __tablename__ = "wallet_topup_amounts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    @classmethod
    async def get_all(cls, session: AsyncSession) -> list["WalletTopupAmount"]:
        result = await session.execute(
            select(cls)
            .where(cls.is_active.is_(True))
            .order_by(cls.sort_order.asc(), cls.amount.asc())
        )
        return list(result.scalars().all())

    @classmethod
    async def get(cls, session: AsyncSession, amount_id: int) -> "WalletTopupAmount | None":
        return await session.get(cls, amount_id)

    @classmethod
    async def create(
        cls, session: AsyncSession, amount: int, sort_order: int | None = None
    ) -> "WalletTopupAmount | None":
        if sort_order is None:
            result = await session.execute(select(cls.sort_order).order_by(cls.sort_order.desc()).limit(1))
            last_order = result.scalar_one_or_none()
            sort_order = (last_order or 0) + 1

        item = cls(amount=amount, sort_order=sort_order, is_active=True)
        session.add(item)
        try:
            await session.commit()
            await session.refresh(item)
            return item
        except Exception:
            await session.rollback()
            return None

    @classmethod
    async def update_amount(
        cls, session: AsyncSession, amount_id: int, amount: int
    ) -> "WalletTopupAmount | None":
        item = await cls.get(session, amount_id)
        if not item:
            return None
        item.amount = amount
        try:
            await session.commit()
            await session.refresh(item)
            return item
        except Exception:
            await session.rollback()
            return None

    @classmethod
    async def delete(cls, session: AsyncSession, amount_id: int) -> bool:
        item = await cls.get(session, amount_id)
        if not item:
            return False
        await session.delete(item)
        try:
            await session.commit()
            return True
        except Exception:
            await session.rollback()
            return False
