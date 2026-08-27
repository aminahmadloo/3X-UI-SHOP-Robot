import logging
from datetime import datetime, timezone
from typing import Self

from sqlalchemy import *
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column, relationship, selectinload

from app.bot.utils.misc import generate_code

from . import Base

logger = logging.getLogger(__name__)


class Promocode(Base):
    """Represents a single-use promocode or real VPN gift code."""

    __tablename__ = "promocodes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(length=32), unique=True, nullable=False)
    duration: Mapped[int] = mapped_column(nullable=False)
    volume_gb: Mapped[int] = mapped_column(nullable=False, default=0)
    is_gift: Mapped[bool] = mapped_column(default=False, nullable=False)
    is_activated: Mapped[bool] = mapped_column(default=False, nullable=False)
    activated_by: Mapped[int | None] = mapped_column(ForeignKey("users.tg_id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(nullable=True)
    activated_user: Mapped["User | None"] = relationship(  # type: ignore
        "User", back_populates="activated_promocodes"
    )

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) >= expires_at

    def __repr__(self) -> str:
        return (
            f"<Promocode(id={self.id}, code='{self.code}', duration={self.duration}, "
            f"volume_gb={self.volume_gb}, is_gift={self.is_gift}, "
            f"is_activated={self.is_activated}, activated_by={self.activated_by}, "
            f"created_at={self.created_at}, expires_at={self.expires_at})>"
        )

    @classmethod
    async def get(cls, session: AsyncSession, code: str) -> Self | None:
        query = await session.execute(
            select(Promocode).options(selectinload(Promocode.activated_user)).where(Promocode.code == code)
        )
        return query.scalar_one_or_none()

    @classmethod
    async def create(cls, session: AsyncSession, **kwargs: Any) -> Self | None:
        while True:
            code = generate_code()
            if not await Promocode.get(session=session, code=code):
                break

        promocode = Promocode(code=code, **kwargs)
        session.add(promocode)
        try:
            await session.commit()
            logger.info("Promocode %s created.", promocode.code)
            return promocode
        except IntegrityError as exception:
            await session.rollback()
            logger.error("Error occurred while creating promocode %s: %s", promocode.code, exception)
            return None

    @classmethod
    async def update(cls, session: AsyncSession, code: str, **kwargs: Any) -> Self | None:
        promocode = await Promocode.get(session=session, code=code)
        if not promocode:
            logger.warning("Promocode %s not found for update.", code)
            return None
        await session.execute(update(Promocode).where(Promocode.code == code).values(**kwargs))
        await session.commit()
        logger.info("Promocode %s updated.", code)
        return promocode

    @classmethod
    async def delete(cls, session: AsyncSession, code: str) -> bool:
        promocode = await Promocode.get(session=session, code=code)
        if promocode:
            await session.delete(promocode)
            await session.commit()
            logger.info("Promocode %s deleted.", code)
            return True
        logger.warning("Promocode %s not found for deletion.", code)
        return False

    @classmethod
    async def set_activated(cls, session: AsyncSession, code: str, user_id: int) -> bool:
        promocode = await Promocode.get(session=session, code=code)
        if not promocode:
            logger.warning("Promocode %s not found for activation.", code)
            return False
        if promocode.is_activated:
            logger.warning("Promocode %s is already activated.", code)
            return False
        await Promocode.update(session=session, code=code, is_activated=True, activated_by=user_id)
        return True

    @classmethod
    async def set_deactivated(cls, session: AsyncSession, code: str) -> bool:
        promocode = await Promocode.get(session=session, code=code)
        if not promocode:
            logger.warning("Promocode %s not found for deactivation.", code)
            return False
        if not promocode.is_activated:
            logger.warning("Promocode %s is already deactivated.", code)
            return False
        await Promocode.update(session=session, code=code, is_activated=False, activated_by=None)
        return True
