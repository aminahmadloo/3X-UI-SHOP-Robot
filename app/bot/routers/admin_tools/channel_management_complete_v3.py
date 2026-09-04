from __future__ import annotations

import json
from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.routers.admin_tools.channel_management_handler import _channel
from app.db.models import ChannelContent, ChannelReferralCampaign, ChannelSetting, ChannelTemplate, Invite

router = Router(name=__name__)
VARS = "{service_name}, {volume}, {price}, {duration}, {buy_link}, {support_link}"

class States(StatesGroup):
    template_name = State(); template_body = State(); template_edit = State()
    signature = State(); backup = State(); buttons = State(); admins = State(); campaign = State()

def menu():
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

def back():
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 مدیریت کانال", callback_data="channel:menu")]])

async def get_setting(session, channel_id):
    result = await session.execute(select(ChannelSetting).where(ChannelSetting.channel_id == channel_id))
    obj = result.scalar_one_or_none()
    if obj is None:
        obj = ChannelSetting(channel_id=channel_id); session.add(obj); await session.flush()
    return obj

@router.callback_query(F.data == "channel:menu", IsAdmin())
async def channel_menu(callback: CallbackQuery, session: AsyncSession):
    channel = await _channel(session); await callback.answer()
    text = "📢 <b>مدیریت کانال</b>\n\n" + (f"📣 <b>{channel.title}</b>\n🆔 <code>{channel.chat_id}</code>\n🟢 اتصال فعال" if channel else "⚠️ کانال هنوز متصل نشده است.")
    await callback.message.edit_text(text, reply_markup=menu())

@router.callback_query(F.data == "channel:content:drafts", IsAdmin())
async def drafts(callback: CallbackQuery, session: AsyncSession):
    channel = await _channel(session)
    if not channel: await callback.answer("ابتدا کانال را متصل کن.", show_alert=True); return
    result = await session.execute(select(ChannelContent).where(ChannelContent.channel_id == channel.id, ChannelContent.status == "draft").order_by(ChannelContent.updated_at.desc()).limit(50))
    items = list(result.scalars().all()); b = InlineKeyboardBuilder()
    for x in items: b.row(InlineKeyboardButton(text=f"📝 #{x.id} {x.title[:30]}", callback_data=f"channel:complete:draft:{x.id}"))
    b.row(InlineKeyboardButton(text="🧩 ساخت از قالب", callback_data="channel:templates")); b.row(InlineKeyboardButton(text="🔙 مدیریت کانال", callback_data="channel:menu"))
    await callback.answer(); await callback.message.edit_text(f"📂 <b>پیش‌نویس‌ها</b>\n\nتعداد: <b>{len(items)}</b>", reply_markup=b.as_markup())

@router.callback_query(F.data.regexp(r"^channel:complete:draft:\d+$"), IsAdmin())
async def draft(callback: CallbackQuery, session: AsyncSession):
    x = await session.get(ChannelContent, int(callback.data.rsplit(":",1)[1]))
    if not x: await callback.answer("پیش‌نویس پیدا نشد.", show_alert=True); return
    b = InlineKeyboardBuilder(); b.row(InlineKeyboardButton(text="✏️ ادامه ویرایش", callback_data=f"channel:edit:{x.id}")); b.row(InlineKeyboardButton(text="🚀 انتشار فوری", callback_data=f"channel:publish:{x.id}"), InlineKeyboardButton(text="📅 زمان‌بندی", callback_data=f"channel:schedule:{x.id}")); b.row(InlineKeyboardButton(text="📋 کپی", callback_data=f"channel:complete:copy:{x.id}"), InlineKeyboardButton(text="🗑 حذف", callback_data=f"channel:complete:delete:{x.id}")); b.row(InlineKeyboardButton(text="🔙 پیش‌نویس‌ها", callback_data="channel:content:drafts"))
    await callback.answer(); await callback.message.edit_text(f"📂 <b>پیش‌نویس #{x.id}</b>\n\n{x.title}\nنوع: {x.content_type}", reply_markup=b.as_markup())

