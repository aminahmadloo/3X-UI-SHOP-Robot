from typing import Self

from sqlalchemy import Integer, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ServicePurchasePlan(Base):
    """Admin-managed purchase, renewal and add-on plans.

    ``plan_kind`` keeps the commercial products separate while allowing
    existing service_type values and legacy rows to remain compatible.
    """

    __tablename__ = "service_purchase_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    service_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    volume_gb: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    price_toman: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_kind: Mapped[str] = mapped_column(
        String(20), nullable=False, default="purchase", server_default="purchase", index=True
    )

    @classmethod
    async def get(
        cls,
        session: AsyncSession,
        plan_id: int,
    ) -> Self | None:
        result = await session.execute(select(cls).where(cls.id == plan_id))
        return result.scalar_one_or_none()

    @classmethod
    async def list_by_type(
        cls,
        session: AsyncSession,
        service_type: str,
        plan_kind: str = "purchase",
    ) -> list[Self]:
        result = await session.execute(
            select(cls)
            .where(cls.service_type == service_type, cls.plan_kind == plan_kind)
            .order_by(cls.id)
        )
        return list(result.scalars().all())
