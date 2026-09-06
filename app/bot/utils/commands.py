import logging
import os

from aiogram import Bot
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    MenuButtonCommands,
    MenuButtonWebApp,
    WebAppInfo,
)

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


def _mini_app_url() -> str | None:
    domain = os.getenv("BOT_DOMAIN", "").strip().rstrip("/")
    if not domain:
        return None
    if not domain.startswith(("http://", "https://")):
        domain = f"https://{domain}"
    return f"{domain}/miniapp"


async def set_user_commands(bot: Bot, chat_id: int, language: str) -> None:
    """Set commands for one user, independent of Telegram app language."""
    await bot.set_my_commands(
        commands=_commands_for_language(language),
        scope=BotCommandScopeChat(chat_id=chat_id),
    )


async def _setup_mini_app_menu_button(bot: Bot, admin_ids: list[int]) -> None:
    """Expose Mini App in Telegram's native bottom chat menu for admins only."""
    url = _mini_app_url()
    if not url:
        logger.warning("BOT_DOMAIN is not configured; Mini App menu button was not configured.")
        return

    # Keep the default/private-chat menu as the normal command menu.
    await bot.set_chat_menu_button(menu_button=MenuButtonCommands(text="Menu"))

    # Override the menu button only for configured admins.
    for admin_id in admin_ids:
        await bot.set_chat_menu_button(
            chat_id=int(admin_id),
            menu_button=MenuButtonWebApp(
                text="Mini App",
                web_app=WebAppInfo(url=url),
            ),
        )

    logger.info("Mini App Telegram menu button configured for %d admin(s).", len(admin_ids))


async def setup(bot: Bot, admin_ids: list[int] | None = None) -> None:
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

    await _setup_mini_app_menu_button(bot, admin_ids or [])

    logger.info("Bot commands configured successfully with Persian as default.")


async def delete(bot: Bot) -> None:
    scope = BotCommandScopeAllPrivateChats()
    await bot.delete_my_commands(scope=scope)
    await bot.delete_my_commands(scope=scope, language_code="fa")
    await bot.delete_my_commands(scope=scope, language_code="en")
    await bot.delete_my_commands(scope=scope, language_code="ru")
    logger.info("Bot commands removed successfully.")
