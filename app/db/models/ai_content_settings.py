from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class AIContentSettings(Base):
    __tablename__ = "ai_content_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="approval", server_default="approval")
    model: Mapped[str] = mapped_column(String(64), nullable=False, default="gpt-5.6-luna", server_default="gpt-5.6-luna")
    topics: Mapped[str] = mapped_column(Text, nullable=False, default="آموزشی,خبری,تعامل,معرفی قابلیت,فروش ویژه", server_default="آموزشی,خبری,تعامل,معرفی قابلیت,فروش ویژه")
    production_controls: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    smart_rules: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    smart_risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="balanced", server_default="balanced")
    posts_per_day: Mapped[int] = mapped_column(Integer, nullable=False, default=2, server_default="2")
    auto_schedule: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    updated_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
