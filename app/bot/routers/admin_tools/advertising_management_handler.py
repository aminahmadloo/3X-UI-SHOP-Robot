import html
import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    InputMediaVideo,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.states.advertising import AdvertisingStates
from app.bot.routers.admin_tools.advertising_builder_handler import build_ad_markup, get_offers, menu_keyboard
from app.db.models import AdvertisingCampaign, AdvertisingChannel, AdvertisingPublication

logger = logging.getLogger(__name__)
router = Router(name=__name__)

COLORS = ("green", "red", "blue", "none")
COLOR_NAMES = {"green": "🟢 سبز", "red": "🔴 قرمز", "blue": "🔵 آبی", "none": "⚪ بدون رنگ"}


def _cancel_markup() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ لغو", callback_data="advertising:manage:cancel")]]
    )


def _campaign_menu(campaign: AdvertisingCampaign) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✏️ عنوان", callback_data=f"advertising:edit_title:{campaign.id}"))
    b.row(InlineKeyboardButton(text="📝 متن / کپشن", callback_data=f"advertising:edit_body:{campaign.id}"))
    b.row(InlineKeyboardButton(text="🖼 رسانه", callback_data=f"advertising:edit_media:{campaign.id}"))
    b.row(InlineKeyboardButton(text="🔘 مدیریت دکمه‌ها", callback_data=f"advertising:edit_buttons:{campaign.id}"))
    b.row(InlineKeyboardButton(text="🛒 سرویس‌های تبلیغ", callback_data=f"advertising:edit_services:{campaign.id}"))
    status_text = "🔴 غیرفعال کن" if campaign.is_active else "🟢 فعال کن"
    b.row(InlineKeyboardButton(text=status_text, callback_data=f"advertising:toggle_campaign:{campaign.id}"))
    b.row(InlineKeyboardButton(text="👁 پیش‌نمایش", callback_data=f"advertising:edit_preview:{campaign.id}"))
    b.row(InlineKeyboardButton(text="🔙 فهرست کمپین‌ها", callback_data="advertising:manage"))
    return b.as_markup()


def _button_menu(campaign: AdvertisingCampaign) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    buttons = campaign.custom_buttons
    for index, item in enumerate(buttons):
        label = str(item.get("label") or "دکمه")[:28]
        b.row(
            InlineKeyboardButton(text=f"✏️ {index + 1}. {label}", callback_data=f"advertising:button_edit:{campaign.id}:{index}"),
            InlineKeyboardButton(text="🗑", callback_data=f"advertising:button_delete:{campaign.id}:{index}"),
        )
        move_row = []
        if index > 0:
            move_row.append(InlineKeyboardButton(text="⬆️", callback_data=f"advertising:button_up:{campaign.id}:{index}"))
        if index < len(buttons) - 1:
            move_row.append(InlineKeyboardButton(text="⬇️", callback_data=f"advertising:button_down:{campaign.id}:{index}"))
        if move_row:
            b.row(*move_row)
    if len(buttons) < 3:
        b.row(InlineKeyboardButton(text="➕ افزودن دکمه", callback_data=f"advertising:button_add:{campaign.id}"))
    b.row(InlineKeyboardButton(text="🔙 بازگشت به کمپین", callback_data=f"advertising:manage:{campaign.id}"))
    return b.as_markup()


async def _get_campaign(session: AsyncSession, campaign_id: int) -> AdvertisingCampaign | None:
    return await session.get(AdvertisingCampaign, campaign_id)


async def _campaign_text(campaign: AdvertisingCampaign) -> str:
    content = {
        "text": "📝 متن",
        "photo": "🖼 عکس + کپشن",
        "video": "🎬 ویدئو + کپشن",
    }.get(campaign.content_type, campaign.content_type)
    status = "🟢 فعال" if campaign.is_active else "🔴 غیرفعال"
    buttons = campaign.custom_buttons
    selected = campaign.selected_offers
    services = "همه سرویس‌های فعال" if campaign.show_services and not selected else (
        f"{len(selected)} سرویس انتخاب‌شده" if campaign.show_services else "بدون سرویس"
    )
    return (
        f"📢 <b>مدیریت کمپین #{campaign.id}</b>\n\n"
        f"🏷 عنوان: <b>{html.escape(campaign.title)}</b>\n"
        f"📌 وضعیت: {status}\n"
        f"📦 محتوا: {content}\n"
        f"🔘 دکمه سفارشی: {len(buttons)}\n"
        f"🛒 سرویس‌ها: {services}\n\n"
        "هر تغییری که ذخیره کنی، روی انتشارهای فعال همین کمپین نیز اعمال می‌شود."
    )


