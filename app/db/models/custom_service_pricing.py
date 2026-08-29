from typing import Self

from sqlalchemy import Float, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class CustomServicePricing(Base):
    """Persistent base prices used by custom-service pricing."""

    __tablename__ = "custom_service_pricing"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    base_price_per_day: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    base_price_per_gb: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    base_price_per_device: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    base_price_per_location: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    show_custom_service_button: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        server_default="1",
    )

    @classmethod
    async def get(cls, session: AsyncSession) -> Self | None:
        result = await session.execute(select(cls).where(cls.id == 1))
        return result.scalar_one_or_none()

    @classmethod
    async def get_or_create(cls, session: AsyncSession) -> Self:
        item = await cls.get(session)
        if item:
            return item
        item = cls(id=1)
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item
