from aiogram import Dispatcher
from aiohttp.web import Application

from app.bot.force_join import router as force_join_router
from app.bot.utils.constants import CONNECTION_WEBHOOK

from . import (
    admin_tools,
    advertising,
    commands,
    custom_service,
    custom_service_card_payment,
    download,
    main_menu,
    managed_card_payment,
    misc,
    my_services,
    payment_method_visibility,
    profile,
    referral,
    subscription,
    support,
    wallet,
)
from .admin_tools.ai_content_handler import router as ai_content_router
from .admin_tools import ai_content_daily_posts_handler  # noqa: F401
from .admin_tools.card_payment_handler import router as card_payment_router
from .admin_tools.card_settings_handler import router as card_settings_router
from .admin_tools.env_settings_enhancer import router as env_settings_enhancer_router
from .admin_tools.env_settings_handler import router as env_settings_router
from .admin_tools.gift_promocode_handler import router as gift_promocode_router
from .admin_tools.gift_reports_handler import router as gift_reports_router
from .admin_tools.multi_card_settings_handler import router as multi_card_settings_router
from .admin_tools.payment_gateway_settings_handler import router as payment_gateway_settings_router
from .admin_tools.blupal_settings_handler import router as blupal_settings_router
from .admin_tools.variza_settings_handler import router as variza_settings_router
from .admin_tools.wallet_amounts_handler import router as wallet_amounts_router
from .admin_tools.service_purchase_management_menu_handler import router as service_purchase_management_menu_router
from .admin_tools.dynamic_service_period_handler import router as dynamic_service_period_router
from .admin_tools.dynamic_renewal_management_handler import router as dynamic_renewal_admin_router
from .admin_tools.dynamic_traffic_addon_management_handler import router as dynamic_traffic_admin_router
from .admin_tools.server_handler import router as server_router
from .admin_tools.referral_settings_handler import router as referral_settings_router
from .admin_tools.test_account_settings_handler import router as test_account_settings_router
from .admin_tools.advertising_management_extra_handler import router as advertising_management_extra_router
from .admin_tools.advertising_management_callbacks_fix_handler import router as advertising_management_callbacks_fix_router
from .admin_tools.advertising_management_handler import router as advertising_management_router
from .admin_tools.advertising_publication_status_handler import router as advertising_publication_status_router
from .admin_tools.advertising_builder_handler import router as advertising_admin_router
from .admin_tools.advertising_cancel_handler import router as advertising_cancel_router
from .admin_tools.channel_campaign_handler import router as channel_campaign_router
from .admin_tools.channel_menu_campaigns import router as channel_menu_campaigns_router
from .admin_tools.channel_management_handler import router as channel_management_router
from .admin_tools.channel_management_extras import router as channel_management_extras_router
from .admin_tools.channel_management_v2 import router as channel_management_v2_router
from .gift_service_handler import router as gift_service_router
from .main_menu.renew_service_handler import router as main_menu_renewal_router
from .main_menu.renewal_aban_payment_fix import router as main_menu_renewal_aban_payment_fix_router
from .multi_card_payment import router as multi_card_payment_router
from .multi_card_service_receipt import router as multi_card_service_receipt_router
from .multi_card_wallet_receipt import router as multi_card_wallet_receipt_router
from .subscription.dynamic_service_purchase_handler import router as dynamic_service_purchase_router
from .subscription.managed_payment_compat_handler import router as managed_payment_compat_router
from .subscription.wallet_payment import router as subscription_wallet_payment_router
from .wallet.aban_payment_fix import router as wallet_aban_payment_fix_router
from .wallet.gateway_payment import router as wallet_gateway_router
from .wallet.overview import router as wallet_overview_router
from app.bot.routers.customer_level.handler import router as customer_level_router
from app.bot.routers.support.training_handler import router as support_training_router
from .special_offer_handler import router as special_offer_router
from .special_offer_runtime_fixes import router as special_offer_runtime_fixes_router
from .special_offer_input_guard import router as special_offer_input_guard_router
from .special_offer_campaign_rename_v2 import router as special_offer_campaign_rename_router
from .variza_payment_handler import router as variza_payment_router
from .blupal_smart_card_payment import router as blupal_smart_card_payment_router

from . import payment_method_visibility as _payment_method_visibility
from . import variza_integration as _variza_integration
from . import blupal_smart_card_payment as _blupal_smart_card_payment
from . import blupal_smart_card_compat as _blupal_smart_card_compat

_variza_integration.install()
_blupal_smart_card_payment.install()


def include(app: Application, dispatcher: Dispatcher) -> None:
    app.router.add_get(CONNECTION_WEBHOOK, download.handler.redirect_to_connection)
    dispatcher.include_routers(
        misc.error_handler.router,
        misc.notification_handler.router,
        force_join_router,
        advertising.router,
        commands.router,
        blupal_smart_card_payment_router,
        multi_card_wallet_receipt_router,
        multi_card_service_receipt_router,
        managed_card_payment.router,
        multi_card_payment_router,
        custom_service_card_payment.router,
        custom_service.router,
        wallet_aban_payment_fix_router,
        wallet_gateway_router,
        wallet_overview_router,
        wallet.handler.router,
        gift_service_router,
        my_services.client_control_handler.router,
        my_services.handler.router,
        main_menu_renewal_aban_payment_fix_router,
        main_menu_renewal_router,
        special_offer_input_guard_router,
        special_offer_runtime_fixes_router,
        special_offer_router,
        main_menu.handler.router,
        profile.handler.router,
        referral.handler.router,
        customer_level_router,
        support_training_router,
        support.handler.router,
        download.handler.router,
        dynamic_service_purchase_router,
        subscription.renewal_handler.router,
        subscription.subscription_handler.router,
        variza_payment_router,
        subscription.payment_handler.router,
        subscription.promocode_handler.router,
        subscription.trial_handler.router,
        subscription.wallet_payment.router,
        service_purchase_management_menu_router,
        managed_payment_compat_router,
        dynamic_renewal_admin_router,
        dynamic_service_period_router,
        dynamic_traffic_admin_router,
        server_router,
        gift_promocode_router,
        gift_reports_router,
        env_settings_enhancer_router,
        env_settings_router,
        test_account_settings_router,
        advertising_management_extra_router,
        advertising_management_callbacks_fix_router,
        advertising_management_router,
        advertising_publication_status_router,
        advertising_cancel_router,
        advertising_admin_router,
        channel_menu_campaigns_router,
        channel_campaign_router,
        ai_content_router,
        channel_management_router,
        channel_management_extras_router,
        channel_management_v2_router,
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
        admin_tools.customer_level_settings_handler.router,
        referral_settings_router,
        card_payment_router,
        multi_card_settings_router,
        card_settings_router,
        variza_settings_router,
        payment_gateway_settings_router,
        blupal_settings_router,
        wallet_amounts_router,
    )
