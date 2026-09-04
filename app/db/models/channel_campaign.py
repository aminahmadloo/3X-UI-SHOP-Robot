from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import quote

from aiogram import Bot
from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ChannelCampaign(Base):
    __tablename__ = "channel_campaigns"
    __table_args__ = (UniqueConstraint("slug", name="uq_channel_campaign_slug"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    campaign_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="referral", index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="active", index=True)
    start_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    end_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    def is_active_now(self, now: datetime | None = None) -> bool:
        now = now or datetime.utcnow()
        return self.status == "active" and self.start_date <= now and (self.end_date is None or self.end_date >= now)


class ChannelCampaignMember(Base):
    __tablename__ = "channel_campaign_members"
    __table_args__ = (UniqueConstraint("campaign_id", "telegram_user_id", name="uq_campaign_member_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("channel_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False, server_default="campaign")
    joined_channel: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    started_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    converted_to_customer: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)


class ChannelMemberSnapshot(Base):
    __tablename__ = "channel_member_snapshots"
    __table_args__ = (UniqueConstraint("channel_id", "snapshot_date", name="uq_channel_member_snapshot_date"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class CampaignEvent(Base):
    __tablename__ = "campaign_events"
    __table_args__ = (UniqueConstraint("campaign_id", "telegram_user_id", "event_type", name="uq_campaign_event_user_type"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("channel_campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    telegram_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    referrer_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)