async def _send_campaign(bot, chat_id: int, campaign: AdvertisingCampaign, session: AsyncSession, channel_id: int):
    markup = await build_ad_markup(
        campaign.id,
        campaign.bot_username or "",
        channel_id,
        session,
        campaign.custom_buttons,
        campaign.selected_offers,
        campaign.show_services,
    )
    if campaign.content_type == "photo":
        return await bot.send_photo(
            chat_id=chat_id,
            photo=campaign.media_file_id,
            caption=campaign.body or None,
            show_caption_above_media=campaign.show_caption_above_media,
            reply_markup=markup,
        )
    if campaign.content_type == "video":
        return await bot.send_video(
            chat_id=chat_id,
            video=campaign.media_file_id,
            caption=campaign.body or None,
            show_caption_above_media=campaign.show_caption_above_media,
            reply_markup=markup,
        )
    return await bot.send_message(chat_id=chat_id, text=campaign.body, reply_markup=markup)


async def _sync_publications(campaign: AdvertisingCampaign, bot, session: AsyncSession) -> tuple[int, int]:
    """Apply the current campaign to every active publication.

    Same-type content is edited in place. When Telegram cannot edit the media type,
    the old message is replaced and the publication row keeps the new message id.
    """
    result = await session.execute(
        select(AdvertisingPublication, AdvertisingChannel)
        .join(AdvertisingChannel, AdvertisingChannel.id == AdvertisingPublication.channel_id)
        .where(
            AdvertisingPublication.campaign_id == campaign.id,
            AdvertisingPublication.is_active.is_(True),
        )
        .order_by(AdvertisingPublication.id),
    )
    rows = list(result.all())
    updated = 0
    failed = 0

    for publication, channel in rows:
        try:
            markup = await build_ad_markup(
                campaign.id,
                campaign.bot_username or "",
                channel.id,
                session,
                campaign.custom_buttons,
                campaign.selected_offers,
                campaign.show_services,
            )
            message_id = publication.message_id
            # We need the old media type only from the campaign's previous state, so callers
            # that change content_type/media pass through the replacement path below.
            if campaign.content_type == "text":
                await bot.edit_message_text(
                    chat_id=channel.chat_id,
                    message_id=message_id,
                    text=campaign.body,
                    reply_markup=markup,
                )
            elif campaign.content_type == "photo":
                await bot.edit_message_media(
                    chat_id=channel.chat_id,
                    message_id=message_id,
                    media=InputMediaPhoto(
                        media=campaign.media_file_id,
                        caption=campaign.body or None,
                        show_caption_above_media=campaign.show_caption_above_media,
                    ),
                    reply_markup=markup,
                )
            else:
                await bot.edit_message_media(
                    chat_id=channel.chat_id,
                    message_id=message_id,
                    media=InputMediaVideo(
                        media=campaign.media_file_id,
                        caption=campaign.body or None,
                        show_caption_above_media=campaign.show_caption_above_media,
                    ),
                    reply_markup=markup,
                )
            updated += 1
        except Exception as exc:
            # A media-type change cannot be represented by edit_message_media. Try a safe
            # replacement only for the known "wrong media type" / missing-message cases.
            try:
                sent = await _send_campaign(bot, channel.chat_id, campaign, session, channel.id)
                try:
                    await bot.delete_message(chat_id=channel.chat_id, message_id=publication.message_id)
                except Exception:
                    pass
                publication.message_id = sent.message_id
                updated += 1
            except Exception as replacement_exc:
                failed += 1
                logger.exception(
                    "Advertising publication sync failed campaign=%s channel=%s: %s / %s",
                    campaign.id,
                    channel.chat_id,
                    exc,
                    replacement_exc,
                )

    return updated, failed


