from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.db.models import AdvertisingCampaign, AdvertisingChannel, AdvertisingPublication, ChannelContent

logger = logging.getLogger(__name__)
router = Router(name=__name__)


class ChannelStates(StatesGroup):
    waiting_channel = State()
    waiting_title = State()
    waiting_text = State()
    waiting_media = State()
    waiting_poll_question = State()
    waiting_poll_options = State()
    waiting_schedule = State()
    waiting_edit_content = State()


def _menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📝 ایجاد پست", callback_data="channel:content:create"))
    b.row(InlineKeyboardButton(text="📅 زمان‌بندی", callback_data="channel:content:scheduled"), InlineKeyboardButton(text="📂 پیش‌نویس‌ها", callback_data="channel:content:drafts"))
    b.row(InlineKeyboardButton(text="📤 منتشرشده‌ها", callback_data="channel:content:published"))
    b.row(InlineKeyboardButton(text="🔥 فروش ویژه", callback_data="channel:special"), InlineKeyboardButton(text="⚡ اطلاعیه سرور", callback_data="channel:server_notice"))
    b.row(InlineKeyboardButton(text="📊 نظرسنجی", callback_data="channel:poll:create"))
    b.row(InlineKeyboardButton(text="📈 آمار کانال", callback_data="channel:stats"))
    b.row(InlineKeyboardButton(text="⚙️ تنظیمات کانال", callback_data="channel:settings"))
    b.row(InlineKeyboardButton(text="🔙 مرکز تبلیغات", callback_data="advertising:menu"))
    return b.as_markup()


def _cancel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ لغو", callback_data="channel:cancel")]])


def _content_menu(content: ChannelContent) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    if content.status == "published":
        b.row(InlineKeyboardButton(text="✏️ ویرایش پست", callback_data=f"channel:edit:{content.id}"))
        b.row(InlineKeyboardButton(text="🔁 بازنشر", callback_data=f"channel:repost:{content.id}"))
    elif content.status in {"draft", "scheduled"}:
        b.row(InlineKeyboardButton(text="✏️ ویرایش", callback_data=f"channel:edit:{content.id}"))
        if content.status == "scheduled":
            b.row(InlineKeyboardButton(text="🚀 انتشار فوری", callback_data=f"channel:publish:{content.id}"))
    if content.status == "draft":
        b.row(InlineKeyboardButton(text="🚀 انتشار", callback_data=f"channel:publish:{content.id}"), InlineKeyboardButton(text="📅 زمان‌بندی", callback_data=f"channel:schedule:{content.id}"))
    b.row(InlineKeyboardButton(text="📊 جزئیات", callback_data=f"channel:details:{content.id}"))
    b.row(InlineKeyboardButton(text="🗑 حذف از مدیریت", callback_data=f"channel:delete:{content.id}"))
    b.row(InlineKeyboardButton(text="🔙 مدیریت کانال", callback_data="channel:menu"))
    return b.as_markup()


async def _channel(session: AsyncSession) -> AdvertisingChannel | None:
    result = await session.execute(select(AdvertisingChannel).where(AdvertisingChannel.is_active.is_(True)).order_by(AdvertisingChannel.id).limit(1))
    return result.scalar_one_or_none()


async def _verify_channel(bot, chat_id: int):
    chat = await bot.get_chat(chat_id)
    me = await bot.get_me()
    member = await bot.get_chat_member(chat.id, me.id)
    if member.status not in {ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR}:
        raise ValueError("ربات باید در کانال ادمین باشد.")
    if member.status == ChatMemberStatus.ADMINISTRATOR and member.can_post_messages is False:
        raise ValueError("ربات دسترسی ارسال پست در کانال را ندارد.")
    return chat


