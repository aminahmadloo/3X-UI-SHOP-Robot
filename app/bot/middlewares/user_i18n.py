from typing import Any

from aiogram.types import TelegramObject
from aiogram.utils.i18n import SimpleI18nMiddleware

from app.bot.utils.constants import DEFAULT_LANGUAGE


class UserI18nMiddleware(SimpleI18nMiddleware):
    async def get_locale(self, event: TelegramObject, data: dict[str, Any]) -> str:
        user = data.get("user")
        language = getattr(user, "language_code", None)
        if language in self.i18n.available_locales:
            return language
        return DEFAULT_LANGUAGE
