from __future__ import annotations

from typing import Self

from sqlalchemy import Boolean, ForeignKey, Integer, String, UniqueConstraint, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class SpecialOfferCampaign(Base):
    """A named, admin-managed special-offer campaign."""

    __tablename__ = "special_offer_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1", index=True)

    @classmethod
    async def get(cls, session: AsyncSession, campaign_id: int) -> Self | None:
        result = await session.execute(select(cls).where(cls.id == campaign_id))
        return result.scalar_one_or_none()

    @classmethod
    async def get_default(cls, session: AsyncSession) -> Self | None:
        result = await session.execute(select(cls).where(cls.is_default.is_(True)))
        return result.scalar_one_or_none()

    @classmethod
    async def list_all(cls, session: AsyncSession) -> list[Self]:
        result = await session.execute(
            select(cls).order_by(cls.is_default.desc(), cls.id)
        )
        return list(result.scalars().all())

    @classmethod
    async def list_active(cls, session: AsyncSession) -> list[Self]:
        result = await session.execute(
            select(cls).where(cls.is_active.is_(True)).order_by(cls.is_default.desc(), cls.id)
        )
        return list(result.scalars().all())


class SpecialOfferCampaignPlan(Base):
    """A service plan included in a campaign with its campaign-specific price."""

    __tablename__ = "special_offer_campaign_plans"
    __table_args__ = (
        UniqueConstraint("campaign_id", "plan_id", name="uq_special_offer_campaign_plan"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("special_offer_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("service_purchase_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    special_price_toman: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1", index=True)

    @classmethod
    async def get(cls, session: AsyncSession, campaign_id: int, plan_id: int) -> Self | None:
        result = await session.execute(
            select(cls).where(cls.campaign_id == campaign_id, cls.plan_id == plan_id)
        )
        return result.scalar_one_or_none()

    @classmethod
    async def list_for_campaign(
        cls,
        session: AsyncSession,
        campaign_id: int,
        *,
        active_only: bool = False,
    ) -> list[Self]:
        query = select(cls).where(cls.campaign_id == campaign_id)
        if active_only:
            query = query.where(cls.is_active.is_(True), cls.special_price_toman > 0)
        result = await session.execute(query.order_by(cls.plan_id))
        return list(result.scalars().all())