async def _publish_content(bot, session: AsyncSession, content: ChannelContent, channel: AdvertisingChannel):
    markup = None
    if content.buttons:
        rows = []
        for item in content.buttons[:8]:
            label = str(item.get("label") or "لینک")[:64]
            url = str(item.get("url") or "")
            if url:
                rows.append([InlineKeyboardButton(text=label, url=url)])
        if rows:
            markup = InlineKeyboardMarkup(inline_keyboard=rows)

    if content.content_type == "photo":
        return await bot.send_photo(channel.chat_id, content.media_file_id, caption=content.body or None, show_caption_above_media=content.show_caption_above_media, reply_markup=markup)
    if content.content_type == "video":
        return await bot.send_video(channel.chat_id, content.media_file_id, caption=content.body or None, show_caption_above_media=content.show_caption_above_media, reply_markup=markup)
    if content.content_type == "poll":
        return await bot.send_poll(channel.chat_id, question=content.poll_question or "نظرسنجی", options=content.poll_options, is_anonymous=content.poll_is_anonymous, allows_multiple_answers=content.poll_allows_multiple)
    return await bot.send_message(channel.chat_id, content.body or "", reply_markup=markup)


async def _show_menu(callback: CallbackQuery, session: AsyncSession):
    channel = await _channel(session)
    if channel:
        text = f"📢 <b>مدیریت کانال</b>\n\n📣 کانال: <b>{channel.title}</b>\n🆔 <code>{channel.chat_id}</code>\n🟢 اتصال فعال"
    else:
        text = "📢 <b>مدیریت کانال</b>\n\n⚠️ هنوز کانالی برای انتشار تنظیم نشده است.\nابتدا از «⚙️ تنظیمات کانال» کانال را متصل کن."
    await callback.message.edit_text(text, reply_markup=_menu())


@router.callback_query(F.data == "channel:menu", IsAdmin())
async def channel_menu(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    await _show_menu(callback, session)


@router.callback_query(F.data == "channel:settings", IsAdmin())
async def channel_settings(callback: CallbackQuery, session: AsyncSession):
    channel = await _channel(session)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕/✏️ اتصال کانال", callback_data="channel:settings:set"))
    if channel:
        b.row(InlineKeyboardButton(text="🔍 تست دسترسی ربات", callback_data="channel:settings:test"))
        b.row(InlineKeyboardButton(text="🔴 غیرفعال کردن", callback_data="channel:settings:disable"))
    b.row(InlineKeyboardButton(text="🔙 مدیریت کانال", callback_data="channel:menu"))
    text = "⚙️ <b>تنظیمات کانال</b>\n\n"
    text += f"کانال فعلی: <b>{channel.title}</b>\n🆔 <code>{channel.chat_id}</code>" if channel else "کانال فعلی: ⚪ تنظیم نشده"
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=b.as_markup())


@router.callback_query(F.data == "channel:settings:set", IsAdmin())
async def channel_settings_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ChannelStates.waiting_channel)
    await callback.answer()
    await callback.message.edit_text("📣 آیدی یا username کانال را ارسال کن.\nمثال: <code>@ToonelVPN</code>\n\nربات باید در کانال ادمین و دارای دسترسی ارسال پست باشد.", reply_markup=_cancel())


@router.message(ChannelStates.waiting_channel, IsAdmin())
async def channel_settings_save(message: Message, state: FSMContext, session: AsyncSession):
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("❌ آیدی کانال نامعتبر است.")
        return
    try:
        chat = await _verify_channel(message.bot, raw)
    except Exception as exc:
        await message.answer(f"❌ اتصال کانال انجام نشد.\n{exc}")
        return
    existing = await session.execute(select(AdvertisingChannel).where(AdvertisingChannel.chat_id == chat.id))
    channel = existing.scalar_one_or_none()
    if channel is None:
        channel = AdvertisingChannel(chat_id=chat.id, username=chat.username, title=chat.title or raw, is_active=True)
        session.add(channel)
    else:
        channel.username = chat.username
        channel.title = chat.title or raw
        channel.is_active = True
    await session.commit()
    await state.clear()
    await message.answer(f"✅ کانال با موفقیت متصل شد.\n\n📣 {channel.title}\n🆔 <code>{channel.chat_id}</code>\n🟢 ربات دسترسی ارسال دارد.", reply_markup=_menu())


