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
    system_health_handler,
    system_health_backup_handler,
    network_health_admin_ui,
    full_backup_handler,
)

# Install AI channel integration after the AI handler is registered. The
# integration removes its legacy duplicate channel:menu handler and extends
# the canonical channel publisher with safe semantic CTA resolution.
from . import ai_content_channel_integration  # noqa: E402,F401

# Extend server and service-inbound administration with the same
# multi-server/multi-node topology used by System Health. This module is
# intentionally loaded after the legacy handlers so it can safely replace
# only their keyboards and add dedicated topology callbacks.
from . import admin_topology_management  # noqa: E402,F401

# Install System Health severity handling after the health handlers/classes
# are imported. Historical Telegram webhook errors become warnings instead
# of falsely marking the whole system critical.
from app.bot.services import health_severity  # noqa: E402,F401
