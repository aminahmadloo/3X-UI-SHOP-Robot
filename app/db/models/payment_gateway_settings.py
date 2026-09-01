from typing import Self

from sqlalchemy import Boolean, String, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class PaymentGatewaySettings(Base):
    """Persistent settings for payment gateway routing and credentials."""

    __tablename__ = "payment_gateway_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    zarinpal_payment_base_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    zarinpal_payment_base_url_configured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # These values are only read server-side. They are never sent to customers.
    # The admin UI masks them when displaying the current configuration.
    nahanramz_api_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    nahanramz_webhook_secret: Mapped[str] = mapped_column(String(500), nullable=False, default="")

    # KPay: legacy column name is retained for DB compatibility. Its value is
    # the KPay ACCOUNT ACCESS TOKEN used for Bearer authentication, not the
    # Shop API key shown in the KPay dashboard. Shop/Card UUIDs are discovered
    # automatically from KPay and cached below. Full card numbers are never stored.
    kpay_api_key: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    kpay_shop_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    kpay_card_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    @classmethod
    async def get(cls, session: AsyncSession) -> Self | None:
        result = await session.execute(select(cls).where(cls.id == 1))
        return result.scalar_one_or_none()

    @property
    def nahanramz_configured(self) -> bool:
        return bool(self.nahanramz_api_key.strip() and self.nahanramz_webhook_secret.strip())

    @property
    def kpay_configured(self) -> bool:
        return bool(
            self.kpay_api_key.strip()
            and self.kpay_shop_id.strip()
            and self.kpay_card_id.strip()
        )