@router.callback_query(F.data == "channel:settings:test", IsAdmin())
async def channel_settings_test(callback: CallbackQuery, session: AsyncSession):
    channel = await _channel(session)
    if not channel:
        await callback.answer("کانالی تنظیم نشده است.", show_alert=True)
        return
    try:
        await _verify_channel(callback.message.bot, channel.chat_id)
        await callback.answer("✅ دسترسی ارسال فعال است.", show_alert=True)
    except Exception as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(F.data == "channel:settings:disable", IsAdmin())
async def channel_settings_disable(callback: CallbackQuery, session: AsyncSession):
    channel = await _channel(session)
    if channel:
        channel.is_active = False
        await session.commit()
    await callback.answer("کانال غیرفعال شد")
    await _show_menu(callback, session)


@router.callback_query(F.data == "channel:content:create", IsAdmin())
async def create_content_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await _channel(session):
        await callback.answer("ابتدا کانال را از تنظیمات متصل کن.", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📝 متن", callback_data="channel:create_type:text"))
    b.row(InlineKeyboardButton(text="🖼 عکس", callback_data="channel:create_type:photo"), InlineKeyboardButton(text="🎬 ویدئو", callback_data="channel:create_type:video"))
    b.row(InlineKeyboardButton(text="📊 نظرسنجی", callback_data="channel:create_type:poll"))
    b.row(InlineKeyboardButton(text="❌ لغو", callback_data="channel:cancel"))
    await state.clear()
    await callback.answer()
    await callback.message.edit_text("📝 <b>ایجاد پست</b>\n\nنوع محتوا را انتخاب کن:", reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^channel:create_type:(text|photo|video|poll)$"), IsAdmin())
async def create_content_type(callback: CallbackQuery, state: FSMContext):
    content_type = callback.data.rsplit(":", 1)[1]
    await state.update_data(content_type=content_type)
    if content_type == "poll":
        await state.set_state(ChannelStates.waiting_poll_question)
        text = "📊 سوال نظرسنجی را ارسال کن."
    elif content_type == "text":
        await state.set_state(ChannelStates.waiting_text)
        text = "📝 متن پست را ارسال کن."
    else:
        await state.set_state(ChannelStates.waiting_media)
        text = "🖼/🎬 رسانه را ارسال کن.\nبرای رسانه، کپشن را هم می‌توانی همراه آن بفرستی."
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=_cancel())


async def _save_new_content(message: Message, state: FSMContext, session: AsyncSession, content_type: str, body: str | None = None, media_file_id: str | None = None):
    channel = await _channel(session)
    if not channel:
        await state.clear()
        await message.answer("❌ کانال تنظیم نشده است.")
        return
    data = await state.get_data()
    content = ChannelContent(channel_id=channel.id, title=data.get("title") or "پست کانال", content_type=content_type, body=body, media_file_id=media_file_id)
    session.add(content)
    await session.commit()
    await state.clear()
    await message.answer(f"✅ پیش‌نویس #{content.id} ساخته شد.\n\nاکنون می‌توانی آن را منتشر یا زمان‌بندی کنی.", reply_markup=_content_menu(content))


@router.message(ChannelStates.waiting_text, IsAdmin())
async def create_text(message: Message, state: FSMContext, session: AsyncSession):
    value = (message.text or "").strip()
    if not value:
        await message.answer("❌ متن نمی‌تواند خالی باشد.")
        return
    await _save_new_content(message, state, session, "text", body=value)


@router.message(ChannelStates.waiting_media, IsAdmin(), F.photo)
async def create_photo(message: Message, state: FSMContext, session: AsyncSession):
    await _save_new_content(message, state, session, "photo", body=message.caption, media_file_id=message.photo[-1].file_id)


@router.message(ChannelStates.waiting_media, IsAdmin(), F.video)
async def create_video(message: Message, state: FSMContext, session: AsyncSession):
    await _save_new_content(message, state, session, "video", body=message.caption, media_file_id=message.video.file_id)


@router.message(ChannelStates.waiting_poll_question, IsAdmin())
async def poll_question(message: Message, state: FSMContext):
    question = (message.text or "").strip()
    if not question or len(question) > 300:
        await message.answer("❌ سوال نامعتبر است؛ حداکثر ۳۰۰ کاراکتر.")
        return
    await state.update_data(poll_question=question)
    await state.set_state(ChannelStates.waiting_poll_options)
    await message.answer("گزینه‌ها را در یک پیام و با خط جدید یا «|» جدا کن.\nحداقل ۲ و حداکثر ۱۰ گزینه.", reply_markup=_cancel())


@router.message(ChannelStates.waiting_poll_options, IsAdmin())
async def poll_options(message: Message, state: FSMContext, session: AsyncSession):
    raw = (message.text or "").replace("|", "\n")
    options = [x.strip() for x in raw.splitlines() if x.strip()]
    if not 2 <= len(options) <= 10 or any(len(x) > 100 for x in options):
        await message.answer("❌ تعداد گزینه‌ها باید ۲ تا ۱۰ باشد و هر گزینه حداکثر ۱۰۰ کاراکتر.")
        return
    channel = await _channel(session)
    data = await state.get_data()
    content = ChannelContent(channel_id=channel.id, title="نظرسنجی کانال", content_type="poll", poll_question=data["poll_question"])
    content.poll_options = options
    session.add(content)
    await session.commit()
    await state.clear()
    await message.answer(f"✅ نظرسنجی #{content.id} ساخته شد.", reply_markup=_content_menu(content))


@router.callback_query(F.data == "channel:poll:create", IsAdmin())
async def poll_create(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ChannelStates.waiting_poll_question)
    await callback.answer()
    await callback.message.edit_text("📊 سوال نظرسنجی را ارسال کن.", reply_markup=_cancel())


@router.callback_query(F.data.regexp(r"^channel:publish:\d+$"), IsAdmin())
async def publish_content(callback: CallbackQuery, session: AsyncSession):
    content = await session.get(ChannelContent, int(callback.data.rsplit(":", 1)[1]))
    channel = await _channel(session)
    if not content or not channel:
        await callback.answer("محتوا یا کانال پیدا نشد.", show_alert=True)
        return
    try:
        sent = await _publish_content(callback.message.bot, session, content, channel)
        content.telegram_message_id = sent.message_id
        content.status = "published"
        content.published_at = datetime.utcnow()
        content.scheduled_at = None
        await session.commit()
        await callback.answer("✅ در کانال منتشر شد")
        await callback.message.edit_text(f"✅ <b>پست #{content.id} منتشر شد</b>\n\n🆔 پیام کانال: <code>{sent.message_id}</code>", reply_markup=_content_menu(content))
    except Exception as exc:
        logger.exception("Channel publish failed: %s", exc)
        await callback.answer("انتشار انجام نشد؛ دسترسی ربات و کانال را بررسی کن.", show_alert=True)


@router.callback_query(F.data.regexp(r"^channel:schedule:\d+$"), IsAdmin())
async def schedule_start(callback: CallbackQuery, state: FSMContext):
    content_id = int(callback.data.rsplit(":", 1)[1])
    await state.update_data(content_id=content_id)
    await state.set_state(ChannelStates.waiting_schedule)
    await callback.answer()
    await callback.message.edit_text("📅 زمان انتشار را به شکل زیر ارسال کن:\n<code>2026-09-05 18:30</code>\n\nزمان بر اساس ساعت سرور ثبت می‌شود.", reply_markup=_cancel())


@router.message(ChannelStates.waiting_schedule, IsAdmin())
async def schedule_save(message: Message, state: FSMContext, session: AsyncSession):
    try:
        when = datetime.strptime((message.text or "").strip(), "%Y-%m-%d %H:%M")
    except ValueError:
        await message.answer("❌ فرمت زمان صحیح نیست. مثال: <code>2026-09-05 18:30</code>")
        return
    if when <= datetime.utcnow():
        await message.answer("❌ زمان باید در آینده باشد.")
        return
    data = await state.get_data()
    content = await session.get(ChannelContent, int(data["content_id"]))
    if not content:
        await state.clear()
        await message.answer("❌ محتوا پیدا نشد.")
        return
    content.status = "scheduled"
    content.scheduled_at = when
    await session.commit()
    await state.clear()
    await message.answer(f"✅ پست #{content.id} برای <b>{when:%Y-%m-%d %H:%M}</b> زمان‌بندی شد.", reply_markup=_content_menu(content))


async def _list_contents(callback: CallbackQuery, session: AsyncSession, status: str):
    channel = await _channel(session)
    if not channel:
        await callback.answer("کانال تنظیم نشده است.", show_alert=True)
        return
    result = await session.execute(select(ChannelContent).where(ChannelContent.channel_id == channel.id, ChannelContent.status == status).order_by(ChannelContent.id.desc()).limit(30))
    contents = list(result.scalars().all())
    b = InlineKeyboardBuilder()
    title = {"draft": "📂 پیش‌نویس‌ها", "scheduled": "📅 زمان‌بندی‌شده‌ها", "published": "📤 منتشرشده‌ها"}[status]
    lines = [f"<b>{title}</b>", ""]
    for content in contents:
        icon = {"text": "📝", "photo": "🖼", "video": "🎬", "poll": "📊"}.get(content.content_type, "📄")
        lines.append(f"{icon} #{content.id} — {content.title[:40]}")
        b.row(InlineKeyboardButton(text=f"🔎 #{content.id}", callback_data=f"channel:details:{content.id}"))
    if not contents:
        lines.append("موردی وجود ندارد.")
    b.row(InlineKeyboardButton(text="🔙 مدیریت کانال", callback_data="channel:menu"))
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(F.data == "channel:content:drafts", IsAdmin())
async def drafts(callback: CallbackQuery, session: AsyncSession): await _list_contents(callback, session, "draft")


@router.callback_query(F.data == "channel:content:scheduled", IsAdmin())
async def scheduled(callback: CallbackQuery, session: AsyncSession): await _list_contents(callback, session, "scheduled")


@router.callback_query(F.data == "channel:content:published", IsAdmin())
async def published(callback: CallbackQuery, session: AsyncSession): await _list_contents(callback, session, "published")


@router.callback_query(F.data.regexp(r"^channel:details:\d+$"), IsAdmin())
async def content_details(callback: CallbackQuery, session: AsyncSession):
    content = await session.get(ChannelContent, int(callback.data.rsplit(":", 1)[1]))
    if not content:
        await callback.answer("پست پیدا نشد.", show_alert=True)
        return
    status = {"draft": "📂 پیش‌نویس", "scheduled": "📅 زمان‌بندی‌شده", "published": "🟢 منتشرشده"}.get(content.status, content.status)
    text = f"📄 <b>پست #{content.id}</b>\n\n🏷 عنوان: <b>{content.title}</b>\n📦 نوع: {content.content_type}\n📌 وضعیت: {status}"
    if content.telegram_message_id:
        text += f"\n🆔 پیام کانال: <code>{content.telegram_message_id}</code>"
    if content.scheduled_at:
        text += f"\n📅 زمان: <b>{content.scheduled_at:%Y-%m-%d %H:%M}</b>"
    if content.published_at:
        text += f"\n📤 انتشار: <b>{content.published_at:%Y-%m-%d %H:%M}</b>"
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=_content_menu(content))


