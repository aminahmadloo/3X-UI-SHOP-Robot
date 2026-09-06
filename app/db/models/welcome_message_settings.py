from typing import Self

from sqlalchemy import Text, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


DEFAULT_WELCOME_MESSAGE = (
    "🌀 <b>{first_name} عزیز، به ToonelVPN خوش آمدی</b> 🌐\n\n"
    "⚡️ اتصال سریع، پایدار و مطمئن به اینترنت آزاد، با سرویس‌هایی متناسب با نیازت.\n\n"
    "🚀 سرویس‌های متنوع برای استفاده روزمره\n"
    "🌍 سرورهای مختلف برای انتخاب بهتر\n"
    "🛡️ اتصال پایدار و مطمئن\n"
    "💻 سازگار با دستگاه‌های مختلف\n"
    "🔄 خرید، تمدید و مدیریت آسان سرویس\n"
    "──────────────────\n\n"
    "🎁 <b>برای شروع، می‌تونی اکانت تست رو امتحان کنی.</b>\n\n"
    "✨ <b>یکی از گزینه‌های زیر رو انتخاب کن:</b> 👇"
)


class WelcomeMessageSettings(Base):
    """Global main-menu welcome message template."""

    __tablename__ = "welcome_message_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    message: Mapped[str] = mapped_column(Text, nullable=False, default=DEFAULT_WELCOME_MESSAGE)

    @classmethod
    async def get(cls, session: AsyncSession) -> Self | None:
        result = await session.execute(select(cls).where(cls.id == 1))
        return result.scalar_one_or_none()

    @classmethod
    async def get_or_create(cls, session: AsyncSession) -> Self:
        item = await cls.get(session)
        if item:
            return item

        item = cls(id=1, message=DEFAULT_WELCOME_MESSAGE)
        session.add(item)
        await session.commit()
        await session.refresh(item)
        return item
