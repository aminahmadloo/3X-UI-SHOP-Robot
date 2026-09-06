import logging

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats, BotCommandScopeChat

from .navigation import NavMain

logger = logging.getLogger(__name__)


def _commands_for_language(language: str) -> list[BotCommand]:
    commands = {
        "fa": [
            BotCommand(command=NavMain.START, description="🏠 منوی اصلی"),
            BotCommand(command="profile", description="👤 پروفایل من"),
            BotCommand(command="subscription", description="📦 سرویس من"),
            BotCommand(command="download", description="📲 راهنمای اتصال"),
            BotCommand(command="referral", description="🎁 دعوت دوستان"),
            BotCommand(command="support", description="🎧 پشتیبانی"),
        ],
        "en": [
            BotCommand(command=NavMain.START, description="🏠 Main menu"),
            BotCommand(command="profile", description="👤 My profile"),
            BotCommand(command="subscription", description="📦 My subscription"),
            BotCommand(command="download", description="📲 Connection guide"),
            BotCommand(command="referral", description="🎁 Invite friends"),
            BotCommand(command="support", description="🎧 Support"),
        ],
        "ru": [
            BotCommand(command=NavMain.START, description="🏠 Главное меню"),
            BotCommand(command="profile", description="👤 Мой профиль"),
            BotCommand(command="subscription", description="📦 Моя подписка"),
            BotCommand(command="download", description="📲 Как подключиться"),
            BotCommand(command="referral", description="🎁 Пригласить друзей"),
            BotCommand(command="support", description="🎧 Поддержка"),
        ],
    }
    return commands.get(language, commands["fa"])


async def set_user_commands(bot: Bot, chat_id: int, language: str) -> None:
    """Set commands for one user, independent of Telegram app language."""
    await bot.set_my_commands(
        commands=_commands_for_language(language),
        scope=BotCommandScopeChat(chat_id=chat_id),
    )


async def setup(bot: Bot) -> None:
    # Persian is the default for everyone. Do not use Telegram's app language
    # to select English/Russian automatically; users choose their language in
    # the bot and then receive a chat-specific command menu.
    scope = BotCommandScopeAllPrivateChats()
    await bot.set_my_commands(commands=_commands_for_language("fa"), scope=scope)

    # Remove old language-specific global scopes created by previous versions.
    await bot.delete_my_commands(scope=scope, language_code="fa")
    await bot.delete_my_commands(scope=scope, language_code="en")
    await bot.delete_my_commands(scope=scope, language_code="ru")
    await bot.set_my_commands(commands=_commands_for_language("fa"), scope=scope)

    logger.info("Bot commands configured successfully with Persian as default.")


async def delete(bot: Bot) -> None:
    scope = BotCommandScopeAllPrivateChats()
    await bot.delete_my_commands(scope=scope)
    await bot.delete_my_commands(scope=scope, language_code="fa")
    await bot.delete_my_commands(scope=scope, language_code="en")
    await bot.delete_my_commands(scope=scope, language_code="ru")
    logger.info("Bot commands removed successfully.")
