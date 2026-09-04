from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ChannelTemplate(Base):
    __tablename__ = "channel_templates"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    template_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class ChannelSetting(Base):
    __tablename__ = "channel_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("advertising_channels.id", ondelete="CASCADE"), unique=True, nullable=False, index=True)
    backup_channel_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    auto_signature: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_buttons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    auto_publish: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    admin_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class ChannelReferralCampaign(Base):
    __tablename__ = "channel_referral_campaigns"
    __table_args__ = (UniqueConstraint("invite_id", name="uq_channel_referral_campaign_invite"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    invite_id: Mapped[int] = mapped_column(ForeignKey("invites.id", ondelete="CASCADE"), nullable=False, index=True)
    reward_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
