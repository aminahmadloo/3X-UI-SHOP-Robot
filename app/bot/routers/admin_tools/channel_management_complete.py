from __future__ import annotations

import json
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.routers.admin_tools.channel_management_handler import _channel, _menu
from app.db.models import ChannelContent, ChannelReferralCampaign, ChannelSetting, ChannelTemplate, Invite

router = Router(name=__name__)


class CompleteChannelStates(StatesGroup):
    template_name = State()
    template_body = State()
    signature = State()
    backup_channel = State()
    default_buttons = State()
    campaign_name = State()


TEMPLATE_VARIABLES = "{service_name}, {volume}, {price}, {duration}, {buy_link}, {support_link}"


def complete_menu() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📝 ایجاد پست", callback_data="channel:content:create"))
    b.row(InlineKeyboardButton(text="📂 پیش‌نویس‌ها", callback_data="channel:content:drafts"), InlineKeyboardButton(text="📅 زمان‌بندی", callback_data="channel:content:scheduled"))
    b.row(InlineKeyboardButton(text="📤 منتشرشده‌ها", callback_data="channel:content:published"))
    b.row(InlineKeyboardButton(text="🔥 فروش ویژه", callback_data="channel:special"), InlineKeyboardButton(text="⚡ اطلاعیه سرور", callback_data="channel:server_notice"))
    b.row(InlineKeyboardButton(text="📊 نظرسنجی", callback_data="channel:poll:create"))
    b.row(InlineKeyboardButton(text="🧩 قالب‌ها", callback_data="channel:templates"))
    b.row(InlineKeyboardButton(text="🎯 کمپین جذب عضو", callback_data="channel:campaigns"))
    b.row(InlineKeyboardButton(text="📈 آمار کانال", callback_data="channel:stats"), InlineKeyboardButton(text="⚙️ تنظیمات", callback_data="channel:settings:full"))
    b.row(InlineKeyboardButton(text="🔙 مرکز تبلیغات", callback_data="advertising:menu"))
    return b.as_markup()


def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 مدیریت کانال", callback_data="channel:menu")]])


def _template_menu(template: ChannelTemplate) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="🚀 ساخت پیش‌نویس از قالب", callback_data=f"channel:template:use:{template.id}"))
    b.row(InlineKeyboardButton(text="✏️ ویرایش قالب", callback_data=f"channel:template:edit:{template.id}"))
    b.row(InlineKeyboardButton(text="🗑 حذف قالب", callback_data=f"channel:template:delete:{template.id}"))
    b.row(InlineKeyboardButton(text="🔙 قالب‌ها", callback_data="channel:templates"))
    return b.as_markup()


async def _settings(session: AsyncSession, channel_id: int) -> ChannelSetting:
    result = await session.execute(select(ChannelSetting).where(ChannelSetting.channel_id == channel_id))
    setting = result.scalar_one_or_none()
    if setting is None:
        setting = ChannelSetting(channel_id=channel_id)
        session.add(setting)
        await session.flush()
    return setting


@router.callback_query(F.data == "channel:menu", IsAdmin())
async def complete_channel_menu(callback: CallbackQuery, session: AsyncSession):
    channel = await _channel(session)
    await callback.answer()
    if channel:
        text = f"📢 <b>مدیریت کانال</b>\n\n📣 <b>{channel.title}</b>\n🆔 <code>{channel.chat_id}</code>\n🟢 اتصال فعال\n\nهمه ابزارهای مدیریت محتوا، قالب، آمار و کمپین از اینجا در دسترس است."
    else:
        text = "📢 <b>مدیریت کانال</b>\n\n⚠️ هنوز کانالی متصل نشده است."
    await callback.message.edit_text(text, reply_markup=complete_menu())


