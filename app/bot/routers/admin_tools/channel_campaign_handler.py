from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.services.channel_campaign import ChannelAnalyticsService, ChannelCampaignService
from app.db.models import AdvertisingChannel, CampaignEvent, ChannelCampaign, ChannelCampaignMember

router = Router(name=__name__)


class CampaignStates(StatesGroup):
    name = State()
    slug = State()
    description = State()
    campaign_type = State()
    start_date = State()
    end_date = State()
    edit_name = State()
    edit_description = State()


def _campaigns_menu() -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="➕ کمپین جدید", callback_data="campaign:create"))
    b.row(InlineKeyboardButton(text="📊 آمار کمپین‌ها", callback_data="campaign:analytics"))
    b.row(InlineKeyboardButton(text="🔗 لینک‌های اختصاصی", callback_data="campaign:links"))
    b.row(InlineKeyboardButton(text="🏆 برترین معرف‌ها", callback_data="campaign:top_referrers"))
    b.row(InlineKeyboardButton(text="📈 رشد کانال", callback_data="campaign:channel_growth"))
    b.row(InlineKeyboardButton(text="🔙 مدیریت کانال", callback_data="channel:menu"))
    return b


async def _render_campaigns(callback: CallbackQuery, session: AsyncSession) -> None:
    campaigns = list((await session.execute(select(ChannelCampaign).order_by(ChannelCampaign.created_at.desc()))).scalars())
    lines = ["🎯 <b>کمپین‌ها</b>", ""]
    b = InlineKeyboardBuilder()
    if not campaigns:
        lines.append("هنوز کمپینی ایجاد نشده است.")
    for c in campaigns:
        count = (await session.execute(select(func.count(ChannelCampaignMember.id)).where(ChannelCampaignMember.campaign_id == c.id))).scalar() or 0
        icon = {"active": "🟢", "paused": "⏸", "finished": "🏁"}.get(c.status, "⚪")
        lines.append(f"🎯 <b>{c.name}</b>\nStatus: {icon} {c.status}\n👥 جذب: <b>{count}</b>")
        b.row(InlineKeyboardButton(text=f"📊 گزارش {c.name[:24]}", callback_data=f"campaign:report:{c.id}"))
        b.row(InlineKeyboardButton(text="⏸ توقف" if c.status == "active" else "▶️ فعال", callback_data=f"campaign:toggle:{c.id}"), InlineKeyboardButton(text="✏️ ویرایش", callback_data=f"campaign:edit:{c.id}"))
    for row in _campaigns_menu().export().inline_keyboard:
        b.row(*row)
    await callback.message.edit_text("\n".join(lines), reply_markup=b.as_markup())


@router.callback_query(F.data == "campaign:menu", IsAdmin())
async def campaigns_menu(callback: CallbackQuery, session: AsyncSession):
    await callback.answer(); await _render_campaigns(callback, session)


@router.callback_query(F.data == "campaign:create", IsAdmin())
async def campaign_create_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(CampaignStates.name); await callback.answer(); await callback.message.edit_text("🎯 <b>کمپین جدید</b>\n\nنام کمپین را ارسال کن.")


@router.message(CampaignStates.name, IsAdmin())
async def campaign_name(message: Message, state: FSMContext):
    value = (message.text or "").strip()
    if not value: await message.answer("❌ نام کمپین الزامی است."); return
    await state.update_data(name=value); await state.set_state(CampaignStates.slug); await message.answer("🔑 slug کمپین را ارسال کن.\nمثال: <code>summer_2026</code>")


@router.message(CampaignStates.slug, IsAdmin())
async def campaign_slug(message: Message, state: FSMContext, session: AsyncSession):
    value = (message.text or "").strip().lower()
    if not value or not all(ch.isalnum() or ch in "_-" for ch in value): await message.answer("❌ slug فقط می‌تواند شامل حروف، عدد، _ و - باشد."); return
    if await ChannelCampaignService.get_by_slug(session, value): await message.answer("❌ این slug قبلاً استفاده شده است."); return
    await state.update_data(slug=value); await state.set_state(CampaignStates.description); await message.answer("📝 توضیح کمپین را ارسال کن یا <code>-</code> بفرست.")


