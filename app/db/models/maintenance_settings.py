from sqlalchemy import Boolean
from sqlalchemy.orm import Mapped, mapped_column

from ._base import Base


class MaintenanceSettings(Base):
    __tablename__ = "maintenance_settings"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