@router.callback_query(F.data.regexp(r"^channel:complete:copy:\d+$"), IsAdmin())
async def copy(callback: CallbackQuery, session: AsyncSession):
    src = await session.get(ChannelContent, int(callback.data.rsplit(":",1)[1])); channel = await _channel(session)
    if not src or not channel: await callback.answer("محتوا پیدا نشد.", show_alert=True); return
    dst = ChannelContent(channel_id=channel.id, title=f"{src.title[:240]} (کپی)", content_type=src.content_type, body=src.body, media_file_id=src.media_file_id, show_caption_above_media=src.show_caption_above_media, buttons_json=src.buttons_json, poll_question=src.poll_question, poll_options_json=src.poll_options_json, poll_is_anonymous=src.poll_is_anonymous, poll_allows_multiple=src.poll_allows_multiple, status="draft")
    session.add(dst); await session.commit(); await callback.answer(f"پیش‌نویس #{dst.id} ساخته شد.", show_alert=True); await callback.message.edit_text("📋 کپی پست ساخته شد.", reply_markup=back())

@router.callback_query(F.data.regexp(r"^channel:complete:delete:\d+$"), IsAdmin())
async def delete(callback: CallbackQuery, session: AsyncSession):
    x = await session.get(ChannelContent, int(callback.data.rsplit(":",1)[1]))
    if x and x.status == "draft": await session.delete(x); await session.commit()
    await callback.answer("پیش‌نویس حذف شد.", show_alert=True); await drafts(callback, session)

@router.callback_query(F.data == "channel:templates", IsAdmin())
async def templates(callback: CallbackQuery, session: AsyncSession):
    result = await session.execute(select(ChannelTemplate).where(ChannelTemplate.is_active.is_(True)).order_by(ChannelTemplate.id)); rows=list(result.scalars().all()); b=InlineKeyboardBuilder()
    for x in rows: b.row(InlineKeyboardButton(text=f"🧩 {x.name}", callback_data=f"channel:template:view:{x.id}"))
    b.row(InlineKeyboardButton(text="➕ قالب سفارشی جدید", callback_data="channel:template:new")); b.row(InlineKeyboardButton(text="🔙 مدیریت کانال", callback_data="channel:menu"))
    await callback.answer(); await callback.message.edit_text(f"🧩 <b>قالب‌ها</b>\n\nمتغیرها: <code>{VARS}</code>\n\nتعداد فعال: <b>{len(rows)}</b>", reply_markup=b.as_markup())

@router.callback_query(F.data.regexp(r"^channel:template:view:\d+$"), IsAdmin())
async def template_view(callback: CallbackQuery, session: AsyncSession):
    x=await session.get(ChannelTemplate,int(callback.data.rsplit(":",1)[1]))
    if not x: await callback.answer("قالب پیدا نشد.",show_alert=True); return
    b=InlineKeyboardBuilder(); b.row(InlineKeyboardButton(text="🚀 ساخت پیش‌نویس",callback_data=f"channel:template:use:{x.id}")); b.row(InlineKeyboardButton(text="✏️ ویرایش",callback_data=f"channel:template:edit:{x.id}"),InlineKeyboardButton(text="🗑 حذف",callback_data=f"channel:template:delete:{x.id}")); b.row(InlineKeyboardButton(text="🔙 قالب‌ها",callback_data="channel:templates"))
    await callback.answer(); await callback.message.edit_text(f"🧩 <b>{x.name}</b>\n\n<pre>{x.body}</pre>\n\n<code>{VARS}</code>",reply_markup=b.as_markup())

@router.callback_query(F.data.regexp(r"^channel:template:use:\d+$"), IsAdmin())
async def template_use(callback: CallbackQuery, session: AsyncSession):
    x=await session.get(ChannelTemplate,int(callback.data.rsplit(":",1)[1])); channel=await _channel(session)
    if not x or not channel: await callback.answer("قالب یا کانال پیدا نشد.",show_alert=True); return
    item=ChannelContent(channel_id=channel.id,title=x.name[:255],content_type="text",body=x.body,status="draft"); session.add(item); await session.commit(); await callback.answer("پیش‌نویس ساخته شد.",show_alert=True); await callback.message.edit_text(f"🚀 پیش‌نویس #{item.id} ساخته شد. متغیرها را تکمیل کن.",reply_markup=back())

@router.callback_query(F.data == "channel:template:new", IsAdmin())
async def template_new(callback: CallbackQuery, state: FSMContext):
    await state.set_state(States.template_name); await callback.answer(); await callback.message.edit_text("🧩 نام قالب را ارسال کن:",reply_markup=back())

