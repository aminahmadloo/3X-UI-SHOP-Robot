import asyncio
import logging
from urllib.parse import urljoin

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.types import MenuButtonWebApp, WebAppInfo
from aiogram.utils.i18n import I18n
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp.web import Application, _run_app
from redis.asyncio.client import Redis

from app import logger
from app.bot import filters, middlewares, routers, services, tasks
from app.bot.middlewares import MaintenanceMiddleware
from app.bot.models import ServicesContainer
from app.bot.payment_gateways import GatewayFactory
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

    # Mini App is admin-only for now. Configure Telegram's native chat menu
    # button per admin instead of exposing a duplicate inline button in the
    # bot's main menu. Customer rollout can later switch this to a global menu.
    mini_app_domain = config.bot.DOMAIN.strip().rstrip("/")
    if mini_app_domain:
        if not mini_app_domain.startswith(("http://", "https://")):
            mini_app_domain = f"https://{mini_app_domain}"
        mini_app_url = f"{mini_app_domain}/miniapp"
        mini_app_menu = MenuButtonWebApp(
            text="Mini App",
            web_app=WebAppInfo(url=mini_app_url),
        )
        for admin_id in config.bot.ADMINS:
            try:
                await bot.set_chat_menu_button(
                    chat_id=int(admin_id),
                    menu_button=mini_app_menu,
                )
            except Exception:
                logging.exception("Failed to configure Mini App menu button for admin %s", admin_id)

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
    )
    I18n.set_current(i18n)
    services_container = await services.initialize(config=config, session=db.session, bot=bot)
    await services_container.server_pool.sync_servers()
    gateway_factory = GatewayFactory()
    gateway_factory.register_gateways(
        app=app,
        config=config,
        session=db.session,
        storage=storage,
        bot=bot,
        i18n=i18n,
        services=services_container,
    )
    dispatcher = Dispatcher(
        db=db,
        storage=storage,
        config=config,
        bot=bot,
        services=services_container,
        gateway_factory=gateway_factory,
        redis=storage.redis,
        i18n=i18n,
    )
    dispatcher.startup.register(on_startup)
    dispatcher.shutdown.register(on_shutdown)
    await MaintenanceMiddleware.load_from_database(db.session)
    middlewares.register(dispatcher=dispatcher, i18n=i18n, session=db.session)
    filters.register(
        dispatcher=dispatcher,
        developer_id=config.bot.DEV_ID,
        admins_ids=config.bot.ADMINS,
    )
    routers.include(app=app, dispatcher=dispatcher)
    register_mini_app(app=app, config=config, db=db, services=services_container, i18n=i18n)
    register_admin_management(app=app, config=config, db=db, services=services_container, i18n=i18n)
    await commands.setup(bot=bot)
    setup_application(app, dispatcher, bot=bot)
    await _run_app(
        app,
        host=DEFAULT_BOT_HOST,
        port=config.bot.PORT,
    )


if __name__ == "__main__":
    asyncio.run(main())
