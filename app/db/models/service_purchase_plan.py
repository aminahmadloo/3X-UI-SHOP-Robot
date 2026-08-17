from typing import Self

from sqlalchemy import Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ServicePurchasePlan(Base):
    """Admin-managed service purchase plans."""

    __tablename__ = "service_purchase_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    volume_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    price_toman: Mapped[int] = mapped_column(Integer, nullable=False)

    @classmethod
    async def get(
        cls,
        session: AsyncSession,
        plan_id: int,
    ) -> Self | None:
        result = await session.execute(
            select(cls).where(cls.id == plan_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def list_by_type(
        cls,
        session: AsyncSession,
        service_type: str,
    ) -> list[Self]:
        result = await session.execute(
            select(cls)
            .where(cls.service_type == service_type)
            .order_by(cls.id)
        )
        return list(result.scalars().all())
