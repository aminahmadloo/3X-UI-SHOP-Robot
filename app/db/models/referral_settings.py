from typing import Self

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ReferralSettings(Base):
    """Global referral commission settings."""

    __tablename__ = "referral_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    reward_percent: Mapped[int] = mapped_column(nullable=False, default=30)
    repeat_reward_percent: Mapped[int] = mapped_column(nullable=False, default=5)

    @classmethod
    async def get(cls, session: AsyncSession) -> Self | None:
        result = await session.execute(select(cls).where(cls.id == 1))
        return result.scalar_one_or_none()

    @classmethod
    async def get_or_create(cls, session: AsyncSession) -> Self:
        item = await cls.get(session)
        if item:
            return item

        item = cls(id=1, reward_percent=30, repeat_reward_percent=5)
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item
