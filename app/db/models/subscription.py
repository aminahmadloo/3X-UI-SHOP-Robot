from datetime import datetime

from sqlalchemy import ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class Subscription(Base):
    """
    User VPN subscription lifecycle record.
    """

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    server_id: Mapped[int | None] = mapped_column(
        ForeignKey("servers.id", ondelete="SET NULL"),
        nullable=True,
    )

    plan_id: Mapped[int | None] = mapped_column(nullable=True)

    config_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    client_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    volume_gb: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
    )

    duration_days: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
    )

    devices: Mapped[int] = mapped_column(
        nullable=False,
        default=1,
    )

    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
    )

    start_date: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    expire_date: Mapped[datetime | None] = mapped_column(
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        default=func.now(),
        nullable=False,
    )

    updated_at: Mapped[datetime] = mapped_column(
        default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship(
        "User",
        back_populates="subscriptions",
    )

    server: Mapped["Server | None"] = relationship(
        "Server",
    )
