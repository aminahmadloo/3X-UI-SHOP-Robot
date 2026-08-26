from typing import Self

from sqlalchemy import Boolean, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class PaymentGatewaySettings(Base):
    """Persistent non-secret settings for payment gateway routing."""

    __tablename__ = "payment_gateway_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    zarinpal_payment_base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    zarinpal_payment_base_url_configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    @classmethod
    async def get(cls, session: AsyncSession) -> Self | None:
        result = await session.execute(select(cls).where(cls.id == 1))
        return result.scalar_one_or_none()