@router.callback_query(F.data == "channel:content:drafts", IsAdmin())
async def complete_drafts(callback: CallbackQuery, session: AsyncSession):
    channel = await _channel(session)
    if not channel:
        await callback.answer("ابتدا کانال را متصل کن.", show_alert=True)
        return
    result = await session.execute(select(ChannelContent).where(ChannelContent.channel_id == channel.id, ChannelContent.status == "draft").order_by(ChannelContent.updated_at.desc()).limit(30))
    drafts = list(result.scalars().all())
    b = InlineKeyboardBuilder()
    for content in drafts:
        label = f"📝 #{content.id} {content.title[:28]}"
        b.row(InlineKeyboardButton(text=label, callback_data=f"channel:complete:draft:{content.id}"))
    b.row(InlineKeyboardButton(text="🧩 ساخت از قالب", callback_data="channel:templates"))
    b.row(InlineKeyboardButton(text="🔙 مدیریت کانال", callback_data="channel:menu"))
    text = "📂 <b>پیش‌نویس‌ها</b>\n\n" + ("هیچ پیش‌نویسی ندارید." if not drafts else f"تعداد: <b>{len(drafts)}</b>\nیک مورد را انتخاب کن:")
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^channel:complete:draft:\d+$"), IsAdmin())
async def draft_actions(callback: CallbackQuery, session: AsyncSession):
    content = await session.get(ChannelContent, int(callback.data.rsplit(":", 1)[1]))
    if not content:
        await callback.answer("پیش‌نویس پیدا نشد.", show_alert=True)
        return
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✏️ ادامه ویرایش", callback_data=f"channel:edit:{content.id}"))
    b.row(InlineKeyboardButton(text="🚀 انتشار فوری", callback_data=f"channel:publish:{content.id}"), InlineKeyboardButton(text="📅 زمان‌بندی", callback_data=f"channel:schedule:{content.id}"))
    b.row(InlineKeyboardButton(text="📋 کپی پست", callback_data=f"channel:complete:copy:{content.id}"))
    b.row(InlineKeyboardButton(text="🗑 حذف", callback_data=f"channel:complete:delete:{content.id}"))
    b.row(InlineKeyboardButton(text="🔙 پیش‌نویس‌ها", callback_data="channel:content:drafts"))
    await callback.answer()
    await callback.message.edit_text(f"📂 <b>پیش‌نویس #{content.id}</b>\n\n<b>{content.title}</b>\nنوع: {content.content_type}\nوضعیت: پیش‌نویس", reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^channel:complete:copy:\d+$"), IsAdmin())
async def copy_content(callback: CallbackQuery, session: AsyncSession):
    source = await session.get(ChannelContent, int(callback.data.rsplit(":", 1)[1]))
    channel = await _channel(session)
    if not source or not channel:
        await callback.answer("محتوا پیدا نشد.", show_alert=True)
        return
    copy = ChannelContent(channel_id=channel.id, title=f"{source.title[:240]} (کپی)", content_type=source.content_type, body=source.body, media_file_id=source.media_file_id, show_caption_above_media=source.show_caption_above_media, buttons_json=source.buttons_json, poll_question=source.poll_question, poll_options_json=source.poll_options_json, poll_is_anonymous=source.poll_is_anonymous, poll_allows_multiple=source.poll_allows_multiple, status="draft")
    session.add(copy)
    await session.commit()
    await callback.answer(f"پیش‌نویس #{copy.id} ساخته شد.", show_alert=True)
    await callback.message.edit_text(f"📋 کپی پست ساخته شد.\n\nپیش‌نویس جدید: <b>#{copy.id}</b>", reply_markup=back_menu())


@router.callback_query(F.data.regexp(r"^channel:complete:delete:\d+$"), IsAdmin())
async def delete_draft(callback: CallbackQuery, session: AsyncSession):
    content = await session.get(ChannelContent, int(callback.data.rsplit(":", 1)[1]))
    if content and content.status == "draft":
        await session.delete(content)
        await session.commit()
    await callback.answer("پیش‌نویس حذف شد.", show_alert=True)
    await complete_drafts(callback, session)


@router.callback_query(F.data == "channel:templates", IsAdmin())
async def templates(callback: CallbackQuery, session: AsyncSession):
    result = await session.execute(select(ChannelTemplate).where(ChannelTemplate.is_active.is_(True)).order_by(ChannelTemplate.id))
    rows = list(result.scalars().all())
    b = InlineKeyboardBuilder()
    for row in rows:
        b.row(InlineKeyboardButton(text=f"🧩 {row.name}", callback_data=f"channel:template:view:{row.id}"))
    b.row(InlineKeyboardButton(text="➕ قالب سفارشی جدید", callback_data="channel:template:new"))
    b.row(InlineKeyboardButton(text="🔙 مدیریت کانال", callback_data="channel:menu"))
    await callback.answer()
    await callback.message.edit_text(f"🧩 <b>قالب‌ها</b>\n\nقالب‌های آماده و سفارشی برای ساخت سریع پست.\n\nمتغیرهای قابل استفاده:\n<code>{TEMPLATE_VARIABLES}</code>\n\nتعداد قالب فعال: <b>{len(rows)}</b>", reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^channel:template:view:\d+$"), IsAdmin())
async def template_view(callback: CallbackQuery, session: AsyncSession):
    template = await session.get(ChannelTemplate, int(callback.data.rsplit(":", 1)[1]))
    if not template:
        await callback.answer("قالب پیدا نشد.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(f"🧩 <b>{template.name}</b>\n\nنوع: <code>{template.template_type}</code>\n\n<pre>{template.body}</pre>\n\nمتغیرها: <code>{TEMPLATE_VARIABLES}</code>", reply_markup=_template_menu(template))


@router.callback_query(F.data.regexp(r"^channel:template:use:\d+$"), IsAdmin())
async def use_template(callback: CallbackQuery, session: AsyncSession):
    template = await session.get(ChannelTemplate, int(callback.data.rsplit(":", 1)[1]))
    channel = await _channel(session)
    if not template or not channel:
        await callback.answer("قالب یا کانال پیدا نشد.", show_alert=True)
        return
    content = ChannelContent(channel_id=channel.id, title=template.name[:255], content_type="text", body=template.body, status="draft")
    session.add(content)
    await session.commit()
    await callback.answer("پیش‌نویس ساخته شد.", show_alert=True)
    await callback.message.edit_text(f"🚀 پیش‌نویس <b>#{content.id}</b> از قالب ساخته شد.\n\nمتغیرها را در متن جایگزین کن و سپس منتشر یا زمان‌بندی کن.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="✏️ ویرایش", callback_data=f"channel:edit:{content.id}")],[InlineKeyboardButton(text="🔙 پیش‌نویس‌ها", callback_data="channel:content:drafts")]]))


@router.callback_query(F.data == "channel:template:new", IsAdmin())
async def template_new(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CompleteChannelStates.template_name)
    await callback.answer()
    await callback.message.edit_text("🧩 نام قالب سفارشی را ارسال کن:", reply_markup=back_menu())


@router.message(CompleteChannelStates.template_name, IsAdmin())
async def template_name(message: Message, state: FSMContext):
    name = (message.text or "").strip()[:100]
    if not name:
        await message.answer("❌ نام قالب نمی‌تواند خالی باشد.")
        return
    await state.update_data(template_name=name)
    await state.set_state(CompleteChannelStates.template_body)
    await message.answer(f"متن قالب را ارسال کن.\n\nمتغیرهای قابل استفاده:\n<code>{TEMPLATE_VARIABLES}</code>")


@router.message(CompleteChannelStates.template_body, IsAdmin())
async def template_body(message: Message, state: FSMContext, session: AsyncSession):
    body = (message.text or "").strip()
    if not body:
        await message.answer("❌ متن قالب نمی‌تواند خالی باشد.")
        return
    data = await state.get_data()
    template = ChannelTemplate(name=data["template_name"], template_type="custom", body=body)
    session.add(template)
    await session.commit()
    await state.clear()
    await message.answer(f"✅ قالب «{template.name}» ساخته شد.", reply_markup=back_menu())


@router.callback_query(F.data.regexp(r"^channel:template:delete:\d+$"), IsAdmin())
async def template_delete(callback: CallbackQuery, session: AsyncSession):
    template = await session.get(ChannelTemplate, int(callback.data.rsplit(":", 1)[1]))
    if template:
        template.is_active = False
        await session.commit()
    await callback.answer("قالب حذف شد.", show_alert=True)
    await templates(callback, session)


@router.callback_query(F.data == "channel:settings:full", IsAdmin())
async def full_settings(callback: CallbackQuery, session: AsyncSession):
    channel = await _channel(session)
    if not channel:
        await callback.answer("ابتدا کانال را متصل کن.", show_alert=True)
        return
    setting = await _settings(session, channel.id)
    await session.commit()
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📣 کانال اصلی", callback_data="channel:settings"))
    b.row(InlineKeyboardButton(text="🗄 کانال پشتیبان", callback_data="channel:setting:backup"))
    b.row(InlineKeyboardButton(text="✍️ امضای خودکار", callback_data="channel:setting:signature"))
    b.row(InlineKeyboardButton(text="🔘 دکمه‌های پیش‌فرض", callback_data="channel:setting:buttons"))
    b.row(InlineKeyboardButton(text=f"{'🟢' if setting.auto_publish else '⚪'} انتشار خودکار", callback_data="channel:setting:auto"))
    b.row(InlineKeyboardButton(text="👮 دسترسی ادمین‌ها", callback_data="channel:setting:admins"))
    b.row(InlineKeyboardButton(text="🔙 مدیریت کانال", callback_data="channel:menu"))
    text = f"⚙️ <b>تنظیمات کانال</b>\n\n📣 کانال اصلی: <b>{channel.title}</b>\n🗄 پشتیبان: <code>{setting.backup_channel_id or 'تنظیم نشده'}</code>\n✍️ امضا: <code>{setting.auto_signature or 'غیرفعال'}</code>\n🔘 دکمه پیش‌فرض: {'تنظیم شده' if setting.default_buttons_json != '[]' else 'تنظیم نشده'}\n🚀 انتشار خودکار: {'فعال' if setting.auto_publish else 'غیرفعال'}\n👮 ادمین‌های اختصاصی: {'تنظیم شده' if setting.admin_ids_json != '[]' else 'همان ادمین‌های ربات'}"
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=b.as_markup())


@router.callback_query(F.data == "channel:setting:auto", IsAdmin())
async def setting_auto(callback: CallbackQuery, session: AsyncSession):
    channel = await _channel(session)
    if channel:
        setting = await _settings(session, channel.id)
        setting.auto_publish = not setting.auto_publish
        await session.commit()
    await full_settings(callback, session)


@router.callback_query(F.data == "channel:setting:signature", IsAdmin())
async def setting_signature_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CompleteChannelStates.signature)
    await callback.answer()
    await callback.message.edit_text("✍️ امضای خودکار را ارسال کن.\nبرای خاموش کردن: <code>-</code>", reply_markup=back_menu())


@router.message(CompleteChannelStates.signature, IsAdmin())
async def setting_signature_save(message: Message, state: FSMContext, session: AsyncSession):
    channel = await _channel(session)
    if channel:
        setting = await _settings(session, channel.id)
        setting.auto_signature = None if (message.text or "").strip() == "-" else (message.text or "").strip()[:255]
        await session.commit()
    await state.clear()
    await message.answer("✅ امضای خودکار ذخیره شد.", reply_markup=back_menu())


@router.callback_query(F.data == "channel:setting:backup", IsAdmin())
async def setting_backup_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CompleteChannelStates.backup_channel)
    await callback.answer()
    await callback.message.edit_text("🗄 آیدی کانال پشتیبان را ارسال کن.\nبرای حذف: <code>-</code>", reply_markup=back_menu())


@router.message(CompleteChannelStates.backup_channel, IsAdmin())
async def setting_backup_save(message: Message, state: FSMContext, session: AsyncSession):
    channel = await _channel(session)
    raw = (message.text or "").strip()
    try:
        value = None if raw == "-" else int(raw)
    except ValueError:
        await message.answer("❌ آیدی کانال باید عددی باشد.")
        return
    if channel:
        setting = await _settings(session, channel.id)
        setting.backup_channel_id = value
        await session.commit()
    await state.clear()
    await message.answer("✅ کانال پشتیبان ذخیره شد.", reply_markup=back_menu())


@router.callback_query(F.data == "channel:setting:buttons", IsAdmin())
async def setting_buttons_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CompleteChannelStates.default_buttons)
    await callback.answer()
    await callback.message.edit_text("🔘 دکمه‌های پیش‌فرض را به صورت JSON ارسال کن.\nمثال:\n<code>[{\"label\":\"🛒 خرید\",\"url\":\"https://t.me/ToonelVpn_bot\"}]</code>\nبرای حذف: <code>-</code>", reply_markup=back_menu())


