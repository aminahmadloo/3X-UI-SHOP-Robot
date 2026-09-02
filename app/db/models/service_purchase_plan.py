from sqlalchemy import Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ServicePurchasePlan(Base):
    __tablename__ = "service_purchase_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_type: Mapped[str]
    volume_gb: Mapped[int]
    duration_days: Mapped[int]
    price_toman: Mapped[int]
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_special_offer: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    special_offer_price_toman: Mapped[int | None] = mapped_column(Integer, nullable=True)
