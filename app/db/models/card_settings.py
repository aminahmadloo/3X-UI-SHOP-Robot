from typing import Self

from sqlalchemy import Boolean, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class CardSettings(Base):
    """Persistent configuration for card-to-card wallet payments."""

    __tablename__ = "card_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    card_number: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    card_holder_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    @classmethod
    async def get(cls, session: AsyncSession) -> Self | None:
        result = await session.execute(select(cls).where(cls.id == 1))
        return result.scalar_one_or_none()

    @classmethod
    async def get_or_create(
        cls,
        session: AsyncSession,
        card_number: str = "",
        card_holder_name: str = "",
    ) -> Self:
        item = await cls.get(session)
        if item:
            return item
        item = cls(id=1, card_number=card_number, card_holder_name=card_holder_name, is_active=bool(card_number))
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item
