import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.routers.admin_tools.advertising_builder_handler import build_ad_markup, save_draft
from app.bot.states.advertising import AdvertisingStates
from app.db.models import AdvertisingCampaign, AdvertisingChannel, AdvertisingPublication, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)

DESTINATION_LABELS = {
    "channels": "📢 کانال/کانال‌های رسمی",
    "bot": "🤖 ربات",
    "home": "🏠 صفحه اصلی ربات",
    "notification": "🔔 اطلاعیه ربات",
    "users": "👥 کاربران ربات",
}
REAL_DESTINATIONS = {"channels", "home", "notification", "users"}


def _checked(target: str, selected: set[str]) -> bool:
    if target == "bot":
        return "users" in selected and "notification" in selected
    return target in selected


def destination_keyboard(selected: set[str]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for target in ("channels", "bot", "home", "notification", "users"):
        mark = "☑️" if _checked(target, selected) else "☐"
        b.row(InlineKeyboardButton(text=f"{mark} {DESTINATION_LABELS[target]}", callback_data=f"advertising:destination:toggle:{target}"))
    if "channels" in selected:
        b.row(InlineKeyboardButton(text="📋 انتخاب کانال‌های رسمی", callback_data="advertising:destination:channels"))
    b.row(InlineKeyboardButton(text="🚀 تأیید و انتشار", callback_data="advertising:destination:publish"))
    b.row(InlineKeyboardButton(text="❌ لغو", callback_data="advertising:destination:cancel"))
    return b.as_markup()


def channel_selection_keyboard(channels: list[AdvertisingChannel], selected_ids: set[int]) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    for channel in channels:
        mark = "☑️" if channel.id in selected_ids else "☐"
        b.row(InlineKeyboardButton(text=f"{mark} {channel.title[:48]}", callback_data=f"advertising:destination:channel:{channel.id}"))
    b.row(InlineKeyboardButton(text="✅ بازگشت به مقصد انتشار", callback_data="advertising:destination:channels_done"))
    b.row(InlineKeyboardButton(text="❌ لغو", callback_data="advertising:destination:cancel"))
    return b.as_markup()


async def _get_active_home_campaign(session: AsyncSession) -> AdvertisingCampaign | None:
    campaigns = list((await session.execute(select(AdvertisingCampaign).where(AdvertisingCampaign.is_active.is_(True)).order_by(AdvertisingCampaign.id.desc()))).scalars().all())
    for campaign in campaigns:
        if "home" in campaign.publication_targets:
            return campaign
    return None


async def send_campaign_content(bot, chat_id: int, campaign: AdvertisingCampaign, session: AsyncSession, *, channel_id: int = 0):
    markup = await build_ad_markup(campaign.id, campaign.bot_username or "", channel_id, session, campaign.custom_buttons, campaign.selected_offers, campaign.show_services)
    if campaign.content_type == "photo":
        return await bot.send_photo(chat_id=chat_id, photo=campaign.media_file_id, caption=campaign.body or None, show_caption_above_media=campaign.show_caption_above_media, reply_markup=markup)
    if campaign.content_type == "video":
        return await bot.send_video(chat_id=chat_id, video=campaign.media_file_id, caption=campaign.body or None, show_caption_above_media=campaign.show_caption_above_media, reply_markup=markup)
    return await bot.send_message(chat_id=chat_id, text=campaign.body, reply_markup=markup)


async def _edit_or_replace_home(callback: CallbackQuery, campaign: AdvertisingCampaign, session: AsyncSession, state: FSMContext) -> None:
    markup = await build_ad_markup(campaign.id, campaign.bot_username or "", 0, session, campaign.custom_buttons, campaign.selected_offers, campaign.show_services)
    if campaign.content_type == "text":
        await callback.message.edit_text(campaign.body, reply_markup=markup)
        await state.update_data(main_message_id=callback.message.message_id)
        return
    try:
        if campaign.content_type == "photo":
            media = InputMediaPhoto(media=campaign.media_file_id, caption=campaign.body or None, show_caption_above_media=campaign.show_caption_above_media)
        else:
            media = InputMediaVideo(media=campaign.media_file_id, caption=campaign.body or None, show_caption_above_media=campaign.show_caption_above_media)
        await callback.message.edit_media(media=media, reply_markup=markup)
        await state.update_data(main_message_id=callback.message.message_id)
    except Exception:
        try:
            await callback.message.delete()
        except Exception:
            pass
        sent = await send_campaign_content(callback.bot, callback.message.chat.id, campaign, session)
        await state.update_data(main_message_id=sent.message_id)


@router.callback_query(F.data == "advertising:create", IsAdmin())
async def destination_aware_create_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.update_data(custom_buttons=[], selected_offers=[], show_services=True, content_type="text", media_file_id=None, show_caption_above_media=False)
    await state.set_state(AdvertisingStates.waiting_campaign_title)
    await callback.answer()
    await callback.message.edit_text(
        "🧩 <b>سازنده تبلیغ</b>\n\n<b>مرحله ۱/۵</b> — عنوان داخلی کمپین را ارسال کنید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ لغو", callback_data="advertising:cancel")]]),
    )


