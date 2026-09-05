from __future__ import annotations

from aiogram.types import InlineKeyboardButton

from app.bot.services.channel_campaign import ChannelCampaignService
from app.bot.utils.navigation import NavDownload, NavMain, NavProfile, NavReferral, NavSubscription, NavSupport

CTA_CALLBACKS = {
    "BUY": NavSubscription.BUY.value,
    "MY_SERVICES": NavMain.MY_SERVICES.value,
    "RENEW": "main_menu:renew_service",
    "WALLET": NavMain.WALLET.value,
    "ACCOUNT": NavProfile.MAIN.value,
    "LEVEL": NavMain.CUSTOMER_LEVEL.value,
    "REFERRAL": NavReferral.MAIN.value,
    "SUPPORT": NavSupport.MAIN.value,
    "GIFT": NavSubscription.GIFT_CODE.value,
    "DOWNLOAD": NavDownload.MAIN.value,
}
AI_ACTION_PREFIX = "ai-action://"


def _patch_publisher() -> None:
    from app.bot.routers.admin_tools import channel_management_handler as channel_management

    original_publish = channel_management._publish_content
    original_button = channel_management.InlineKeyboardButton

    if getattr(original_publish, "_ai_semantic_cta", False):
        return

    def patched_button(*args, **kwargs):
        url = kwargs.get("url")
        if isinstance(url, str) and url.startswith(AI_ACTION_PREFIX):
            kwargs.pop("url", None)
            kwargs["callback_data"] = url[len(AI_ACTION_PREFIX) :]
        return original_button(*args, **kwargs)

    async def publish_content(bot, session, content, channel):
        buttons = content.buttons or []
        transformed: list[dict[str, str]] = []
        bot_username: str | None = None

        for item in buttons[:8]:
            if not isinstance(item, dict):
                continue
            label = str(item.get("label") or "لینک").strip()[:64]
            action = str(item.get("action") or "").strip().upper()
            url = str(item.get("url") or "").strip()
            if not label:
                continue

            callback_data = CTA_CALLBACKS.get(action)
            if callback_data:
                transformed.append({"label": label, "url": f"{AI_ACTION_PREFIX}{callback_data}"})
                continue

            if action.startswith("CAMPAIGN:"):
                slug = action[len("CAMPAIGN:") :].strip()
                if slug:
                    campaign = await ChannelCampaignService.get_by_slug(session, slug)
                    if campaign and campaign.channel_id == channel.chat_id and campaign.is_active_now():
                        if bot_username is None:
                            bot_username = (await bot.get_me()).username
                        if bot_username:
                            transformed.append(
                                {"label": label, "url": ChannelCampaignService.build_link(bot_username, slug)}
                            )
                continue

            # Preserve manually authored legacy URL buttons. AI-generated
            # content never receives raw URLs from the AI service.
            if url.startswith(("https://", "http://", "tg://")):
                transformed.append({"label": label, "url": url})

        old_buttons = content.buttons
        channel_management.InlineKeyboardButton = patched_button
        try:
            content.buttons = transformed
            return await original_publish(bot, session, content, channel)
        finally:
            content.buttons = old_buttons
            channel_management.InlineKeyboardButton = patched_button

    publish_content._ai_semantic_cta = True
    channel_management._publish_content = publish_content


def _patch_campaign_start() -> None:
    from app.bot.routers.main_menu import handler as main_menu

    observer = main_menu.router.message
    for handler in observer.handlers:
        callback = getattr(handler, "callback", None)
        if getattr(callback, "__name__", "") != "command_main_menu":
            continue
        if getattr(callback, "_ai_campaign_start", False):
            return

        original = callback

        async def wrapped(*args, **kwargs):
            command = kwargs.get("command")
            session = kwargs.get("session")
            user = kwargs.get("user")
            if command and command.args and session and user:
                payload = command.args.strip()
                if payload.startswith(ChannelCampaignService.start_payload("")):
                    slug = payload[len(ChannelCampaignService.start_payload("")) :].strip()
                    campaign = await ChannelCampaignService.get_by_slug(session, slug)
                    if campaign and campaign.is_active_now():
                        await ChannelCampaignService.register_start(
                            session,
                            campaign,
                            user.tg_id,
                            referrer_id=None,
                            joined_channel=False,
                            source="campaign",
                        )
                        # Let the existing /start flow render the normal main
                        # menu, but prevent it from treating campaign_<slug>
                        # as an invite hash.
                        command.args = None
            return await original(*args, **kwargs)

        wrapped._ai_campaign_start = True
        handler.callback = wrapped
        return


def _remove_duplicate_channel_menu() -> None:
    from app.bot.routers.admin_tools import ai_content_handler

    observer = ai_content_handler.router.callback_query
    observer.handlers[:] = [
        handler
        for handler in observer.handlers
        if getattr(handler.callback, "__name__", "") != "channel_menu_with_ai"
    ]


def install() -> None:
    _remove_duplicate_channel_menu()
    _patch_publisher()
    _patch_campaign_start()


install()