@router.message(CompleteChannelStates.default_buttons, IsAdmin())
async def setting_buttons_save(message: Message, state: FSMContext, session: AsyncSession):
    raw = (message.text or "").strip()
    if raw == "-":
        value = []
    else:
        try:
            value = json.loads(raw)
            if not isinstance(value, list):
                raise ValueError
        except (ValueError, TypeError):
            await message.answer("❌ JSON نامعتبر است.")
            return
    channel = await _channel(session)
    if channel:
        setting = await _settings(session, channel.id)
        setting.default_buttons_json = json.dumps(value, ensure_ascii=False)
        await session.commit()
    await state.clear()
    await message.answer("✅ دکمه‌های پیش‌فرض ذخیره شد.", reply_markup=back_menu())


@router.callback_query(F.data == "channel:setting:admins", IsAdmin())
async def setting_admins_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CompleteChannelStates.default_buttons)
    await callback.answer()
    await callback.message.edit_text("👮 شناسه عددی ادمین‌های اختصاصی را با کاما ارسال کن.\nمثال: <code>123456,987654</code>\nبرای استفاده از ادمین‌های فعلی ربات: <code>-</code>", reply_markup=back_menu())


@router.message(CompleteChannelStates.default_buttons, IsAdmin(), F.text.regexp(r"^[0-9,\- ]+$"))
async def setting_admins_save(message: Message, state: FSMContext, session: AsyncSession):
    raw = (message.text or "").strip()
    channel = await _channel(session)
    if channel:
        setting = await _settings(session, channel.id)
        ids = [] if raw == "-" else [int(x.strip()) for x in raw.split(",") if x.strip()]
        setting.admin_ids_json = json.dumps(ids)
        await session.commit()
    await state.clear()
    await message.answer("✅ دسترسی ادمین‌های کانال ذخیره شد.", reply_markup=back_menu())