@router.message(States.template_name, IsAdmin())
async def template_name(message: Message,state:FSMContext):
    name=(message.text or "").strip()[:100]
    if not name: await message.answer("❌ نام قالب خالی است."); return
    await state.update_data(name=name); await state.set_state(States.template_body); await message.answer(f"متن قالب را ارسال کن.\n\nمتغیرها: <code>{VARS}</code>")

@router.message(States.template_body, IsAdmin())
async def template_body(message:Message,state:FSMContext,session:AsyncSession):
    body=(message.text or "").strip(); data=await state.get_data()
    if not body: await message.answer("❌ متن خالی است."); return
    session.add(ChannelTemplate(name=data["name"],template_type="custom",body=body)); await session.commit(); await state.clear(); await message.answer("✅ قالب ساخته شد.",reply_markup=back())

@router.callback_query(F.data.regexp(r"^channel:template:edit:\d+$"), IsAdmin())
async def template_edit_start(callback:CallbackQuery,state:FSMContext,session:AsyncSession):
    x=await session.get(ChannelTemplate,int(callback.data.rsplit(":",1)[1]))
    if not x: await callback.answer("قالب پیدا نشد.",show_alert=True); return
    await state.set_state(States.template_edit); await state.update_data(template_id=x.id); await callback.answer(); await callback.message.edit_text(f"✏️ متن جدید «{x.name}» را ارسال کن.\n\n<code>{VARS}</code>",reply_markup=back())

@router.message(States.template_edit, IsAdmin())
async def template_edit_save(message:Message,state:FSMContext,session:AsyncSession):
    data=await state.get_data(); x=await session.get(ChannelTemplate,data.get("template_id")); body=(message.text or "").strip()
    if not x: await state.clear(); await message.answer("❌ قالب پیدا نشد."); return
    if not body: await message.answer("❌ متن خالی است."); return
    x.body=body; await session.commit(); await state.clear(); await message.answer("✅ قالب ویرایش شد.",reply_markup=back())

@router.callback_query(F.data.regexp(r"^channel:template:delete:\d+$"), IsAdmin())
async def template_delete(callback:CallbackQuery,session:AsyncSession):
    x=await session.get(ChannelTemplate,int(callback.data.rsplit(":",1)[1]))
    if x: x.is_active=False; await session.commit()
    await callback.answer("قالب حذف شد.",show_alert=True); await templates(callback,session)

@router.callback_query(F.data == "channel:settings:full", IsAdmin())
async def settings(callback:CallbackQuery,session:AsyncSession):
    channel=await _channel(session)
    if not channel: await callback.answer("ابتدا کانال را متصل کن.",show_alert=True); return
    s=await get_setting(session,channel.id); await session.commit(); b=InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📣 کانال اصلی",callback_data="channel:settings")); b.row(InlineKeyboardButton(text="🗄 کانال پشتیبان",callback_data="channel:setting:backup")); b.row(InlineKeyboardButton(text="✍️ امضای خودکار",callback_data="channel:setting:signature")); b.row(InlineKeyboardButton(text="🔘 دکمه‌های پیش‌فرض",callback_data="channel:setting:buttons")); b.row(InlineKeyboardButton(text=f"{'🟢' if s.auto_publish else '⚪'} انتشار خودکار",callback_data="channel:setting:auto")); b.row(InlineKeyboardButton(text="👮 دسترسی ادمین‌ها",callback_data="channel:setting:admins")); b.row(InlineKeyboardButton(text="🔙 مدیریت کانال",callback_data="channel:menu"))
    await callback.answer(); await callback.message.edit_text(f"⚙️ <b>تنظیمات کانال</b>\n\n📣 {channel.title}\n🗄 پشتیبان: <code>{s.backup_channel_id or '—'}</code>\n✍️ امضا: <code>{s.auto_signature or '—'}</code>\n🚀 انتشار خودکار: <b>{'فعال' if s.auto_publish else 'غیرفعال'}</b>\n👮 ادمین اختصاصی: <b>{'فعال' if s.admin_ids_json != '[]' else 'خیر'}</b>",reply_markup=b.as_markup())

@router.callback_query(F.data == "channel:setting:auto", IsAdmin())
async def auto(callback:CallbackQuery,session:AsyncSession):
    channel=await _channel(session)
    if channel: s=await get_setting(session,channel.id); s.auto_publish=not s.auto_publish; await session.commit()
    await settings(callback,session)

