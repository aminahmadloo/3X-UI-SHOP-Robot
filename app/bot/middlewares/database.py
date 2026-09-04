import logging
import uuid
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from aiogram.types import User as TelegramUser
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.services.channel_campaign import CAMPAIGN_PREFIX, ChannelCampaignService
from app.bot.utils.constants import DEFAULT_LANGUAGE
from app.db.models import Referral, User

logger = logging.getLogger(__name__)


class DBSessionMiddleware(BaseMiddleware):
    def __init__(self, session: async_sessionmaker) -> None:
        self.session = session
        logger.debug("Database Session Middleware initialized.")

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session() as session:
            tg_user: TelegramUser | None = event.event.from_user

            if tg_user is not None and not tg_user.is_bot:
                user = await User.get(session=session, tg_id=tg_user.id)
                is_new_user = False

                if not user:
                    is_new_user = True
                    user = await User.create(
                        session=session,
                        tg_id=tg_user.id,
                        vpn_id=str(uuid.uuid4()),
                        first_name=tg_user.first_name,
                        username=tg_user.username,
                        language_code=DEFAULT_LANGUAGE,
                    )
                    logger.info(f"New user {user.tg_id} created with language {DEFAULT_LANGUAGE}.")

                data["user"] = user
                data["session"] = session
                data["is_new_user"] = is_new_user

                # Campaign attribution is an additional layer and never replaces
                # the normal Referral/Invite processing in the /start handler.
                text = getattr(event.event, "text", None) or ""
                parts = text.split(maxsplit=1)
                payload = parts[1].strip() if len(parts) == 2 and parts[0].lower() == "/start" else ""
                if payload.startswith(CAMPAIGN_PREFIX):
                    slug = payload[len(CAMPAIGN_PREFIX):].strip()
                    if slug:
                        campaign = await ChannelCampaignService.get_by_slug(session, slug)
                        if campaign and campaign.is_active_now():
                            joined_channel = False
                            try:
                                member = await event.event.bot.get_chat_member(campaign.channel_id, user.tg_id)
                                joined_channel = member.status not in {"left", "kicked"}
                            except Exception:
                                logger.debug(
                                    "Campaign channel membership check failed campaign=%s user=%s",
                                    campaign.id,
                                    user.tg_id,
                                    exc_info=True,
                                )
                            referral = await Referral.get_referral(session, user.tg_id)
                            await ChannelCampaignService.register_start(
                                session,
                                campaign,
                                user.tg_id,
                                referrer_id=referral.referrer_tg_id if referral else None,
                                joined_channel=joined_channel,
                            )
                            data["campaign"] = campaign
            else:
                logger.debug("No user found in event data.")

            return await handler(event, data)
