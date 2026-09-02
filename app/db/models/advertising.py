from datetime import datetime
from typing import Self

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class AdvertisingChannel(Base):
    __tablename__ = "advertising_channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    @classmethod
    async def list_active(cls, session: AsyncSession) -> list[Self]:
        result = await session.execute(select(cls).where(cls.is_active.is_(True)).order_by(cls.id))
        return list(result.scalars().all())

    @classmethod
    async def get_by_chat_id(cls, session: AsyncSession, chat_id: int) -> Self | None:
        result = await session.execute(select(cls).where(cls.chat_id == chat_id))
        return result.scalar_one_or_none()


class AdvertisingCampaign(Base):
    __tablename__ = "advertising_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    bot_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())


class AdvertisingEvent(Base):
    __tablename__ = "advertising_events"
    __table_args__ = (UniqueConstraint("campaign_id", "tg_id", "event_type", name="uq_ad_event_campaign_user_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("advertising_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    plan_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)

    @classmethod
    async def record_unique(cls, session: AsyncSession, campaign_id: int, tg_id: int, event_type: str, *, channel_id: int | None = None, plan_id: int | None = None) -> bool:
        existing = await session.execute(select(cls).where(cls.campaign_id == campaign_id, cls.tg_id == tg_id, cls.event_type == event_type))
        if existing.scalar_one_or_none():
            return False
        session.add(cls(campaign_id=campaign_id, tg_id=tg_id, event_type=event_type, channel_id=channel_id, plan_id=plan_id))
        await session.commit()
        return True