@router.callback_query(F.data == "channel:stats", IsAdmin())
async def channel_stats(callback: CallbackQuery, session: AsyncSession):
    channel = await _channel(session)
    if not channel:
        await callback.answer("ابتدا کانال را متصل کن.", show_alert=True)
        return
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = await session.scalar(select(func.count(ChannelContent.id)).where(ChannelContent.channel_id == channel.id)) or 0
    month = await session.scalar(select(func.count(ChannelContent.id)).where(ChannelContent.channel_id == channel.id, ChannelContent.created_at >= month_start)) or 0
    published = await session.scalar(select(func.count(ChannelContent.id)).where(ChannelContent.channel_id == channel.id, ChannelContent.status == "published")) or 0
    last = await session.scalar(select(func.max(ChannelContent.published_at)).where(ChannelContent.channel_id == channel.id))
    try:
        members = await callback.message.bot.get_chat_member_count(channel.chat_id)
    except Exception:
        members = None
    text = "📈 <b>آمار کانال</b>\n\n"
    text += f"👥 اعضای فعلی: <b>{members if members is not None else 'نامشخص'}</b>\n"
    text += f"📚 تعداد کل محتواهای مدیریت‌شده: <b>{total}</b>\n"
    text += f"📅 محتوای این ماه: <b>{month}</b>\n"
    text += f"📤 منتشرشده: <b>{published}</b>\n"
    text += f"🕐 آخرین فعالیت: <b>{last.strftime('%Y-%m-%d %H:%M') if last else 'هنوز ثبت نشده'}</b>\n\n"
    text += "📊 رشد اعضا: از این نسخه به بعد تعداد اعضا در زمان مشاهده ثبت می‌شود؛ برای نمودار تاریخی باید چند نقطه زمانی جمع شود."
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=back_menu())


