import logging

from aiogram import Bot
from aiogram.types import BotCommand, BotCommandScopeAllPrivateChats

from .navigation import NavMain

logger = logging.getLogger(__name__)


async def setup(bot: Bot) -> None:
    scope = BotCommandScopeAllPrivateChats()

    fa_commands = [
        BotCommand(command=NavMain.START, description="🏠 منوی اصلی"),
        BotCommand(command="profile", description="👤 پروفایل من"),
        BotCommand(command="subscription", description="📦 سرویس من"),
        BotCommand(command="download", description="📲 راهنمای اتصال"),
        BotCommand(command="referral", description="🎁 دعوت دوستان"),
        BotCommand(command="support", description="🎧 پشتیبانی"),
    ]

    en_commands = [
        BotCommand(command=NavMain.START, description="🏠 Main menu"),
        BotCommand(command="profile", description="👤 My profile"),
        BotCommand(command="subscription", description="📦 My subscription"),
        BotCommand(command="download", description="📲 Connection guide"),
        BotCommand(command="referral", description="🎁 Invite friends"),
        BotCommand(command="support", description="🎧 Support"),
    ]

    ru_commands = [
        BotCommand(command=NavMain.START, description="🏠 Главное меню"),
        BotCommand(command="profile", description="👤 Мой профиль"),
        BotCommand(command="subscription", description="📦 Моя подписка"),
        BotCommand(command="download", description="📲 Как подключиться"),
        BotCommand(command="referral", description="🎁 Пригласить друзей"),
        BotCommand(command="support", description="🎧 Поддержка"),
    ]

    await bot.set_my_commands(commands=fa_commands, scope=scope)
    await bot.set_my_commands(commands=fa_commands, scope=scope, language_code="fa")
    await bot.set_my_commands(commands=en_commands, scope=scope, language_code="en")
    await bot.set_my_commands(commands=ru_commands, scope=scope, language_code="ru")

    logger.info("Bot commands configured successfully.")


async def delete(bot: Bot) -> None:
    await bot.delete_my_commands(
        scope=BotCommandScopeAllPrivateChats(),
    )
    logger.info("Bot commands removed successfully.")
