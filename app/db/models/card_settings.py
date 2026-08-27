from typing import Self

from sqlalchemy import Boolean, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class CardSettings(Base):
    """Persistent card-to-card payment destination configuration."""

    __tablename__ = "card_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    card_number: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    card_holder_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    bank_name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    @classmethod
    async def get(cls, session: AsyncSession) -> Self | None:
        result = await session.execute(
            select(cls).order_by(cls.display_order.asc(), cls.id.asc()).limit(1)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_all(cls, session: AsyncSession) -> list[Self]:
        result = await session.execute(
            select(cls).order_by(cls.display_order.asc(), cls.id.asc())
        )
        return list(result.scalars().all())

    @classmethod
    async def get_active_cards(cls, session: AsyncSession) -> list[Self]:
        result = await session.execute(
            select(cls)
            .where(
                cls.is_active.is_(True),
                cls.card_number != "",
                cls.card_holder_name != "",
            )
            .order_by(cls.display_order.asc(), cls.id.asc())
        )
        return list(result.scalars().all())

    @classmethod
    async def get_or_create(
        cls,
        session: AsyncSession,
        card_number: str = "",
        card_holder_name: str = "",
    ) -> Self:
        item = await cls.get(session)
        if item:
            if not item.card_number and card_number:
                item.card_number = card_number
                item.is_active = True
                await session.commit()
                await session.refresh(item)
            return item

        item = cls(
            card_number=card_number,
            card_holder_name=card_holder_name,
            bank_name="",
            display_order=1,
            is_active=bool(card_number and card_holder_name),
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item

    @classmethod
    async def next_display_order(cls, session: AsyncSession) -> int:
        result = await session.execute(select(cls.display_order).order_by(cls.display_order.desc()).limit(1))
        current = result.scalar_one_or_none()
        return int(current or 0) + 1