async def _refresh_campaign_message(callback: CallbackQuery, campaign: AdvertisingCampaign) -> None:
    await callback.message.edit_text(await _campaign_text(campaign), reply_markup=_campaign_menu(campaign))


@router.callback_query(F.data == "advertising:manage", IsAdmin())
async def manage_campaigns(callback: CallbackQuery, session: AsyncSession) -> None:
    campaigns = list(
        (
            await session.execute(
                select(AdvertisingCampaign).order_by(AdvertisingCampaign.id.desc()).limit(30)
            )
        ).scalars().all()
    )
    b = InlineKeyboardBuilder()
    lines = ["📢 <b>مدیریت کمپین‌ها</b>", "", "کمپین موردنظر را انتخاب کن:"]
    for campaign in campaigns:
        status = "🟢" if campaign.is_active else "🔴"
        b.row(
            InlineKeyboardButton(
                text=f"{status} #{campaign.id} — {campaign.title[:42]}",
                callback_data=f"advertising:manage:{campaign.id}",
            )
        )
    if not campaigns:
        lines.append("هنوز کمپینی ساخته نشده است.")
    b.row(InlineKeyboardButton(text="📣 ساخت کمپین جدید", callback_data="advertising:create"))
    b.row(InlineKeyboardButton(text="🔙 مرکز تبلیغات", callback_data="advertising:menu"))
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^advertising:manage:\d+$"), IsAdmin())
async def manage_campaign(callback: CallbackQuery, session: AsyncSession) -> None:
    campaign = await _get_campaign(session, int(callback.data.rsplit(":", 1)[1]))
    if not campaign:
        await callback.answer("کمپین پیدا نشد.", show_alert=True)
        return
    await callback.answer()
    await _refresh_campaign_message(callback, campaign)


@router.callback_query(F.data == "advertising:manage:cancel", IsAdmin())
async def cancel_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("لغو شد")
    await callback.message.edit_text("❌ ویرایش لغو شد.", reply_markup=menu_keyboard())


@router.callback_query(F.data.regexp(r"^advertising:edit_title:\d+$"), IsAdmin())
async def edit_title_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    campaign_id = int(callback.data.rsplit(":", 1)[1])
    campaign = await _get_campaign(session, campaign_id)
    if not campaign:
        await callback.answer("کمپین پیدا نشد.", show_alert=True)
        return
    await state.update_data(edit_campaign_id=campaign_id)
    await state.set_state(AdvertisingStates.waiting_edit_campaign_title)
    await callback.answer()
    await callback.message.edit_text(
        f"✏️ <b>ویرایش عنوان کمپین #{campaign.id}</b>\n\nعنوان جدید را ارسال کن.",
        reply_markup=_cancel_markup(),
    )


