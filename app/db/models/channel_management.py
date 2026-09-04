import json
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ChannelSettings(Base):
    """Singleton settings that extend, but do not replace, AdvertisingChannel."""
    __tablename__ = "channel_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    primary_channel_id: Mapped[int | None] = mapped_column(ForeignKey("advertising_channels.id", ondelete="SET NULL"), nullable=True)
    backup_channel_id: Mapped[int | None] = mapped_column(ForeignKey("advertising_channels.id", ondelete="SET NULL"), nullable=True)
    signature: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_buttons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    auto_publish_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    admin_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    @property
    def default_buttons(self) -> list[dict]:
        try:
            value = json.loads(self.default_buttons_json or "[]")
            return value if isinstance(value, list) else []
        except (TypeError, ValueError):
            return []

    @default_buttons.setter
    def default_buttons(self, value: list[dict]) -> None:
        self.default_buttons_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def admin_ids(self) -> list[int]:
        try:
            return [int(item) for item in json.loads(self.admin_ids_json or "[]")]
        except (TypeError, ValueError):
            return []


class ChannelContentTemplate(Base):
    __tablename__ = "channel_content_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    variable_definitions_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())

    @property
    def variable_definitions(self) -> list[dict]:
        try:
            value = json.loads(self.variable_definitions_json or "[]")
            return value if isinstance(value, list) else []
        except (TypeError, ValueError):
            return []

    @variable_definitions.setter
    def variable_definitions(self, value: list[dict]) -> None:
        self.variable_definitions_json = json.dumps(value or [], ensure_ascii=False)


class ChannelContentEvent(Base):
    __tablename__ = "channel_content_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_id: Mapped[int] = mapped_column(ForeignKey("channel_contents.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}", server_default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), index=True)