@router.callback_query(F.data == "channel:setting:signature", IsAdmin())
async def signature_start(callback:CallbackQuery,state:FSMContext):
    await state.set_state(States.signature); await callback.answer(); await callback.message.edit_text("✍️ امضای خودکار را ارسال کن. برای حذف: <code>-</code>",reply_markup=back())

@router.message(States.signature, IsAdmin())
async def signature_save(message:Message,state:FSMContext,session:AsyncSession):
    channel=await _channel(session); raw=(message.text or "").strip()
    if channel: s=await get_setting(session,channel.id); s.auto_signature=None if raw=="-" else raw[:255]; await session.commit()
    await state.clear(); await message.answer("✅ امضا ذخیره شد.",reply_markup=back())

@router.callback_query(F.data == "channel:setting:backup", IsAdmin())
async def backup_start(callback:CallbackQuery,state:FSMContext):
    await state.set_state(States.backup); await callback.answer(); await callback.message.edit_text("🗄 آیدی عددی کانال پشتیبان را ارسال کن. برای حذف: <code>-</code>",reply_markup=back())

@router.message(States.backup, IsAdmin())
async def backup_save(message:Message,state:FSMContext,session:AsyncSession):
    raw=(message.text or "").strip()
    try: value=None if raw=="-" else int(raw)
    except ValueError: await message.answer("❌ آیدی باید عددی باشد."); return
    channel=await _channel(session)
    if channel: s=await get_setting(session,channel.id); s.backup_channel_id=value; await session.commit()
    await state.clear(); await message.answer("✅ کانال پشتیبان ذخیره شد.",reply_markup=back())

@router.callback_query(F.data == "channel:setting:buttons", IsAdmin())
async def buttons_start(callback:CallbackQuery,state:FSMContext):
    await state.set_state(States.buttons); await callback.answer(); await callback.message.edit_text("🔘 JSON دکمه‌های پیش‌فرض را ارسال کن یا <code>-</code>.",reply_markup=back())

@router.message(States.buttons, IsAdmin())
async def buttons_save(message:Message,state:FSMContext,session:AsyncSession):
    raw=(message.text or "").strip()
    try:
        value=[] if raw=="-" else json.loads(raw)
        if not isinstance(value,list): raise ValueError
    except (ValueError,TypeError): await message.answer("❌ JSON نامعتبر است."); return
    channel=await _channel(session)
    if channel: s=await get_setting(session,channel.id); s.default_buttons_json=json.dumps(value,ensure_ascii=False); await session.commit()
    await state.clear(); await message.answer("✅ دکمه‌های پیش‌فرض ذخیره شد.",reply_markup=back())

@router.callback_query(F.data == "channel:setting:admins", IsAdmin())
async def admins_start(callback:CallbackQuery,state:FSMContext):
    await state.set_state(States.admins); await callback.answer(); await callback.message.edit_text("👮 شناسه‌های عددی ادمین را با کاما ارسال کن؛ برای حذف: <code>-</code>",reply_markup=back())

