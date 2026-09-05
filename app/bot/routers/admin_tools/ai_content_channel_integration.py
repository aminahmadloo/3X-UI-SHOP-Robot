from __future__ import annotations

import os

from app.bot.services.channel_campaign import ChannelCampaignService
from app.bot.utils.navigation import (
    NavDownload,
    NavMain,
    NavProfile,
    NavReferral,
    NavSubscription,
    NavSupport,
)

CTA_CALLBACKS = {
    "BUY": NavSubscription.BUY.value,
    "MY_SERVICES": NavMain.MY_SERVICES.value,
    "RENEW": NavSubscription.RENEW_SERVICE.value,
    "WALLET": NavMain.WALLET.value,
    "ACCOUNT": NavProfile.MAIN.value,
    "LEVEL": NavMain.CUSTOMER_LEVEL.value,
    "REFERRAL": NavReferral.MAIN.value,
    "SUPPORT": NavSupport.MAIN.value,
    "GIFT": NavSubscription.GIFT_CODE.value,
    "DOWNLOAD": NavDownload.MAIN.value,
}
AI_ACTION_PREFIX = "ai-action://"
AI_MENU_BUTTON = "🤖 مدیریت محتوای AI"


def _patch_ai_settings() -> None:
    from app.bot.routers.admin_tools import ai_content_handler

    original_settings = ai_content_handler._settings
    if getattr(original_settings, "_ai_api_key", False):
        return

    async def settings(session):
        service, stored_settings = await original_settings(session)
        service.api_key = os.getenv("OPENAI_API_KEY")
        return service, stored_settings

    settings._ai_api_key = True
    ai_content_handler._settings = settings


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
        transformed: list[dict[str, str]] = []
        bot_username: str | None = None

        for item in (content.buttons or [])[:8]:
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
                    if campaign and campaign.channel_id == channel.id and campaign.is_active_now():
                        if bot_username is None:
                            bot_username = (await bot.get_me()).username
                        if bot_username:
                            transformed.append(
                                {
                                    "label": label,
                                    "url": ChannelCampaignService.build_link(bot_username, slug),
                                }
                            )
                continue

            # Preserve manually authored legacy URL buttons. AI-generated
            # content is restricted to semantic actions by AIContentService.
            if url.startswith(("https://", "http://", "tg://")):
                transformed.append({"label": label, "url": url})

        old_buttons = content.buttons
        channel_management.InlineKeyboardButton = patched_button
        try:
            content.buttons = transformed
            return await original_publish(bot, session, content, channel)
        finally:
            content.buttons = old_buttons
            channel_management.InlineKeyboardButton = original_button

    publish_content._ai_semantic_cta = True
    channel_management._publish_content = publish_content


def _patch_campaign_start() -> None:
    from app.bot.routers.main_menu import handler as main_menu

    for handler in main_menu.router.message.handlers:
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
                prefix = ChannelCampaignService.start_payload("")
                if payload.startswith(prefix):
                    slug = payload[len(prefix) :].strip()
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


def _patch_canonical_channel_menu() -> None:
    from app.bot.routers.admin_tools import channel_management_handler as channel_management

    original_menu = channel_management._menu
    if getattr(original_menu, "_ai_menu_extension", False):
        return

    def menu_with_ai(*args, **kwargs):
        markup = original_menu(*args, **kwargs)
        rows = list(markup.inline_keyboard)
        ai_row = [
            channel_management.InlineKeyboardButton(
                text=AI_MENU_BUTTON,
                callback_data="channel:ai_content",
            )
        ]
        insert_at = max(0, len(rows) - 1)
        rows.insert(insert_at, ai_row)
        return channel_management.InlineKeyboardMarkup(inline_keyboard=rows)

    menu_with_ai._ai_menu_extension = True
    channel_management._menu = menu_with_ai


def install() -> None:
    _patch_ai_settings()
    _remove_duplicate_channel_menu()
    _patch_canonical_channel_menu()
    _patch_publisher()
    _patch_campaign_start()


install()
