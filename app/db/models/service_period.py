from __future__ import annotations

from typing import Self

from sqlalchemy import Boolean, Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ServicePeriod(Base):
    """Dynamic, admin-managed subscription periods."""

    __tablename__ = "service_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    months: Mapped[int] = mapped_column(Integer, nullable=False, unique=True, index=True)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    service_type: Mapped[str] = mapped_column(String(20), nullable=False, unique=True, index=True)
    traffic_addon_service_type: Mapped[str] = mapped_column(String(30), nullable=False, unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    @classmethod
    async def get(cls, session: AsyncSession, period_id: int) -> Self | None:
        result = await session.execute(select(cls).where(cls.id == period_id))
        return result.scalar_one_or_none()

    @classmethod
    async def list_active(cls, session: AsyncSession) -> list[Self]:
        result = await session.execute(select(cls).where(cls.is_active.is_(True), cls.is_archived.is_(False)).order_by(cls.sort_order, cls.months))
        return list(result.scalars().all())

    @classmethod
    async def list_manageable(cls, session: AsyncSession) -> list[Self]:
        result = await session.execute(select(cls).where(cls.is_archived.is_(False)).order_by(cls.sort_order, cls.months))
        return list(result.scalars().all())

    @classmethod
    async def get_by_months(cls, session: AsyncSession, months: int) -> Self | None:
        result = await session.execute(select(cls).where(cls.months == months))
        return result.scalar_one_or_none()
