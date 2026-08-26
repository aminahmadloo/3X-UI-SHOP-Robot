import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update

from app.bot.utils.navigation import NavMain

logger = logging.getLogger(__name__)


class GarbageMiddleware(BaseMiddleware):
    def __init__(self) -> None:
        logger.debug("Garbage Middleware initialized.")

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if isinstance(event, Update) and event.message:
            user_id = event.message.from_user.id

            if user_id == event.bot.id:
                logger.debug(f"Message from bot {event.bot.id} skipped.")

            else:
                # Messages sent while an FSM input state is active must
                # reach the corresponding message handler before Garbage
                # Middleware can delete them.
                fsm_state = data.get("state")
                current_state = None

                if fsm_state is not None:
                    try:
                        current_state = await fsm_state.get_state()
                    except Exception as exception:
                        logger.debug(
                            f"Could not read FSM state for user {user_id}: {exception}"
                        )

                is_env_editor_input = (
                    current_state == "EnvSettingsStates:waiting_value"
                )

                if is_env_editor_input:
                    logger.debug(
                        f"Message from user {user_id} preserved for "
                        f"env editor FSM state: {current_state}"
                    )

                elif (
                    event.message.text
                    and not event.message.text.endswith(NavMain.START)
                    or event.message.forward_from
                ):
                    try:
                        await event.message.delete()
                        logger.debug(
                            f"Message {event.message.text} from user "
                            f"{user_id} deleted."
                        )
                    except Exception as exception:
                        logger.error(
                            f"Failed to delete message from user "
                            f"{user_id}: {exception}"
                        )

        return await handler(event, data)
