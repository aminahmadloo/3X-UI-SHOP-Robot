from __future__ import annotations

from urllib.parse import quote

from app.bot.routers.my_services import auto_connect, handler as my_services_handler
from app.bot.services.notification import NotificationService
from app.bot.utils.constants import MESSAGE_EFFECT_IDS
from app.bot.utils.navigation import NavSubscription

# Keep the existing My Services and payment handlers intact. This module only
# attaches the new router/middleware and replaces the purchase-success keyboard
# with the subscription-aware version.
auto_connect.NavSubscription = NavSubscription

# NekoBox uses the Clash-compatible import scheme for subscription deep links.
auto_connect.CLIENTS["android"]["nekobox"] = "NekoBox"
_original_deep_link = auto_connect._client_deep_link


def _deep_link_with_nekobox(client: str, subscription_url: str, name: str) -> str | None:
    if client == "nekobox":
        encoded_url = quote(subscription_url, safe="")
        encoded_name = quote(name or "ToonelVPN", safe="")
        return f"clash://install-config?url={encoded_url}&name={encoded_name}"
    return _original_deep_link(client, subscription_url, name)


auto_connect._client_deep_link = _deep_link_with_nekobox

if auto_connect.router not in my_services_handler.router.sub_routers:
    my_services_handler.router.include_router(auto_connect.router)

if not getattr(my_services_handler.router, "_auto_connect_keyboard_middleware", False):
    my_services_handler.router.callback_query.outer_middleware(
        auto_connect.MyServicesDetailsKeyboardMiddleware()
    )
    setattr(my_services_handler.router, "_auto_connect_keyboard_middleware", True)

if not getattr(NotificationService, "_auto_connect_purchase_success_patch", False):

    async def notify_purchase_success_with_auto_connect(
        self,
        user_id: int,
        key: str,
        message_effect_id: str = MESSAGE_EFFECT_IDS["🎉"],
    ) -> None:
        await self.notify_by_id(
            chat_id=user_id,
            text=auto_connect._("payment:message:purchase_success").format(key=key),
            message_effect_id=message_effect_id,
            reply_markup=auto_connect.payment_success_keyboard_for_key(key),
        )

    NotificationService.notify_purchase_success = notify_purchase_success_with_auto_connect
    setattr(NotificationService, "_auto_connect_purchase_success_patch", True)