@router.message(CampaignStates.description, IsAdmin())
async def campaign_description(message: Message, state: FSMContext):
    await state.update_data(description=None if (message.text or "").strip() == "-" else (message.text or "").strip())
    await state.set_state(CampaignStates.campaign_type)
    b = InlineKeyboardBuilder()
    for key, title in (("referral", "🔗 Referral"), ("promo", "🎁 Promo"), ("announcement", "📢 Announcement")): b.row(InlineKeyboardButton(text=title, callback_data=f"campaign:type:{key}"))
    await message.answer("نوع کمپین را انتخاب کن:", reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^campaign:type:(referral|promo|announcement)$"), IsAdmin())
async def campaign_type(callback: CallbackQuery, state: FSMContext):
    await state.update_data(campaign_type=callback.data.rsplit(":", 1)[1]); await state.set_state(CampaignStates.start_date); await callback.answer(); await callback.message.edit_text("📅 تاریخ شروع را YYYY-MM-DD ارسال کن یا <code>-</code> برای همین لحظه.")


@router.message(CampaignStates.start_date, IsAdmin())
async def campaign_start_date(message: Message, state: FSMContext):
    value = (message.text or "").strip(); start = datetime.utcnow()
    if value != "-":
        try: start = datetime.strptime(value, "%Y-%m-%d")
        except ValueError: await message.answer("❌ فرمت تاریخ صحیح نیست."); return
    await state.update_data(start_date=start); await state.set_state(CampaignStates.end_date); await message.answer("📅 تاریخ پایان را YYYY-MM-DD ارسال کن یا <code>-</code> برای بدون پایان.")


@router.message(CampaignStates.end_date, IsAdmin())
async def campaign_end_date(message: Message, state: FSMContext, session: AsyncSession):
    value = (message.text or "").strip(); end = None
    if value != "-":
        try: end = datetime.strptime(value, "%Y-%m-%d")
        except ValueError: await message.answer("❌ فرمت تاریخ صحیح نیست."); return
    data = await state.get_data()
    channel = (await session.execute(select(AdvertisingChannel).where(AdvertisingChannel.is_active.is_(True)).order_by(AdvertisingChannel.id).limit(1))).scalar_one_or_none()
    if not channel: await state.clear(); await message.answer("❌ ابتدا یک کانال فعال در مدیریت کانال تنظیم کن."); return
    campaign = ChannelCampaign(name=data["name"], slug=data["slug"], description=data.get("description"), channel_id=channel.chat_id, campaign_type=data["campaign_type"], status="active", start_date=data["start_date"], end_date=end, created_by=message.from_user.id)
    session.add(campaign); await session.commit(); await state.clear()
    link = ChannelCampaignService.build_link((await message.bot.get_me()).username, campaign.slug)
    await message.answer(f"✅ کمپین ایجاد شد.\n\n🎯 <b>{campaign.name}</b>\n🔗 <code>{link}</code>", reply_markup=_campaigns_menu().as_markup())


@router.callback_query(F.data.regexp(r"^campaign:report:\d+$"), IsAdmin())
async def campaign_report(callback: CallbackQuery, session: AsyncSession):
    data = await ChannelCampaignService.report(session, int(callback.data.rsplit(":", 1)[1]))
    if not data: await callback.answer("کمپین پیدا نشد.", show_alert=True); return
    c = data["campaign"]; link = ChannelCampaignService.build_link((await callback.bot.get_me()).username, c.slug)
    ref_lines = "\n".join(f"• <code>{rid}</code>: {count}" for rid, count in data["top_referrers"]) or "• هنوز داده‌ای ثبت نشده است."
    text = f"🎯 <b>{c.name}</b>\n\nStatus: {'🟢 Active' if c.status == 'active' else '⏸ Paused' if c.status == 'paused' else '🏁 Finished'}\n🔗 <code>{link}</code>\n\n👥 Members: <b>{data['members']}</b>\n🤖 Bot users: <b>{data['started']}</b>\n🛒 Customers: <b>{data['customers']}</b>\n📈 Conversion: <b>{data['conversion_rate']:.1f}%</b>\n💰 Revenue: <b>{data['revenue']:,.0f}</b>\n\n🏆 <b>برترین معرف‌ها</b>\n{ref_lines}"
    b = InlineKeyboardBuilder(); b.row(InlineKeyboardButton(text="🔗 کپی لینک", callback_data=f"campaign:copy:{c.id}")); b.row(InlineKeyboardButton(text="🔙 کمپین‌ها", callback_data="campaign:menu")); await callback.answer(); await callback.message.edit_text(text, reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^campaign:copy:\d+$"), IsAdmin())
async def campaign_copy(callback: CallbackQuery, session: AsyncSession):
    c = await session.get(ChannelCampaign, int(callback.data.rsplit(":", 1)[1]))
    if not c: await callback.answer("کمپین پیدا نشد.", show_alert=True); return
    link = ChannelCampaignService.build_link((await callback.bot.get_me()).username, c.slug); await callback.answer("لینک ساخته شد"); await callback.message.answer(f"🔗 <b>{c.name}</b>\n<code>{link}</code>")


@router.callback_query(F.data.regexp(r"^campaign:toggle:\d+$"), IsAdmin())
async def campaign_toggle(callback: CallbackQuery, session: AsyncSession):
    c = await session.get(ChannelCampaign, int(callback.data.rsplit(":", 1)[1]))
    if not c: await callback.answer("کمپین پیدا نشد.", show_alert=True); return
    c.status = "paused" if c.status == "active" else "active"; await session.commit(); await callback.answer("وضعیت کمپین تغییر کرد"); await _render_campaigns(callback, session)


@router.callback_query(F.data.regexp(r"^campaign:edit:\d+$"), IsAdmin())
async def campaign_edit_start(callback: CallbackQuery, state: FSMContext):
    await state.update_data(campaign_id=int(callback.data.rsplit(":", 1)[1])); await state.set_state(CampaignStates.edit_name); await callback.answer(); await callback.message.edit_text("✏️ نام جدید کمپین را ارسال کن یا <code>-</code> برای حفظ نام فعلی.")


@router.message(CampaignStates.edit_name, IsAdmin())
async def campaign_edit_name(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data(); c = await session.get(ChannelCampaign, data.get("campaign_id"))
    if not c: await state.clear(); return
    if (message.text or "").strip() != "-": c.name = (message.text or "").strip()
    await state.set_state(CampaignStates.edit_description); await message.answer("📝 توضیح جدید را ارسال کن یا <code>-</code> برای حفظ توضیح.")


@router.message(CampaignStates.edit_description, IsAdmin())
async def campaign_edit_description(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data(); c = await session.get(ChannelCampaign, data.get("campaign_id"))
    if not c: await state.clear(); return
    if (message.text or "").strip() != "-": c.description = (message.text or "").strip()
    await session.commit(); await state.clear(); await message.answer("✅ کمپین ویرایش شد.", reply_markup=_campaigns_menu().as_markup())


@router.callback_query(F.data == "campaign:analytics", IsAdmin())
async def campaign_analytics(callback: CallbackQuery, session: AsyncSession):
    campaigns = list((await session.execute(select(ChannelCampaign).order_by(ChannelCampaign.id.desc()).limit(20))).scalars()); lines = ["📊 <b>آمار کمپین‌ها</b>", ""]
    for c in campaigns:
        members = (await session.execute(select(func.count(ChannelCampaignMember.id)).where(ChannelCampaignMember.campaign_id == c.id))).scalar() or 0
        customers = (await session.execute(select(func.count(ChannelCampaignMember.id)).where(ChannelCampaignMember.campaign_id == c.id, ChannelCampaignMember.converted_to_customer.is_(True)))).scalar() or 0
        lines.append(f"🎯 {c.name}: 👥 {members} | 🛒 {customers}")
    await callback.answer(); await callback.message.edit_text("\n".join(lines), reply_markup=_campaigns_menu().as_markup())


@router.callback_query(F.data == "campaign:links", IsAdmin())
async def campaign_links(callback: CallbackQuery, session: AsyncSession):
    campaigns = list((await session.execute(select(ChannelCampaign).order_by(ChannelCampaign.id.desc()))).scalars()); username = (await callback.bot.get_me()).username
    lines = ["🔗 <b>لینک‌های اختصاصی</b>", ""] + [f"🎯 {c.name}\n<code>{ChannelCampaignService.build_link(username, c.slug)}</code>" for c in campaigns]
    await callback.answer(); await callback.message.edit_text("\n\n".join(lines), reply_markup=_campaigns_menu().as_markup())


@router.callback_query(F.data == "campaign:top_referrers", IsAdmin())
async def campaign_top_referrers(callback: CallbackQuery, session: AsyncSession):
    rows = (await session.execute(select(CampaignEvent.referrer_id, func.count(CampaignEvent.id)).where(CampaignEvent.referrer_id.is_not(None)).group_by(CampaignEvent.referrer_id).order_by(func.count(CampaignEvent.id).desc()).limit(20))).all()
    lines = ["🏆 <b>برترین معرف‌ها در کمپین‌ها</b>", ""] + [f"• <code>{rid}</code>: <b>{count}</b>" for rid, count in rows]
    await callback.answer(); await callback.message.edit_text("\n".join(lines), reply_markup=_campaigns_menu().as_markup())


@router.callback_query(F.data == "campaign:channel_growth", IsAdmin())
async def channel_growth(callback: CallbackQuery, session: AsyncSession):
    channel = (await session.execute(select(AdvertisingChannel).where(AdvertisingChannel.is_active.is_(True)).order_by(AdvertisingChannel.id).limit(1))).scalar_one_or_none()
    if not channel: await callback.answer("کانال تنظیم نشده است.", show_alert=True); return
    growth = await ChannelAnalyticsService.growth(session, channel.chat_id)
    campaigns = (await session.execute(select(func.count(ChannelCampaignMember.id)).join(ChannelCampaign).where(ChannelCampaign.channel_id == channel.chat_id))).scalar() or 0
    text = f"📈 <b>رشد کانال</b>\n\nامروز: <b>{growth['today']:+d}</b> users\nاین هفته: <b>{growth['week']:+d}</b>\nاین ماه: <b>{growth['month']:+d}</b>\n\n🎯 Campaign: <b>{campaigns}</b>"
    await callback.answer(); await callback.message.edit_text(text, reply_markup=_campaigns_menu().as_markup())
