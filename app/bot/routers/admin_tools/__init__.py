from . import (
    admin_tools_handler,
    backup_handler,
    client_control_settings_handler,
    customer_level_settings_handler,
    inbound_management_handler,
    invites_handler,
    maintenance_handler,
    notification_handler,
    promocode_handler,
    referral_settings_handler,
    restart_handler,
    server_handler,
    subscription_settings_handler,
    statistics_handler,
    user_handler,
)

# Install AI channel integration after the AI handler is registered. The
# integration removes its legacy duplicate channel:menu handler and extends
# the canonical channel publisher with safe semantic CTA resolution.
from . import ai_content_channel_integration  # noqa: E402,F401
