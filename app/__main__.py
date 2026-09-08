import asyncio
import logging
from urllib.parse import urljoin

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import MenuButtonDefault
from aiogram.utils.i18n import I18n
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp.web import Application, _run_app
from redis.asyncio.client import Redis

from app import logger
from app.bot import filters, middlewares, routers, services, tasks
from app.bot.middlewares import MaintenanceMiddleware
from app.bot.models import ServicesContainer
from app.bot.payment_gateways import GatewayFactory
from app.bot.payment_gateways.variza_gateway import VarizaGateway
from app.bot.utils import commands
from app.bot.utils.constants import (
    BOT_STARTED_TAG,
    BOT_STOPPED_TAG,
    DEFAULT_LANGUAGE,
    I18N_DOMAIN,
    TELEGRAM_WEBHOOK,
)
from app.config import DEFAULT_BOT_HOST, DEFAULT_LOCALES_DIR, Config, load_config
from app.db.database import Database
from app.mini_app import register as register_mini_app
from app.miniapp.admin_management import register_admin_management


async def on_shutdown(db: Database, bot: Bot, services: ServicesContainer) -> None:
    await services.notification.notify_developer(BOT_STOPPED_TAG)
    await commands.delete(bot)
    await bot.delete_webhook()
    await bot.session.close()
    await db.close()
    logging.info("Bot stopped.")


async def on_startup(
    config: Config,
    bot: Bot,
    services: ServicesContainer,
    db: Database,
    redis: Redis,
    i18n: I18n,
) -> None:
    webhook_url = urljoin(config.bot.DOMAIN, TELEGRAM_WEBHOOK)

    if await bot.get_webhook_info() != webhook_url:
        await bot.set_webhook(webhook_url)

    current_webhook = await bot.get_webhook_info()
    logging.info(f"Current webhook URL: {current_webhook.url}")

    # Clear any legacy per-admin Mini App menu-button override.
    # BotFather remains the source of truth for the bot-wide menu button.
    for admin_id in config.bot.ADMINS:
        try:
            await bot.set_chat_menu_button(
                chat_id=int(admin_id),
                menu_button=MenuButtonDefault(),
            )
        except Exception:
            logging.exception("Failed to reset Mini App menu button for admin %s", admin_id)

    await services.notification.notify_developer(BOT_STARTED_TAG)
    logging.info("Bot started.")

    tasks.transactions.start_scheduler(db.session)
    if config.shop.REFERRER_REWARD_ENABLED:
        tasks.referral.start_scheduler(
            session_factory=db.session, referral_service=services.referral
        )
    tasks.subscription_expiry.start_scheduler(
        session_factory=db.session,
        redis=redis,
        i18n=i18n,
        vpn_service=services.vpn,
        notification_service=services.notification,
    )
    await tasks.test_account_cleanup.start_scheduler(services.test_account)
    tasks.channel_content.start_scheduler(session_factory=db.session, bot=bot)
    tasks.channel_analytics.start_scheduler(session_factory=db.session, bot=bot)
    tasks.ai_content.start_scheduler(session_factory=db.session)


async def main() -> None:
    app = Application()
    config = load_config()
    logger.setup_logging(config.logging)
    db = Database(config.database)
    await db.initialize()
    storage = RedisStorage.from_url(url=config.redis.url())
    bot = Bot(
        token=config.bot.TOKEN,
        default=DefaultBotProperties(
            parse_mode=ParseMode.HTML, link_preview_is_disabled=True
        ),
    )
    i18n = I18n(
        path=DEFAULT_LOCALES_DIR,
        default_locale=DEFAULT_LANGUAGE,
        domain=I18N_DOMAIN,