@router.callback_query(F.data == "channel:campaigns", IsAdmin())
async def campaigns(callback: CallbackQuery, session: AsyncSession):
    result = await session.execute(select(ChannelReferralCampaign, Invite).join(Invite, Invite.id == ChannelReferralCampaign.invite_id).order_by(ChannelReferralCampaign.created_at.desc()))
    rows = list(result.all())
    b = InlineKeyboardBuilder()
    for campaign, invite in rows:
        b.row(InlineKeyboardButton(text=f"🎯 {campaign.title} ({invite.clicks})", callback_data=f"channel:campaign:view:{campaign.id}"))
    b.row(InlineKeyboardButton(text="➕ کمپین جدید", callback_data="channel:campaign:new"))
    b.row(InlineKeyboardButton(text="🔙 مدیریت کانال", callback_data="channel:menu"))
    await callback.answer()
    await callback.message.edit_text("🎯 <b>کمپین جذب عضو</b>\n\nکمپین‌ها از لینک‌های دعوت موجود استفاده می‌کنند و پاداش referral فعلی را تغییر نمی‌دهند.\n\nتعداد داخل فهرست، ورودی/کلیک ثبت‌شده برای لینک دعوت است.", reply_markup=b.as_markup())


@router.callback_query(F.data == "channel:campaign:new", IsAdmin())
async def campaign_new(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CompleteChannelStates.campaign_name)
    await callback.answer()
    await callback.message.edit_text("🎯 نام کمپین را ارسال کن.\nمثلاً: <b>کمپین جذب عضو شهریور</b>", reply_markup=back_menu())