@router.message(States.admins, IsAdmin())
async def admins_save(message:Message,state:FSMContext,session:AsyncSession):
    raw=(message.text or "").strip()
    try: ids=[] if raw=="-" else [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError: await message.answer("❌ فقط شناسه عددی."); return
    channel=await _channel(session)
    if channel: s=await get_setting(session,channel.id); s.admin_ids_json=json.dumps(ids); await session.commit()
    await state.clear(); await message.answer("✅ دسترسی ادمین‌ها ذخیره شد.",reply_markup=back())

@router.callback_query(F.data == "channel:stats", IsAdmin())
async def stats(callback:CallbackQuery,session:AsyncSession):
    channel=await _channel(session)
    if not channel: await callback.answer("ابتدا کانال را متصل کن.",show_alert=True); return
    now=datetime.utcnow(); month=now.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    total=await session.scalar(select(func.count(ChannelContent.id)).where(ChannelContent.channel_id==channel.id)) or 0
    monthly=await session.scalar(select(func.count(ChannelContent.id)).where(ChannelContent.channel_id==channel.id,ChannelContent.created_at>=month)) or 0
    published=await session.scalar(select(func.count(ChannelContent.id)).where(ChannelContent.channel_id==channel.id,ChannelContent.status=="published")) or 0
    last=await session.scalar(select(func.max(ChannelContent.published_at)).where(ChannelContent.channel_id==channel.id))
    try: members=await callback.message.bot.get_chat_member_count(channel.chat_id)
    except Exception: members=None
    text=f"📈 <b>آمار کانال</b>\n\n👥 اعضا: <b>{members if members is not None else 'نامشخص'}</b>\n📚 کل محتوا: <b>{total}</b>\n📅 این ماه: <b>{monthly}</b>\n📤 منتشرشده: <b>{published}</b>\n🕐 آخرین فعالیت: <b>{last.strftime('%Y-%m-%d %H:%M') if last else '—'}</b>\n\n📊 رشد تاریخی اعضا پس از جمع‌آوری snapshotهای دوره‌ای قابل نمایش است."
    await callback.answer(); await callback.message.edit_text(text,reply_markup=back())

@router.callback_query(F.data == "channel:campaigns", IsAdmin())
async def campaigns(callback:CallbackQuery,session:AsyncSession):
    result=await session.execute(select(ChannelReferralCampaign,Invite).join(Invite,Invite.id==ChannelReferralCampaign.invite_id).order_by(ChannelReferralCampaign.created_at.desc())); rows=list(result.all()); b=InlineKeyboardBuilder()
    for campaign,invite in rows: b.row(InlineKeyboardButton(text=f"🎯 {campaign.title} — {invite.clicks} کلیک",callback_data=f"channel:campaign:view:{campaign.id}"))
    b.row(InlineKeyboardButton(text="➕ کمپین جدید",callback_data="channel:campaign:new")); b.row(InlineKeyboardButton(text="🔙 مدیریت کانال",callback_data="channel:menu"))
    await callback.answer(); await callback.message.edit_text("🎯 <b>کمپین جذب عضو</b>\n\nاز Invite فعلی استفاده می‌شود؛ پاداش Referral فعلی تغییر نمی‌کند. آمار این بخش بر اساس کلیک لینک دعوت است.",reply_markup=b.as_markup())

@router.callback_query(F.data == "channel:campaign:new", IsAdmin())
async def campaign_new(callback:CallbackQuery,state:FSMContext):
    await state.set_state(States.campaign); await callback.answer(); await callback.message.edit_text("🎯 نام کمپین را ارسال کن:",reply_markup=back())

@router.message(States.campaign, IsAdmin())
async def campaign_save(message:Message,state:FSMContext,session:AsyncSession):
    name=(message.text or "").strip()[:255]
    if not name: await message.answer("❌ نام کمپین خالی است."); return
    slug="channel_"+"".join(c.lower() if c.isalnum() else "_" for c in name)[:35]+"_"+str(int(datetime.utcnow().timestamp()))
    invite=await Invite.create(session,slug); campaign=ChannelReferralCampaign(title=name,invite_id=invite.id,reward_enabled=True); session.add(campaign); await session.commit(); await state.clear(); bot=await message.bot.get_me(); link=f"https://t.me/{bot.username}?start={invite.hash_code}"
    await message.answer(f"✅ کمپین ساخته شد.\n\n🎯 <b>{name}</b>\n🔗 <code>{link}</code>\n🎁 پاداش Referral فعلی: فعال",reply_markup=back())

@router.callback_query(F.data.regexp(r"^channel:campaign:view:\d+$"), IsAdmin())
async def campaign_view(callback:CallbackQuery,session:AsyncSession):
    campaign=await session.get(ChannelReferralCampaign,int(callback.data.rsplit(":",1)[1])); invite=await session.get(Invite,campaign.invite_id) if campaign else None
    if not campaign: await callback.answer("کمپین پیدا نشد.",show_alert=True); return
    bot=await callback.message.bot.get_me(); link=f"https://t.me/{bot.username}?start={invite.hash_code}" if invite else "-"
    await callback.answer(); await callback.message.edit_text(f"🎯 <b>{campaign.title}</b>\n\n🔗 <code>{link}</code>\n👥 کلیک/ورودی: <b>{invite.clicks if invite else 0}</b>\n🎁 پاداش Referral: <b>{'فعال' if campaign.reward_enabled else 'غیرفعال'}</b>",reply_markup=back())
