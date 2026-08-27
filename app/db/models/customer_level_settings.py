from typing import Self

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class CustomerLevelSettings(Base):
    """Global customer-level discount percentages."""

    __tablename__ = "customer_level_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    base_discount_percent: Mapped[int] = mapped_column(nullable=False, default=0)
    bronze_discount_percent: Mapped[int] = mapped_column(nullable=False, default=10)
    silver_discount_percent: Mapped[int] = mapped_column(nullable=False, default=15)
    gold_discount_percent: Mapped[int] = mapped_column(nullable=False, default=20)

    @classmethod
    async def get(cls, session: AsyncSession) -> Self | None:
        result = await session.execute(select(cls).where(cls.id == 1))
        return result.scalar_one_or_none()

    @classmethod
    async def get_or_create(cls, session: AsyncSession) -> Self:
        item = await cls.get(session)
        if item:
            return item

        item = cls(
            id=1,
            base_discount_percent=0,
            bronze_discount_percent=10,
            silver_discount_percent=15,
            gold_discount_percent=20,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item