@router.callback_query(F.data.regexp(r"^channel:edit:\d+$"), IsAdmin())
async def edit_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    content = await session.get(ChannelContent, int(callback.data.rsplit(":", 1)[1]))
    if not content:
        await callback.answer("پست پیدا نشد.", show_alert=True)
        return
    if content.content_type == "poll" and content.status == "published":
        await callback.answer("تلگرام بعد از انتشار امکان ویرایش سوال/گزینه‌های Poll را نمی‌دهد.", show_alert=True)
        return
    await state.update_data(edit_content_id=content.id)
    await state.set_state(ChannelStates.waiting_edit_content)
    prompt = "📝 متن جدید را ارسال کن." if content.content_type == "text" else "🖼/🎬 رسانه جدید را ارسال کن؛ کپشن هم می‌تواند همراه رسانه باشد."
    await callback.answer()
    await callback.message.edit_text(prompt, reply_markup=_cancel())


@router.message(ChannelStates.waiting_edit_content, IsAdmin())
async def edit_content(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    content = await session.get(ChannelContent, int(data["edit_content_id"]))
    channel = await _channel(session)
    if not content or not channel:
        await state.clear(); await message.answer("❌ پست یا کانال پیدا نشد."); return
    try:
        if content.content_type == "text":
            value = (message.text or "").strip()
            if not value: raise ValueError("متن خالی است")
            content.body = value
            if content.status == "published":
                await message.bot.edit_message_text(channel.chat_id, content.telegram_message_id, text=value)
        elif content.content_type == "photo" and message.photo:
            content.media_file_id = message.photo[-1].file_id
            content.body = message.caption
            if content.status == "published":
                await message.bot.edit_message_media(channel.chat_id, content.telegram_message_id, media=InputMediaPhoto(media=content.media_file_id, caption=content.body or None))
        elif content.content_type == "video" and message.video:
            content.media_file_id = message.video.file_id
            content.body = message.caption
            if content.status == "published":
                await message.bot.edit_message_media(channel.chat_id, content.telegram_message_id, media=InputMediaVideo(media=content.media_file_id, caption=content.body or None))
        else:
            raise ValueError("نوع محتوا با پست اصلی مطابقت ندارد")
        await session.commit()
        await state.clear()
        await message.answer(f"✅ پست #{content.id} ویرایش شد.", reply_markup=_content_menu(content))
    except Exception as exc:
        logger.exception("Channel edit failed: %s", exc)
        await message.answer(f"❌ ویرایش انجام نشد: {exc}")


@router.callback_query(F.data.regexp(r"^channel:repost:\d+$"), IsAdmin())
async def repost_content(callback: CallbackQuery, session: AsyncSession):
    content = await session.get(ChannelContent, int(callback.data.rsplit(":", 1)[1]))
    channel = await _channel(session)
    if not content or not channel:
        await callback.answer("پست یا کانال پیدا نشد.", show_alert=True); return
    try:
        if content.telegram_message_id:
            sent = await callback.message.bot.copy_message(chat_id=channel.chat_id, from_chat_id=channel.chat_id, message_id=content.telegram_message_id)
        else:
            sent = await _publish_content(callback.message.bot, session, content, channel)
        clone = ChannelContent(channel_id=channel.id, title=f"بازنشر: {content.title}"[:255], content_type=content.content_type, body=content.body, media_file_id=content.media_file_id, buttons_json=content.buttons_json, poll_question=content.poll_question, poll_options_json=content.poll_options_json, poll_is_anonymous=content.poll_is_anonymous, poll_allows_multiple=content.poll_allows_multiple, status="published", published_at=datetime.utcnow(), telegram_message_id=sent.message_id)
        session.add(clone)
        await session.commit()
        await callback.answer("✅ بازنشر شد")
        await callback.message.edit_text(f"🔁 <b>بازنشر انجام شد</b>\n\nپست جدید: #{clone.id}\n🆔 پیام: <code>{sent.message_id}</code>", reply_markup=_content_menu(clone))
    except Exception as exc:
        logger.exception("Channel repost failed: %s", exc)
        await callback.answer("بازنشر انجام نشد.", show_alert=True)


@router.callback_query(F.data.regexp(r"^channel:delete:\d+$"), IsAdmin())
async def delete_content(callback: CallbackQuery, session: AsyncSession):
    content = await session.get(ChannelContent, int(callback.data.rsplit(":", 1)[1]))
    if not content:
        await callback.answer("پست پیدا نشد.", show_alert=True); return
    await session.delete(content)
    await session.commit()
    await callback.answer("از مدیریت حذف شد")
    await _show_menu(callback, session)


@router.callback_query(F.data == "channel:stats", IsAdmin())
async def channel_stats(callback: CallbackQuery, session: AsyncSession):
    channel = await _channel(session)
    if not channel:
        await callback.answer("کانال تنظیم نشده است.", show_alert=True); return
    try:
        chat = await callback.message.bot.get_chat(channel.chat_id)
        members = await callback.message.bot.get_chat_member_count(channel.chat_id)
        total = await session.scalar(select(func.count(ChannelContent.id)).where(ChannelContent.channel_id == channel.id)) or 0
        published = await session.scalar(select(func.count(ChannelContent.id)).where(ChannelContent.channel_id == channel.id, ChannelContent.status == "published")) or 0
        scheduled = await session.scalar(select(func.count(ChannelContent.id)).where(ChannelContent.channel_id == channel.id, ChannelContent.status == "scheduled")) or 0
        text = f"📈 <b>آمار کانال</b>\n\n📣 {chat.title}\n👥 اعضا: <b>{members:,}</b>\n📄 کل محتواهای مدیریت‌شده: <b>{total:,}</b>\n📤 منتشرشده: <b>{published:,}</b>\n📅 زمان‌بندی‌شده: <b>{scheduled:,}</b>\n\n⚠️ تعداد بازدید واقعی هر پست از Bot API قابل دریافت نیست؛ آمار این بخش بر اساس داده‌های مدیریتی و وضعیت انتشار است."
    except Exception as exc:
        text = f"❌ دریافت آمار کانال انجام نشد: {exc}"
    b = InlineKeyboardBuilder(); b.row(InlineKeyboardButton(text="🔄 بروزرسانی", callback_data="channel:stats")); b.row(InlineKeyboardButton(text="🔙 مدیریت کانال", callback_data="channel:menu"))
    await callback.answer(); await callback.message.edit_text(text, reply_markup=b.as_markup())


@router.callback_query(F.data == "channel:cancel", IsAdmin())
async def channel_cancel(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    await state.clear(); await callback.answer("لغو شد"); await _show_menu(callback, session)


# Repost existing advertising campaigns without replacing the established advertising manager.
from app.bot.routers.admin_tools import advertising_management_handler as _ad_management
_original_campaign_menu = _ad_management._campaign_menu


def _campaign_menu_with_repost(campaign: AdvertisingCampaign):
    markup = _original_campaign_menu(campaign)
    rows = [list(row) for row in markup.inline_keyboard]
    rows.insert(-1, [InlineKeyboardButton(text="🔁 بازنشر در کانال", callback_data=f"advertising:repost_campaign:{campaign.id}")])
    return type(markup)(inline_keyboard=rows)


_ad_management._campaign_menu = _campaign_menu_with_repost


@router.callback_query(F.data.regexp(r"^advertising:repost_campaign:\d+$"), IsAdmin())
async def repost_campaign(callback: CallbackQuery, session: AsyncSession):
    campaign = await session.get(AdvertisingCampaign, int(callback.data.rsplit(":", 1)[1]))
    channel = await _channel(session)
    if not campaign or not channel:
        await callback.answer("کمپین یا کانال پیدا نشد.", show_alert=True); return
    try:
        from app.bot.routers.admin_tools.advertising_management_handler import _send_campaign
        sent = await _send_campaign(callback.message.bot, channel.chat_id, campaign, session, channel.id)
        publication = AdvertisingPublication(campaign_id=campaign.id, channel_id=channel.id, message_id=sent.message_id, is_active=True)
        session.add(publication)
        await session.commit()
        await callback.answer("✅ کمپین بازنشر شد")
        await callback.message.answer(f"🔁 کمپین #{campaign.id} بازنشر شد.\n🆔 پیام کانال: <code>{sent.message_id}</code>")
    except Exception as exc:
        logger.exception("Campaign repost failed: %s", exc)
        await callback.answer("بازنشر کمپین انجام نشد.", show_alert=True)
