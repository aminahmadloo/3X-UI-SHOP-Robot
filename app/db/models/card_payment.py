from datetime import datetime
from typing import Self

from sqlalchemy import ForeignKey, Integer, String, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class CardPayment(Base):
    """Manual card-to-card wallet top-up request submitted with a receipt."""

    __tablename__ = "card_payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_tg_id: Mapped[int] = mapped_column(
        ForeignKey("users.tg_id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    receipt_file_id: Mapped[str] = mapped_column(String(512), nullable=False)
    tracking_code: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    admin_tg_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    admin_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(default=func.now(), nullable=False)
    reviewed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    @classmethod
    async def get(cls, session: AsyncSession, payment_id: int) -> Self | None:
        return await session.get(cls, payment_id)

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        user_tg_id: int,
        amount: int,
        receipt_file_id: str,
        tracking_code: str,
    ) -> Self:
        item = cls(
            user_tg_id=user_tg_id,
            amount=amount,
            receipt_file_id=receipt_file_id,
            tracking_code=tracking_code,
            status="pending",
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item

    @classmethod
    async def get_pending(cls, session: AsyncSession) -> list[Self]:
        result = await session.execute(
            select(cls).where(cls.status == "pending").order_by(cls.created_at.asc())
        )
        return list(result.scalars().all())