@router.message(CompleteChannelStates.campaign_name, IsAdmin())
async def campaign_save(message: Message, state: FSMContext, session: AsyncSession):
    name = (message.text or "").strip()[:255]
    if not name:
        await message.answer("❌ نام کمپین نمی‌تواند خالی باشد.")
        return
    safe = "channel_" + "".join(ch.lower() if ch.isalnum() else "_" for ch in name)[:40] + "_" + str(int(datetime.utcnow().timestamp()))
    invite = await Invite.create(session, safe)
    campaign = ChannelReferralCampaign(title=name, invite_id=invite.id, reward_enabled=True)
    session.add(campaign)
    await session.commit()
    await state.clear()
    bot = await message.bot.get_me()
    link = f"https://t.me/{bot.username}?start={invite.hash_code}"
    await message.answer(f"✅ کمپین ساخته شد.\n\n🎯 <b>{name}</b>\n🔗 <code>{link}</code>\n🎁 پاداش referral فعلی: {'فعال' if campaign.reward_enabled else 'غیرفعال'}", reply_markup=back_menu())


@router.callback_query(F.data.regexp(r"^channel:campaign:view:\d+$"), IsAdmin())
async def campaign_view(callback: CallbackQuery, session: AsyncSession):
    campaign = await session.get(ChannelReferralCampaign, int(callback.data.rsplit(":", 1)[1]))
    if not campaign:
        await callback.answer("کمپین پیدا نشد.", show_alert=True)
        return
    invite = await session.get(Invite, campaign.invite_id)
    bot = await callback.message.bot.get_me()
    link = f"https://t.me/{bot.username}?start={invite.hash_code}" if invite else "-"
    text = f"🎯 <b>{campaign.title}</b>\n\n🔗 <code>{link}</code>\n👥 ورودی/کلیک: <b>{invite.clicks if invite else 0}</b>\n🎁 پاداش referral: <b>{'فعال' if campaign.reward_enabled else 'غیرفعال'}</b>\n\nاین کمپین به سیستم Referral فعلی متصل است و از همان لینک دعوت استفاده می‌کند."
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=back_menu())
