"""V2 controls layered over the original channel-management workflow."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.routers.admin_tools.channel_management_handler import ChannelStates, _channel, _content_menu, _menu
from app.bot.services.channel_templates import render_template
from app.db.models import ChannelContent, ChannelContentEvent, ChannelContentTemplate, ChannelSettings

router = Router(name=__name__)


async def _event(session: AsyncSession, content_id: int, event_type: str) -> None:
    session.add(ChannelContentEvent(content_id=content_id, event_type=event_type))


@router.callback_query(F.data == "channel:templates", IsAdmin())
async def templates_menu(callback: CallbackQuery, session: AsyncSession):
    templates = list((await session.execute(select(ChannelContentTemplate).order_by(ChannelContentTemplate.id))).scalars())
    builder = InlineKeyboardBuilder()
    for template in templates:
        builder.row(InlineKeyboardButton(text=f"🧩 {template.title}", callback_data=f"channel:template:{template.id}"))
    builder.row(InlineKeyboardButton(text="🔙 مدیریت کانال", callback_data="channel:menu"))
    await callback.answer()
    await callback.message.edit_text("🧩 <b>قالب‌های پست</b>\n\nیک قالب انتخاب کن؛ در پیام بعدی مقدار متغیرها را با قالب <code>نام=مقدار</code> و هر مقدار در یک خط بفرست.", reply_markup=builder.as_markup())


@router.callback_query(F.data.regexp(r"^channel:template:\d+$"), IsAdmin())
async def template_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    template = await session.get(ChannelContentTemplate, int(callback.data.rsplit(":", 1)[1]))
    if not template:
        await callback.answer("قالب پیدا نشد.", show_alert=True); return
    await state.update_data(channel_template_id=template.id)
    await state.set_state(ChannelStates.waiting_template_values)
    await callback.answer()
    await callback.message.edit_text(f"<b>{template.title}</b>\n\nمتغیرها را وارد کن. نمونه:\n<code>service_name=سرویس طلایی\nprice=۱۰۰ هزار تومان\nbuy_link=https://example.com</code>", reply_markup=None)


@router.message(ChannelStates.waiting_template_values, IsAdmin())
async def save_template_content(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    template_id = data.get("channel_template_id")
    if not template_id:
        return
    template = await session.get(ChannelContentTemplate, template_id)
    values = {}
    for line in (message.text or "").splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    content = ChannelContent(channel_id=(await _channel(session)).id, title=template.title, content_type="text", body=render_template(template.body, values))
    session.add(content)
    await session.flush()
    await _event(session, content.id, "template_created")
    await session.commit()
    await state.clear()
    await message.answer(f"✅ پیش‌نویس قالب #{content.id} آماده شد.", reply_markup=_content_menu(content))


@router.callback_query(F.data.regexp(r"^channel:copy:\d+$"), IsAdmin())
async def copy_content(callback: CallbackQuery, session: AsyncSession):
    source = await session.get(ChannelContent, int(callback.data.rsplit(":", 1)[1]))
    if not source:
        await callback.answer("پست پیدا نشد.", show_alert=True); return
    clone = ChannelContent(channel_id=source.channel_id, title=f"کپی: {source.title}"[:255], content_type=source.content_type, body=source.body, media_file_id=source.media_file_id, show_caption_above_media=source.show_caption_above_media, buttons_json=source.buttons_json, poll_question=source.poll_question, poll_options_json=source.poll_options_json, poll_is_anonymous=source.poll_is_anonymous, poll_allows_multiple=source.poll_allows_multiple)
    session.add(clone); await session.flush(); await _event(session, clone.id, "copied"); await session.commit()
    await callback.answer("✅ کپی پیش‌نویس ساخته شد")
    await callback.message.edit_text(f"📂 <b>کپی پست #{source.id}</b>\n\nپیش‌نویس جدید: #{clone.id}", reply_markup=_content_menu(clone))


@router.callback_query(F.data.regexp(r"^channel:history:\d+$"), IsAdmin())
async def history(callback: CallbackQuery, session: AsyncSession):
    content_id = int(callback.data.rsplit(":", 1)[1])
    events = list((await session.execute(select(ChannelContentEvent).where(ChannelContentEvent.content_id == content_id).order_by(ChannelContentEvent.created_at.desc()).limit(20))).scalars())
    lines = [f"📜 <b>تاریخچه پست #{content_id}</b>", ""] + [f"• {event.event_type} — {event.created_at:%Y-%m-%d %H:%M}" for event in events]
    if not events: lines.append("هنوز رویدادی ثبت نشده است.")
    await callback.answer(); await callback.message.edit_text("\n".join(lines), reply_markup=_menu())


@router.callback_query(F.data == "channel:analytics", IsAdmin())
async def analytics(callback: CallbackQuery, session: AsyncSession):
    channel = await _channel(session)
    if not channel: await callback.answer("کانال تنظیم نشده است.", show_alert=True); return
    types = list((await session.execute(select(ChannelContent.content_type, func.count(ChannelContent.id)).where(ChannelContent.channel_id == channel.id).group_by(ChannelContent.content_type))).all())
    events = list((await session.execute(select(ChannelContentEvent.event_type, func.count(ChannelContentEvent.id)).join(ChannelContent).where(ChannelContent.channel_id == channel.id).group_by(ChannelContentEvent.event_type))).all())
    lines = ["📊 <b>تحلیل محتوا</b>", "", "نوع محتوا:"] + [f"• {kind}: <b>{count}</b>" for kind, count in types] + ["", "تاریخچه عملیات:"] + [f"• {kind}: <b>{count}</b>" for kind, count in events]
    await callback.answer(); await callback.message.edit_text("\n".join(lines), reply_markup=_menu())
