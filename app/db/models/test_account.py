from datetime import datetime
from typing import Self

from sqlalchemy import Boolean, DateTime, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class TestAccountSettings(Base):
    __tablename__ = "test_account_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    volume_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=200)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    cleanup_interval_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=12
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
        item = cls(
            id=1,
            enabled=True,
            volume_mb=200,
            duration_days=2,
            cleanup_interval_hours=12,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item


class TestAccount(Base):
    __tablename__ = "test_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    server_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    inbound_id: Mapped[int] = mapped_column(Integer, nullable=False)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    client_email: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    subscription_token: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    quota_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    usage_up_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    usage_down_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    @classmethod
    async def get_by_telegram_id(cls, session: AsyncSession, telegram_user_id: int) -> Self | None:
        result = await session.execute(
            select(cls).where(cls.telegram_user_id == telegram_user_id)
        )
        return result.scalar_one_or_none()
