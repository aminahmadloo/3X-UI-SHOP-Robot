import json
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ChannelContent(Base):
    __tablename__ = "channel_contents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("advertising_channels.id", ondelete="CASCADE"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="پست کانال", server_default="پست کانال")
    content_type: Mapped[str] = mapped_column(String(16), nullable=False, default="text", server_default="text")
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    show_caption_above_media: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    buttons_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    poll_question: Mapped[str | None] = mapped_column(Text, nullable=True)
    poll_options_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]", server_default="[]")
    poll_is_anonymous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    poll_allows_multiple: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft", server_default="draft", index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    @property
    def buttons(self) -> list[dict]:
        try:
            value = json.loads(self.buttons_json or "[]")
            return value if isinstance(value, list) else []
        except (TypeError, ValueError):
            return []

    @buttons.setter
    def buttons(self, value: list[dict]) -> None:
        self.buttons_json = json.dumps(value or [], ensure_ascii=False)

    @property
    def poll_options(self) -> list[str]:
        try:
            value = json.loads(self.poll_options_json or "[]")
            return [str(item) for item in value] if isinstance(value, list) else []
        except (TypeError, ValueError):
            return []

    @poll_options.setter
    def poll_options(self, value: list[str]) -> None:
        self.poll_options_json = json.dumps(value or [], ensure_ascii=False)