@router.message(AdvertisingStates.waiting_edit_campaign_title, IsAdmin())
async def edit_title(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = (message.text or "").strip()
    if not value or len(value) > 255:
        await message.answer("❌ عنوان نامعتبر است؛ حداکثر ۲۵۵ کاراکتر.")
        return
    data = await state.get_data()
    campaign = await _get_campaign(session, int(data["edit_campaign_id"]))
    if not campaign:
        await state.clear()
        await message.answer("❌ کمپین پیدا نشد.", reply_markup=menu_keyboard())
        return
    campaign.title = value
    await session.commit()
    await state.clear()
    await message.answer("✅ عنوان کمپین ذخیره شد.", reply_markup=_campaign_menu(campaign))


@router.callback_query(F.data.regexp(r"^advertising:edit_body:\d+$"), IsAdmin())
async def edit_body_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    campaign_id = int(callback.data.rsplit(":", 1)[1])
    campaign = await _get_campaign(session, campaign_id)
    if not campaign:
        await callback.answer("کمپین پیدا نشد.", show_alert=True)
        return
    await state.update_data(edit_campaign_id=campaign_id)
    await state.set_state(AdvertisingStates.waiting_edit_campaign_body)
    await callback.answer()
    await callback.message.edit_text(
        "📝 <b>ویرایش متن / کپشن</b>\n\n"
        "متن جدید را ارسال کن. برای کمپین رسانه‌ای، این متن کپشن همان رسانه خواهد بود.",
        reply_markup=_cancel_markup(),
    )


@router.message(AdvertisingStates.waiting_edit_campaign_body, IsAdmin())
async def edit_body(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = (message.text or "").strip()
    data = await state.get_data()
    campaign = await _get_campaign(session, int(data["edit_campaign_id"]))
    if not campaign:
        await state.clear()
        await message.answer("❌ کمپین پیدا نشد.", reply_markup=menu_keyboard())
        return
    if campaign.content_type == "text" and not value:
        await message.answer("❌ متن کمپین متنی نمی‌تواند خالی باشد.")
        return
    campaign.body = value
    updated, failed = await _sync_publications(campaign, message.bot, session)
    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ متن/کپشن ذخیره شد.\n📡 انتشارهای به‌روزشده: {updated}\n⚠️ ناموفق: {failed}",
        reply_markup=_campaign_menu(campaign),
    )


@router.callback_query(F.data.regexp(r"^advertising:edit_media:\d+$"), IsAdmin())
async def edit_media_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    campaign = await _get_campaign(session, int(callback.data.rsplit(":", 1)[1]))
    if not campaign:
        await callback.answer("کمپین پیدا نشد.", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    if campaign.content_type == "photo":
        b.row(InlineKeyboardButton(text="🖼 تعویض عکس", callback_data=f"advertising:media_upload:photo:{campaign.id}"))
    else:
        b.row(InlineKeyboardButton(text="🖼 تبدیل به عکس", callback_data=f"advertising:media_upload:photo:{campaign.id}"))
    if campaign.content_type == "video":
        b.row(InlineKeyboardButton(text="🎬 تعویض ویدئو", callback_data=f"advertising:media_upload:video:{campaign.id}"))
    else:
        b.row(InlineKeyboardButton(text="🎬 تبدیل به ویدئو", callback_data=f"advertising:media_upload:video:{campaign.id}"))
    if campaign.content_type != "text":
        b.row(InlineKeyboardButton(text="📝 حذف رسانه و تبدیل به متن", callback_data=f"advertising:media_remove:{campaign.id}"))
    b.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"advertising:manage:{campaign.id}"))
    await callback.answer()
    await callback.message.edit_text(
        f"🖼 <b>رسانه کمپین #{campaign.id}</b>\n\nنوع فعلی: <b>{campaign.content_type}</b>\n"
        "تعویض رسانه روی انتشارهای فعال هم اعمال می‌شود.",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data.regexp(r"^advertising:media_upload:(photo|video):\d+$"), IsAdmin())
async def media_upload_start(callback: CallbackQuery, state: FSMContext) -> None:
    kind, campaign_id = callback.data.split(":")[-2:]
    await state.update_data(edit_campaign_id=int(campaign_id), edit_media_kind=kind)
    await state.set_state(AdvertisingStates.waiting_edit_campaign_media)
    await callback.answer()
    prompt = "🖼 عکس جدید را ارسال کن." if kind == "photo" else "🎬 ویدئوی جدید را ارسال کن."
    await callback.message.edit_text(prompt, reply_markup=_cancel_markup())


@router.message(AdvertisingStates.waiting_edit_campaign_media, IsAdmin())
async def edit_media(message: Message, state: FSMContext, session: AsyncSession) -> None:
    data = await state.get_data()
    campaign = await _get_campaign(session, int(data["edit_campaign_id"]))
    kind = data.get("edit_media_kind")
    if not campaign:
        await state.clear()
        await message.answer("❌ کمپین پیدا نشد.", reply_markup=menu_keyboard())
        return
    if kind == "photo" and message.photo:
        campaign.content_type = "photo"
        campaign.media_file_id = message.photo[-1].file_id
        campaign.body = (message.caption or campaign.body or "").strip()
    elif kind == "video" and message.video:
        campaign.content_type = "video"
        campaign.media_file_id = message.video.file_id
        campaign.body = (message.caption or campaign.body or "").strip()
    else:
        await message.answer("❌ رسانه صحیح را ارسال کن.")
        return
    updated, failed = await _sync_publications(campaign, message.bot, session)
    await session.commit()
    await state.clear()
    await message.answer(
        f"✅ رسانه ذخیره و انتشارها به‌روزرسانی شدند.\n📡 موفق: {updated}\n⚠️ ناموفق: {failed}",
        reply_markup=_campaign_menu(campaign),
    )


