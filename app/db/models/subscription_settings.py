from typing import Self

from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class SubscriptionSettings(Base):
    """Global settings for generated subscription URLs and user controls."""

    __tablename__ = "subscription_settings"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        default=1,
    )

    domain: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
    )

    port: Mapped[int] = mapped_column(
        nullable=False,
        default=2096,
    )

    path: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="sub",
    )

    allow_user_client_toggle: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
    )

    @classmethod
    async def get(cls, session: AsyncSession) -> Self | None:
        result = await session.execute(
            select(cls).where(cls.id == 1)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_or_create(
        cls,
        session: AsyncSession,
    ) -> Self:
        item = await cls.get(session)

        if item:
            return item

        item = cls(
            id=1,
            domain="",
            port=2096,
            path="sub",
            allow_user_client_toggle=False,
        )

        session.add(item)
        await session.commit()
        await session.refresh(item)

        return item
