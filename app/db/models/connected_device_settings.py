from typing import Self

from sqlalchemy import Integer, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ConnectedDeviceSettings(Base):
    """Persistent setting for the maximum number of connected devices."""

    __tablename__ = "connected_device_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    max_connected_devices: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )

    @classmethod
    async def get(cls, session: AsyncSession) -> Self | None:
        result = await session.execute(
            select(cls).where(cls.id == 1)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def get_or_create(cls, session: AsyncSession) -> Self:
        item = await cls.get(session)

        if item:
            return item

        item = cls(
            id=1,
            max_connected_devices=1,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)

        return item