@router.callback_query(F.data.regexp(r"^advertising:media_remove:\d+$"), IsAdmin())
async def media_remove(callback: CallbackQuery, session: AsyncSession) -> None:
    campaign = await _get_campaign(session, int(callback.data.rsplit(":", 1)[1]))
    if not campaign:
        await callback.answer("کمپین پیدا نشد.", show_alert=True)
        return
    if not campaign.body.strip():
        await callback.answer("ابتدا برای کمپین یک متن/کپشن تنظیم کن.", show_alert=True)
        return
    campaign.content_type = "text"
    campaign.media_file_id = None
    updated, failed = await _sync_publications(campaign, callback.message.bot, session)
    await session.commit()
    await callback.answer("رسانه حذف شد")
    await callback.message.edit_text(
        f"✅ رسانه حذف شد و کمپین متنی شد.\n📡 موفق: {updated}\n⚠️ ناموفق: {failed}",
        reply_markup=_campaign_menu(campaign),
    )


@router.callback_query(F.data.regexp(r"^advertising:edit_buttons:\d+$"), IsAdmin())
async def edit_buttons(callback: CallbackQuery, session: AsyncSession) -> None:
    campaign = await _get_campaign(session, int(callback.data.rsplit(":", 1)[1]))
    if not campaign:
        await callback.answer("کمپین پیدا نشد.", show_alert=True)
        return
    lines = [f"🔘 <b>دکمه‌های کمپین #{campaign.id}</b>", ""]
    if not campaign.custom_buttons:
        lines.append("هنوز دکمه سفارشی ثبت نشده است.")
    else:
        for i, item in enumerate(campaign.custom_buttons, 1):
            lines.append(
                f"{i}. <b>{html.escape(str(item.get('label') or 'دکمه'))}</b>\n"
                f"   🔗 <code>{html.escape(str(item.get('url') or ''))}</code> | 🎨 {item.get('color', 'none')}"
            )
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=_button_menu(campaign))


async def _button_edit_screen(callback: CallbackQuery, campaign: AdvertisingCampaign, index: int) -> None:
    item = campaign.custom_buttons[index]
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✏️ عنوان", callback_data=f"advertising:button_title_edit:{campaign.id}:{index}"))
    b.row(InlineKeyboardButton(text="🔗 لینک / اکشن", callback_data=f"advertising:button_url_edit:{campaign.id}:{index}"))
    b.row(InlineKeyboardButton(text="🎨 رنگ", callback_data=f"advertising:button_color_edit:{campaign.id}:{index}"))
    b.row(InlineKeyboardButton(text="🗑 حذف دکمه", callback_data=f"advertising:button_delete:{campaign.id}:{index}"))
    b.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"advertising:edit_buttons:{campaign.id}"))
    await callback.message.edit_text(
        f"🔘 <b>ویرایش دکمه {index + 1}</b>\n\n"
        f"عنوان: <b>{html.escape(str(item.get('label') or 'دکمه'))}</b>\n"
        f"لینک: <code>{html.escape(str(item.get('url') or ''))}</code>\n"
        f"رنگ: {item.get('color', 'none')}",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data.regexp(r"^advertising:button_edit:\d+:\d+$"), IsAdmin())
