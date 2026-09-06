from typing import Self

from sqlalchemy import Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


DEFAULT_REFERRAL_SHARE_TEXT = (
    "من به‌تازگی مشتری تونلVPN شدم و از کیفیت سرویس‌هاش واقعاً راضی‌ام. "
    "پینگ عالی، سرعت مناسب و قیمت‌های مقرون‌به‌صرفه از مزیت‌های این سرویسه.\n\n"
    "اگر دوست داشتی تو هم امتحانش کنی، از طریق لینک زیر وارد شو و خریدت رو انجام بده:\n\n"
    "🔗 {referral_link}"
)


class ReferralSettings(Base):
    """Global referral commission and sharing settings."""

    __tablename__ = "referral_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    reward_percent: Mapped[int] = mapped_column(nullable=False, default=30)
    repeat_reward_percent: Mapped[int] = mapped_column(nullable=False, default=5)
    share_text: Mapped[str] = mapped_column(
        Text, nullable=False, default=DEFAULT_REFERRAL_SHARE_TEXT
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
            reward_percent=30,
            repeat_reward_percent=5,
            share_text=DEFAULT_REFERRAL_SHARE_TEXT,
        )
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item
