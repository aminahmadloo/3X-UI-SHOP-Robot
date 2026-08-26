from aiogram import Dispatcher
from aiohttp.web import Application

from app.bot.utils.constants import CONNECTION_WEBHOOK

from . import (
    admin_tools,
    commands,
    custom_service,
    custom_service_card_payment,
    download,
    main_menu,
    managed_card_payment,
    misc,
    my_services,
    profile,
    referral,
    subscription,
    support,
    wallet,
)
from .admin_tools.card_payment_handler import router as card_payment_router
from .admin_tools.card_settings_handler import router as card_settings_router
from .admin_tools.wallet_amounts_handler import router as wallet_amounts_router
from .admin_tools.service_purchase_management_menu_handler import router as service_purchase_management_menu_router
from .admin_tools.dynamic_service_period_handler import router as dynamic_service_period_router
from .admin_tools.dynamic_renewal_management_handler import router as dynamic_renewal_admin_router
from .admin_tools.dynamic_traffic_addon_management_handler import router as dynamic_traffic_admin_router
from .admin_tools.server_handler import router as server_router
from .main_menu.renew_service_handler import router as main_menu_renewal_router
from .subscription.dynamic_service_purchase_handler import router as dynamic_service_purchase_router
from .wallet.gateway_payment import router as wallet_gateway_router


def include(app: Application, dispatcher: Dispatcher) -> None:
    app.router.add_get(CONNECTION_WEBHOOK, download.handler.redirect_to_connection)
    dispatcher.include_routers(
        misc.error_handler.router,
        misc.notification_handler.router,
        commands.router,
        custom_service_card_payment.router,
        managed_card_payment.router,
        custom_service.router,
        wallet_gateway_router,
        wallet.handler.router,
        my_services.client_control_handler.router,
        my_services.handler.router,
        main_menu_renewal_router,
        main_menu.handler.router,
        profile.handler.router,
        referral.handler.router,
        support.handler.router,
        download.handler.router,
        dynamic_service_purchase_router,
        subscription.renewal_handler.router,
        subscription.subscription_handler.router,
        subscription.payment_handler.router,
        subscription.promocode_handler.router,
        subscription.trial_handler.router,
        subscription.wallet_payment.router,
        service_purchase_management_menu_router,
        dynamic_renewal_admin_router,
        dynamic_service_period_router,
        dynamic_traffic_admin_router,
        server_router,
        admin_tools.admin_tools_handler.router,
        admin_tools.backup_handler.router,
        admin_tools.inbound_management_handler.router,
        admin_tools.invites_handler.router,
        admin_tools.maintenance_handler.router,
        admin_tools.notification_handler.router,
        admin_tools.promocode_handler.router,
        admin_tools.restart_handler.router,
        admin_tools.client_control_settings_handler.router,
        admin_tools.subscription_settings_handler.router,
        admin_tools.statistics_handler.router,
        admin_tools.user_handler.router,
        card_payment_router,
        card_settings_router,
        wallet_amounts_router,
    )