async def button_edit(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, _, campaign_id, index = callback.data.split(":")
    campaign = await _get_campaign(session, int(campaign_id))
    index = int(index)
    if not campaign or index < 0 or index >= len(campaign.custom_buttons):
        await callback.answer("دکمه پیدا نشد.", show_alert=True)
        return
    await callback.answer()
    await _button_edit_screen(callback, campaign, index)


async def _start_button_field(callback: CallbackQuery, state: FSMContext, campaign_id: int, index: int, field_state) -> None:
    await state.update_data(edit_campaign_id=campaign_id, edit_button_index=index)
    await state.set_state(field_state)
    await callback.answer()
    prompt = "عنوان جدید را ارسال کن." if field_state == AdvertisingStates.waiting_edit_button_title else "لینک/اکشن جدید را ارسال کن."
    await callback.message.edit_text(prompt, reply_markup=_cancel_markup())


@router.callback_query(F.data.regexp(r"^advertising:button_title_edit:\d+:\d+$"), IsAdmin())
async def button_title_edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, _, campaign_id, index = callback.data.split(":")
    await _start_button_field(callback, state, int(campaign_id), int(index), AdvertisingStates.waiting_edit_button_title)


@router.message(AdvertisingStates.waiting_edit_button_title, IsAdmin())
async def button_title_edit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = (message.text or "").strip()
    if not value or len(value) > 64:
        await message.answer("❌ عنوان باید بین ۱ تا ۶۴ کاراکتر باشد.")
        return
    data = await state.get_data()
    campaign = await _get_campaign(session, int(data["edit_campaign_id"]))
    index = int(data["edit_button_index"])
    if not campaign or index >= len(campaign.custom_buttons):
        await state.clear(); await message.answer("❌ دکمه پیدا نشد.", reply_markup=menu_keyboard()); return
    buttons = campaign.custom_buttons
    buttons[index]["label"] = value
    campaign.custom_buttons = buttons
    updated, failed = await _sync_publications(campaign, message.bot, session)
    await session.commit(); await state.clear()
    await message.answer(f"✅ عنوان دکمه ذخیره شد.\n📡 موفق: {updated}\n⚠️ ناموفق: {failed}", reply_markup=_campaign_menu(campaign))


@router.callback_query(F.data.regexp(r"^advertising:button_url_edit:\d+:\d+$"), IsAdmin())
async def button_url_edit_start(callback: CallbackQuery, state: FSMContext) -> None:
    _, _, _, campaign_id, index = callback.data.split(":")
    await _start_button_field(callback, state, int(campaign_id), int(index), AdvertisingStates.waiting_edit_button_url)


@router.message(AdvertisingStates.waiting_edit_button_url, IsAdmin())
async def button_url_edit(message: Message, state: FSMContext, session: AsyncSession) -> None:
    from app.bot.routers.admin_tools.advertising_builder_handler import normalize_url, valid_url

    value = normalize_url((message.text or "").strip())
    if not valid_url(value):
        await message.answer("❌ لینک معتبر نیست. نمونه: https://example.com یا https://t.me/ToonelVPN")
        return
    data = await state.get_data(); campaign = await _get_campaign(session, int(data["edit_campaign_id"])); index = int(data["edit_button_index"])
    if not campaign or index >= len(campaign.custom_buttons):
        await state.clear(); await message.answer("❌ دکمه پیدا نشد.", reply_markup=menu_keyboard()); return
    buttons = campaign.custom_buttons; buttons[index]["url"] = value; campaign.custom_buttons = buttons
    updated, failed = await _sync_publications(campaign, message.bot, session)
    await session.commit(); await state.clear()
    await message.answer(f"✅ لینک/اکشن دکمه ذخیره شد.\n📡 موفق: {updated}\n⚠️ ناموفق: {failed}", reply_markup=_campaign_menu(campaign))


@router.callback_query(F.data.regexp(r"^advertising:button_color_edit:\d+:\d+$"), IsAdmin())
async def button_color_edit_start(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, _, campaign_id, index = callback.data.split(":")
    campaign = await _get_campaign(session, int(campaign_id)); index = int(index)
    if not campaign or index >= len(campaign.custom_buttons):
        await callback.answer("دکمه پیدا نشد.", show_alert=True); return
    b = InlineKeyboardBuilder()
    for color in COLORS:
        b.row(InlineKeyboardButton(text=COLOR_NAMES[color], callback_data=f"advertising:button_color_set:{campaign.id}:{index}:{color}"))
    b.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"advertising:button_edit:{campaign.id}:{index}"))
    await callback.answer(); await callback.message.edit_text("🎨 رنگ جدید را انتخاب کن.", reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^advertising:button_color_set:\d+:\d+:(green|red|blue|none)$"), IsAdmin())
async def button_color_set(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":"); campaign_id, index, color = int(parts[3]), int(parts[4]), parts[5]
    campaign = await _get_campaign(session, campaign_id)
    if not campaign or index >= len(campaign.custom_buttons):
        await callback.answer("دکمه پیدا نشد.", show_alert=True); return
    buttons = campaign.custom_buttons; buttons[index]["color"] = color; campaign.custom_buttons = buttons
    updated, failed = await _sync_publications(campaign, callback.message.bot, session)
    await session.commit(); await callback.answer("رنگ ذخیره شد")
    await callback.message.edit_text(f"✅ رنگ دکمه ذخیره شد.\n📡 موفق: {updated}\n⚠️ ناموفق: {failed}", reply_markup=_campaign_menu(campaign))


@router.callback_query(F.data.regexp(r"^advertising:button_add:\d+$"), IsAdmin())
async def button_add_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession) -> None:
    campaign_id = int(callback.data.rsplit(":", 1)[1]); campaign = await _get_campaign(session, campaign_id)
    if not campaign: await callback.answer("کمپین پیدا نشد.", show_alert=True); return
    if len(campaign.custom_buttons) >= 3: await callback.answer("حداکثر ۳ دکمه مجاز است.", show_alert=True); return
    await state.update_data(edit_campaign_id=campaign_id, edit_button_index=len(campaign.custom_buttons), edit_button_new=True)
    await state.set_state(AdvertisingStates.waiting_edit_button_title)
    await callback.answer(); await callback.message.edit_text("➕ عنوان دکمه جدید را ارسال کن.", reply_markup=_cancel_markup())


