import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
from aiogram.types import User as TelegramUser
from aiogram.utils.i18n import gettext as _
from sqlalchemy import select

from app.bot.filters import IsAdmin
from app.bot.services import NotificationService
from app.db.models import MaintenanceSettings

logger = logging.getLogger(__name__)


class MaintenanceMiddleware(BaseMiddleware):
    active: bool = False

    def __init__(self) -> None:
        logger.debug("Maintenance Middleware initialized.")

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Update):
            user: TelegramUser | None = event.event.from_user

            if user is not None:
                is_admin = await IsAdmin()(user_id=user.id)
                logger.debug(
                    f"Is user {user.id} an admin? "
                    f"{'Yes' if is_admin else 'No'}"
                )

                if self.active and not is_admin and user.id != event.bot.id:
                    logger.info(
                        f"User {user.id} tried to use bot in maintenance"
                    )

                    message = None

                    if event.message:
                        message = event.message
                    elif (
                        event.callback_query
                        and event.callback_query.message
                    ):
                        message = event.callback_query.message

                    if message:
                        await NotificationService.notify_by_message(
                            message=message,
                            text=_("maintenance:ntf:try_later"),
                            duration=5,
                        )

                    return None

                logger.debug(
                    f"User {user.id} is allowed to interact with the bot."
                )

        return await handler(event, data)

    @classmethod
    def set_mode(cls, active: bool) -> None:
        cls.active = active
        logger.info(
            f"Maintenance Mode: {'enabled' if active else 'disabled'}"
        )

    @classmethod
    async def load_from_database(cls, session) -> bool:
        async with session() as db_session:
            result = await db_session.execute(
                select(MaintenanceSettings).where(
                    MaintenanceSettings.id == 1
                )
            )
            settings = result.scalar_one_or_none()

            if settings is None:
                settings = MaintenanceSettings(id=1, enabled=False)
                db_session.add(settings)
                await db_session.commit()
                active = False
            else:
                active = bool(settings.enabled)

        cls.set_mode(active)

        logger.info(
            "Maintenance Mode restored from database: "
            f"{'enabled' if active else 'disabled'}"
        )

        return active

    @classmethod
    async def persist_mode(cls, session, active: bool) -> None:
        async with session() as db_session:
            result = await db_session.execute(
                select(MaintenanceSettings).where(
                    MaintenanceSettings.id == 1
                )
            )
            settings = result.scalar_one_or_none()

            if settings is None:
                settings = MaintenanceSettings(
                    id=1,
                    enabled=active,
                )
                db_session.add(settings)
            else:
                settings.enabled = active

            await db_session.commit()

        cls.set_mode(active)

        logger.info(
            "Maintenance Mode persisted: "
            f"{'enabled' if active else 'disabled'}"
        )
