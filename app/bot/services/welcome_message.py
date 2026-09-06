from html import escape

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, WelcomeMessageSettings


async def get_welcome_message(session: AsyncSession, user: User) -> str:
    """Return the current welcome-message template rendered for a user.

    The template is loaded from the database on every call so admin edits
    take effect without restarting the bot.
    """
    settings = await WelcomeMessageSettings.get_or_create(session)
    return settings.message.replace("{first_name}", escape(user.first_name or "کاربر"))