@router.callback_query(F.data.regexp(r"^advertising:button_delete:\d+:\d+$"), IsAdmin())
async def button_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, _, campaign_id, index = callback.data.split(":"); campaign = await _get_campaign(session, int(campaign_id)); index = int(index)
    if not campaign or index >= len(campaign.custom_buttons): await callback.answer("دکمه پیدا نشد.", show_alert=True); return
    buttons = campaign.custom_buttons; buttons.pop(index); campaign.custom_buttons = buttons
    updated, failed = await _sync_publications(campaign, callback.message.bot, session)
    await session.commit(); await callback.answer("دکمه حذف شد")
    await callback.message.edit_text(f"✅ دکمه حذف شد.\n📡 موفق: {updated}\n⚠️ ناموفق: {failed}", reply_markup=_button_menu(campaign))


@router.callback_query(F.data.regexp(r"^advertising:button_(up|down):\d+:\d+$"), IsAdmin())
async def button_move(callback: CallbackQuery, session: AsyncSession) -> None:
    _, _, direction, campaign_id, index = callback.data.split(":"); campaign = await _get_campaign(session, int(campaign_id)); index = int(index)
    if not campaign or index < 0 or index >= len(campaign.custom_buttons): await callback.answer("دکمه پیدا نشد.", show_alert=True); return
    target = index - 1 if direction == "up" else index + 1
    buttons = campaign.custom_buttons
    if target < 0 or target >= len(buttons): await callback.answer(); return
    buttons[index], buttons[target] = buttons[target], buttons[index]; campaign.custom_buttons = buttons
    updated, failed = await _sync_publications(campaign, callback.message.bot, session)
    await session.commit(); await callback.answer("ترتیب دکمه‌ها تغییر کرد")
    await callback.message.edit_text(f"✅ ترتیب دکمه‌ها ذخیره شد.\n📡 موفق: {updated}\n⚠️ ناموفق: {failed}", reply_markup=_button_menu(campaign))