@router.callback_query(F.data == "advertising:preview", IsAdmin())
async def preview_to_destinations(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    if not data.get("campaign_title") or data.get("campaign_body") is None:
        await callback.answer("اطلاعات کمپین ناقص است.", show_alert=True)
        return
    try:
        me = await callback.bot.get_me()
        campaign = await save_draft(session, data, me.username or "")
        await session.commit()
    except Exception as exc:
        await session.rollback()
        logger.exception("Failed to save advertising campaign draft: %s", exc)
        await callback.answer("ذخیره کمپین ناموفق بود.", show_alert=True)
        return
    await state.update_data(destination_campaign_id=campaign.id, publication_targets=[], publication_channel_ids=[])
    await state.set_state(AdvertisingStates.waiting_publication_destinations)
    await callback.answer()
    await callback.message.edit_text(
        f"👁 <b>پیش‌نمایش کمپین #{campaign.id} آماده است.</b>\n\n🎯 <b>مقصد انتشار را انتخاب کنید:</b>",
        reply_markup=destination_keyboard(set()),
    )


@router.callback_query(F.data.regexp(r"^advertising:destination:toggle:(channels|bot|home|notification|users)$"), AdvertisingStates.waiting_publication_destinations, IsAdmin())
async def toggle_destination(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    target = callback.data.rsplit(":", 1)[1]
    data = await state.get_data()
    selected = set(data.get("publication_targets", []))
    if target == "bot":
        if "users" in selected and "notification" in selected:
            selected.difference_update({"users", "notification"})
        else:
            selected.update({"users", "notification"})
    elif target in REAL_DESTINATIONS:
        if target in selected:
            selected.remove(target)
        else:
            selected.add(target)
    channel_ids = {int(item) for item in data.get("publication_channel_ids", []) if str(item).isdigit()}
    if "channels" in selected and not channel_ids:
        channel_ids = {channel.id for channel in await AdvertisingChannel.list_active(session)}
    if "channels" not in selected:
        channel_ids.clear()
    await state.update_data(publication_targets=sorted(selected), publication_channel_ids=sorted(channel_ids))
    await callback.answer("مقصد به‌روزرسانی شد")
    await callback.message.edit_reply_markup(reply_markup=destination_keyboard(selected))


@router.callback_query(F.data == "advertising:destination:channels", AdvertisingStates.waiting_publication_destinations, IsAdmin())
async def open_channel_selection(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    selected = {int(item) for item in data.get("publication_channel_ids", []) if str(item).isdigit()}
    channels = await AdvertisingChannel.list_active(session)
    if not channels:
        await callback.answer("هیچ کانال فعالی وجود ندارد.", show_alert=True)
        return
    await state.set_state(AdvertisingStates.waiting_publication_channels)
    await callback.answer()
    await callback.message.edit_text("📢 <b>کانال‌های رسمی مقصد</b>\n\nیک یا چند کانال فعال را انتخاب کن:", reply_markup=channel_selection_keyboard(channels, selected))


@router.callback_query(F.data.regexp(r"^advertising:destination:channel:\d+$"), AdvertisingStates.waiting_publication_channels, IsAdmin())
async def toggle_publication_channel(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    channel_id = int(callback.data.rsplit(":", 1)[1])
    channel = await session.get(AdvertisingChannel, channel_id)
    if not channel or not channel.is_active:
        await callback.answer("کانال فعال نیست.", show_alert=True)
        return
    data = await state.get_data()
    selected = {int(item) for item in data.get("publication_channel_ids", []) if str(item).isdigit()}
    if channel_id in selected:
        selected.remove(channel_id)
    else:
        selected.add(channel_id)
    await state.update_data(publication_channel_ids=sorted(selected))
    await callback.answer("انتخاب کانال به‌روزرسانی شد")
    await callback.message.edit_reply_markup(reply_markup=channel_selection_keyboard(await AdvertisingChannel.list_active(session), selected))


@router.callback_query(F.data == "advertising:destination:channels_done", AdvertisingStates.waiting_publication_channels, IsAdmin())
async def finish_channel_selection(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected = set(data.get("publication_targets", []))
    channel_ids = [int(item) for item in data.get("publication_channel_ids", []) if str(item).isdigit()]
    if channel_ids:
        selected.add("channels")
    else:
        selected.discard("channels")
    await state.update_data(publication_targets=sorted(selected), publication_channel_ids=sorted(channel_ids))
    await state.set_state(AdvertisingStates.waiting_publication_destinations)
    await callback.answer()
    await callback.message.edit_text("🎯 <b>مقصد انتشار:</b>", reply_markup=destination_keyboard(selected))


async def _publish_to_channels(campaign: AdvertisingCampaign, channel_ids: list[int], bot, session: AsyncSession) -> tuple[int, int]:
    sent_count = failed_count = 0
    for channel_id in channel_ids:
        channel = await session.get(AdvertisingChannel, channel_id)
        if not channel or not channel.is_active:
            continue
        try:
            sent = await send_campaign_content(bot, channel.chat_id, campaign, session, channel_id=channel.id)
            session.add(AdvertisingPublication(campaign_id=campaign.id, channel_id=channel.id, message_id=sent.message_id, is_active=True))
            sent_count += 1
        except Exception as exc:
            failed_count += 1
            logger.warning("Advertising channel publication failed campaign=%s channel=%s: %s", campaign.id, channel.chat_id, exc)
    return sent_count, failed_count


async def _publish_to_users(campaign: AdvertisingCampaign, bot, session: AsyncSession) -> tuple[int, int]:
    sent_count = failed_count = 0
    for user in await User.get_all(session=session):
        try:
            await send_campaign_content(bot, user.tg_id, campaign, session, channel_id=0)
            sent_count += 1
        except Exception as exc:
            failed_count += 1
            logger.warning("Advertising user publication failed campaign=%s user=%s: %s", campaign.id, user.tg_id, exc)
    return sent_count, failed_count


async def _publish_to_notifications(campaign: AdvertisingCampaign, bot, session: AsyncSession) -> tuple[int, int]:
    sent_count = failed_count = 0
    for user in await User.get_all(session=session):
        try:
            await send_campaign_content(bot, user.tg_id, campaign, session, channel_id=0)
            sent_count += 1
        except Exception as exc:
            failed_count += 1
            logger.warning("Advertising notification publication failed campaign=%s user=%s: %s", campaign.id, user.tg_id, exc)
    return sent_count, failed_count


@router.callback_query(F.data == "advertising:destination:publish", AdvertisingStates.waiting_publication_destinations, IsAdmin())
async def publish_destinations(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    campaign = await session.get(AdvertisingCampaign, int(data.get("destination_campaign_id", 0)))
    if not campaign:
        await state.clear()
        await callback.answer("کمپین پیدا نشد.", show_alert=True)
        return
    selected = set(data.get("publication_targets", []))
    channel_ids = [int(item) for item in data.get("publication_channel_ids", []) if str(item).isdigit()]
    if "channels" in selected and not channel_ids:
        await callback.answer("حداقل یک کانال رسمی انتخاب کن.", show_alert=True)
        return
    if not selected:
        await callback.answer("حداقل یک مقصد را انتخاب کن.", show_alert=True)
        return
    campaign.publication_targets = [*sorted(selected), *[f"channel:{channel_id}" for channel_id in sorted(channel_ids)]]
    await session.commit()
    channel_sent = channel_failed = users_sent = users_failed = notification_sent = notification_failed = 0
    if "channels" in selected:
        channel_sent, channel_failed = await _publish_to_channels(campaign, channel_ids, callback.bot, session)
    if "users" in selected:
        users_sent, users_failed = await _publish_to_users(campaign, callback.bot, session)
    if "notification" in selected:
        notification_sent, notification_failed = await _publish_to_notifications(campaign, callback.bot, session)
    await session.commit()
    await state.clear()
    await callback.answer("انتشار انجام شد")
    lines = [f"✅ <b>کمپین #{campaign.id} منتشر شد.</b>", "", f"📢 کانال‌ها: {channel_sent} موفق / {channel_failed} ناموفق", f"👥 کاربران ربات: {users_sent} موفق / {users_failed} ناموفق", f"🔔 اطلاعیه ربات: {notification_sent} موفق / {notification_failed} ناموفق"]
    if "home" in selected:
        lines.append("🏠 صفحه اصلی ربات: فعال شد")
    await callback.message.edit_text("\n".join(lines))


@router.callback_query(F.data == "advertising:destination:cancel", IsAdmin())
async def cancel_destinations(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("لغو شد")
    await callback.message.edit_text("❌ انتشار کمپین لغو شد.")


@router.callback_query(F.data.regexp(r"^advertising:edit_buttons:\d+$"), IsAdmin())
async def unlimited_button_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    campaign = await session.get(AdvertisingCampaign, int(callback.data.rsplit(":", 1)[1]))
    if not campaign:
        await callback.answer("کمپین پیدا نشد.", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    buttons = campaign.custom_buttons
    for index, item in enumerate(buttons):
        label = str(item.get("label") or "دکمه")[:28]
        b.row(InlineKeyboardButton(text=f"✏️ {index + 1}. {label}", callback_data=f"advertising:button_edit:{campaign.id}:{index}"), InlineKeyboardButton(text="🗑", callback_data=f"advertising:button_delete:{campaign.id}:{index}"))
    b.row(InlineKeyboardButton(text="➕ افزودن دکمه", callback_data=f"advertising:button_add:{campaign.id}"))
    b.row(InlineKeyboardButton(text="🔙 بازگشت به کمپین", callback_data=f"advertising:manage:{campaign.id}"))
    await callback.answer()
    await callback.message.edit_text(f"🔘 <b>مدیریت دکمه‌ها</b>\n\nتعداد دکمه‌ها: <b>{len(buttons)}</b>\n\nهر تعداد دکمه که لازم داری می‌توانی اضافه کنی.", reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^advertising:button_add:\d+$"), IsAdmin())
async def unlimited_button_add_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    campaign_id = int(callback.data.rsplit(":", 1)[1])
    campaign = await session.get(AdvertisingCampaign, campaign_id)
    if not campaign:
        await callback.answer("کمپین پیدا نشد.", show_alert=True)
        return
    await state.update_data(edit_campaign_id=campaign_id)
    await state.set_state(AdvertisingStates.waiting_add_button_title)
    await callback.answer()
    await callback.message.edit_text("➕ <b>افزودن دکمه</b>\n\nعنوان دکمه را ارسال کن.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ لغو", callback_data="advertising:manage:cancel")]]))


@router.message(AdvertisingStates.waiting_add_button_title, IsAdmin())
async def unlimited_button_title(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value or len(value) > 64:
        await message.answer("❌ عنوان دکمه باید بین ۱ تا ۶۴ کاراکتر باشد.")
        return
    await state.update_data(pending_add_button_title=value)
    await state.set_state(AdvertisingStates.waiting_add_button_url)
    await message.answer("🔗 لینک دکمه را ارسال کن.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ لغو", callback_data="advertising:manage:cancel")]]))


@router.message(AdvertisingStates.waiting_add_button_url, IsAdmin())
async def unlimited_button_url(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if value.startswith("@"):
        value = f"https://t.me/{value[1:]}"
    elif value.startswith("t.me/"):
        value = f"https://{value}"
    if not (value.startswith("http://") or value.startswith("https://") or value.startswith("tg://")):
        await message.answer("❌ لینک معتبر نیست.")
        return
    await state.update_data(pending_add_button_url=value)
    await state.set_state(AdvertisingStates.waiting_add_button_color)
    b = InlineKeyboardBuilder()
    for color, label in (("green", "🟢 سبز"), ("red", "🔴 قرمز"), ("blue", "🔵 آبی"), ("none", "⚪ بدون رنگ")):
        b.row(InlineKeyboardButton(text=label, callback_data=f"advertising:add_button_color_unlimited:{color}"))
    b.row(InlineKeyboardButton(text="❌ لغو", callback_data="advertising:manage:cancel"))
    await message.answer("🎨 رنگ دکمه را انتخاب کن.", reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^advertising:add_button_color_unlimited:(green|red|blue|none)$"), AdvertisingStates.waiting_add_button_color, IsAdmin())
async def unlimited_button_color(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    color = callback.data.rsplit(":", 1)[1]
    data = await state.get_data()
    campaign = await session.get(AdvertisingCampaign, int(data.get("edit_campaign_id", 0)))
    if not campaign:
        await state.clear()
        await callback.answer("کمپین پیدا نشد.", show_alert=True)
        return
    buttons = campaign.custom_buttons
    buttons.append({"label": data.get("pending_add_button_title", "دکمه"), "url": data.get("pending_add_button_url", ""), "color": color})
    campaign.custom_buttons = buttons
    await session.commit()
    await state.clear()
    await callback.answer("دکمه اضافه شد")
    await callback.message.edit_text(f"✅ دکمه اضافه شد. تعداد فعلی: {len(buttons)}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔘 مدیریت دکمه‌ها", callback_data=f"advertising:edit_buttons:{campaign.id}")], [InlineKeyboardButton(text="🔙 بازگشت به کمپین", callback_data=f"advertising:manage:{campaign.id}")]]))