@router.callback_query(F.data.regexp(r"^advertising:edit_services:\d+$"), IsAdmin())
async def edit_services(callback: CallbackQuery, session: AsyncSession) -> None:
    campaign = await _get_campaign(session, int(callback.data.rsplit(":", 1)[1]));
    if not campaign: await callback.answer("کمپین پیدا نشد.", show_alert=True); return
    offers = await get_offers(session); selected = set(campaign.selected_offers); b = InlineKeyboardBuilder()
    for period, plan in offers:
        key = f"{period.id}:{plan.id}"; mark = "☑️" if key in selected else "⬜"
        b.row(InlineKeyboardButton(text=f"{mark} {period.name} | {plan.volume_gb}GB | {plan.duration_days}روز | {plan.price_toman}"[:64], callback_data=f"advertising:edit_offer:{campaign.id}:{period.id}:{plan.id}"))
    b.row(InlineKeyboardButton(text="🚫 بدون سرویس", callback_data=f"advertising:edit_services_off:{campaign.id}"))
    b.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"advertising:manage:{campaign.id}"))
    await callback.answer(); await callback.message.edit_text("🛒 <b>سرویس‌های این کمپین</b>\n\nانتخاب‌ها را تغییر بده.\nاگر انتخابی نداشته باشی، همه سرویس‌های فعال نمایش داده می‌شوند.", reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^advertising:edit_offer:\d+:\d+:\d+$"), IsAdmin())
async def edit_offer(callback: CallbackQuery, session: AsyncSession) -> None:
    parts = callback.data.split(":"); campaign_id, period_id, plan_id = map(int, parts[2:5])
    campaign = await _get_campaign(session, campaign_id)
    if not campaign: await callback.answer("کمپین پیدا نشد.", show_alert=True); return
    selected = set(campaign.selected_offers); key = f"{period_id}:{plan_id}"; selected.remove(key) if key in selected else selected.add(key); campaign.selected_offers = sorted(selected); campaign.show_services = True
    await _sync_publications(campaign, callback.message.bot, session); await session.commit(); await callback.answer("انتخاب به‌روزرسانی شد")
    await edit_services(callback, session)


@router.callback_query(F.data.regexp(r"^advertising:edit_services_off:\d+$"), IsAdmin())
async def edit_services_off(callback: CallbackQuery, session: AsyncSession) -> None:
    campaign = await _get_campaign(session, int(callback.data.rsplit(":", 1)[1]));
    if not campaign: await callback.answer("کمپین پیدا نشد.", show_alert=True); return
    campaign.show_services = False; campaign.selected_offers = []
    updated, failed = await _sync_publications(campaign, callback.message.bot, session); await session.commit(); await callback.answer("سرویس‌ها حذف شدند")
    await callback.message.edit_text(f"✅ سرویس‌ها از کمپین حذف شدند.\n📡 موفق: {updated}\n⚠️ ناموفق: {failed}", reply_markup=_campaign_menu(campaign))


@router.callback_query(F.data.regexp(r"^advertising:toggle_campaign:\d+$"), IsAdmin())
async def toggle_campaign(callback: CallbackQuery, session: AsyncSession) -> None:
    campaign = await _get_campaign(session, int(callback.data.rsplit(":", 1)[1]));
    if not campaign: await callback.answer("کمپین پیدا نشد.", show_alert=True); return
    campaign.is_active = not campaign.is_active; await session.commit(); await callback.answer("وضعیت کمپین تغییر کرد")
    await _refresh_campaign_message(callback, campaign)


@router.callback_query(F.data.regexp(r"^advertising:edit_preview:\d+$"), IsAdmin())
async def edit_preview(callback: CallbackQuery, session: AsyncSession) -> None:
    campaign = await _get_campaign(session, int(callback.data.rsplit(":", 1)[1]));
    if not campaign: await callback.answer("کمپین پیدا نشد.", show_alert=True); return
    channels = await AdvertisingChannel.list_active(session)
    if not channels: await callback.answer("کانال فعالی وجود ندارد.", show_alert=True); return
    markup = await build_ad_markup(campaign.id, campaign.bot_username or "", channels[0].id, session, campaign.custom_buttons, campaign.selected_offers, campaign.show_services)
    try:
        await callback.message.delete()
    except Exception:
        pass
    if campaign.content_type == "photo":
        await callback.message.bot.send_photo(callback.from_user.id, campaign.media_file_id, caption=campaign.body or None, show_caption_above_media=campaign.show_caption_above_media, reply_markup=markup)
    elif campaign.content_type == "video":
        await callback.message.bot.send_video(callback.from_user.id, campaign.media_file_id, caption=campaign.body or None, show_caption_above_media=campaign.show_caption_above_media, reply_markup=markup)
    else:
        await callback.message.bot.send_message(callback.from_user.id, campaign.body, reply_markup=markup)
    await callback.message.bot.send_message(callback.from_user.id, "🔙 برای بازگشت به مدیریت کمپین:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت", callback_data=f"advertising:manage:{campaign.id}")]]))
    await callback.answer()
