"""V2 controls layered over the original channel-management workflow."""
from __future__ import annotations

import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.routers.admin_tools.channel_management_handler import ChannelStates, _channel, _content_menu, _menu
from app.bot.services.channel_templates import (
    create_draft_from_template,
    template_variables,
    variable_assignment_text,
)
from app.db.models import ChannelContent, ChannelContentEvent, ChannelContentTemplate

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
    await callback.message.edit_text("🧩 <b>قالب‌های پست</b>\n\nیک قالب را انتخاب کن تا کاربرد، متغیرها و مسیر ساخت پست آن را ببینی.", reply_markup=builder.as_markup())


@router.callback_query(F.data.regexp(r"^channel:template:\d+$"), IsAdmin())
async def template_details(callback: CallbackQuery, session: AsyncSession):
    template = await session.get(ChannelContentTemplate, int(callback.data.rsplit(":", 1)[1]))
    if not template:
        await callback.answer("قالب پیدا نشد.", show_alert=True)
        return
    variables = template_variables(template.variable_definitions)
    variable_lines = []
    for item in variables:
        required = "ضروری" if item.get("required", True) else "اختیاری"
        variable_lines.append(f"<code>{{{item['key']}}}</code> — <b>{item['label']}</b> ({required})\n{item.get('description', '')}\nمثال: <code>{item.get('example', '')}</code>")
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📝 ساخت پست از قالب", callback_data=f"channel:template:create:{template.id}"))
    builder.row(InlineKeyboardButton(text="📋 کپی متغیرها", callback_data=f"channel:template:copy_vars:{template.id}"))
    builder.row(InlineKeyboardButton(text="✏️ ویرایش قالب", callback_data=f"channel:template:edit:{template.id}"))
    builder.row(InlineKeyboardButton(text="⬅️ بازگشت", callback_data="channel:templates"))
    text = f"<b>{template.title}</b>\n\n<b>کاربرد:</b>\n{template.purpose or 'بدون توضیح'}\n\n<b>متغیرهای قابل استفاده:</b>\n\n" + ("\n\n".join(variable_lines) or "این قالب متغیر مستندی ندارد.")
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.regexp(r"^channel:template:copy_vars:\d+$"), IsAdmin())
async def copy_template_variables(callback: CallbackQuery, session: AsyncSession):
    template = await session.get(ChannelContentTemplate, int(callback.data.rsplit(":", 1)[1]))
    if not template:
        await callback.answer("قالب پیدا نشد.", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(f"📋 <b>متغیرهای {template.title}</b>\n\n<code>{variable_assignment_text(template.variable_definitions)}</code>")


async def _ask_next_template_value(message: Message, state: FSMContext, template: ChannelContentTemplate) -> None:
    data = await state.get_data()
    required = [item for item in template_variables(template.variable_definitions) if item.get("required", True)]
    index = data.get("channel_template_value_index", 0)
    item = required[index]
    await message.answer(f"<b>{item['label']}؟</b>\n{item.get('description', '')}\nمثال: <code>{item.get('example', '')}</code>", reply_markup=None)


@router.callback_query(F.data.regexp(r"^channel:template:create:\d+$"), IsAdmin())
async def template_create_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    template = await session.get(ChannelContentTemplate, int(callback.data.rsplit(":", 1)[1]))
    if not template:
        await callback.answer("قالب پیدا نشد.", show_alert=True)
        return
    required = [item for item in template_variables(template.variable_definitions) if item.get("required", True)]
    await state.update_data(channel_template_id=template.id, channel_template_values={}, channel_template_value_index=0)
    await callback.answer()
    if not required:
        await _finish_template_draft(callback.message, state, session, template, {})
        return
    await state.set_state(ChannelStates.waiting_template_value)
    await callback.message.edit_text("📝 <b>ساخت پست از قالب</b>\n\nمقادیر ضروری را مرحله‌به‌مرحله وارد کن.")
    await _ask_next_template_value(callback.message, state, template)


async def _finish_template_draft(message: Message, state: FSMContext, session: AsyncSession, template: ChannelContentTemplate, values: dict[str, str]) -> None:
    channel = await _channel(session)
    if not channel:
        await message.answer("⚠️ ابتدا یک کانال فعال در تنظیمات کانال انتخاب کن.", reply_markup=_menu())
        await state.clear()
        return
    content = create_draft_from_template(template, channel.id, values)
    session.add(content)
    await session.flush()
    await _event(session, content.id, "template_created")
    await session.commit()
    await state.clear()
    await message.answer(f"📝 <b>پیش‌نمایش پست</b>\n\n{content.body}\n\n✅ پیش‌نویس قالب #{content.id} ذخیره شد.", reply_markup=_content_menu(content))


@router.message(ChannelStates.waiting_template_value, IsAdmin())
async def save_template_value(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    template = await session.get(ChannelContentTemplate, data.get("channel_template_id"))
    if not template:
        await state.clear()
        return
    required = [item for item in template_variables(template.variable_definitions) if item.get("required", True)]
    index = data.get("channel_template_value_index", 0)
    value = (message.text or "").strip()
    if not value:
        await message.answer("❌ مقدار ضروری است؛ لطفاً یک مقدار وارد کن.")
        return
    values = data.get("channel_template_values", {})
    values[required[index]["key"]] = value
    index += 1
    await state.update_data(channel_template_values=values, channel_template_value_index=index)
    if index < len(required):
        await _ask_next_template_value(message, state, template)
        return
    await _finish_template_draft(message, state, session, template, values)


@router.callback_query(F.data.regexp(r"^channel:template:edit:\d+$"), IsAdmin())
async def edit_template_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    template = await session.get(ChannelContentTemplate, int(callback.data.rsplit(":", 1)[1]))
    if not template:
        await callback.answer("قالب پیدا نشد.", show_alert=True)
        return
    await state.update_data(channel_template_id=template.id)
    await state.set_state(ChannelStates.waiting_template_body)
    await callback.answer()
    await callback.message.edit_text(f"✏️ <b>ویرایش قالب {template.title}</b>\n\nمتن جدید قالب را ارسال کن. متغیرهای مستند این قالب حفظ می‌شوند.\n\nمتن فعلی:\n<code>{template.body}</code>")


@router.message(ChannelStates.waiting_template_body, IsAdmin())
async def edit_template_save(message: Message, state: FSMContext, session: AsyncSession):
    template = await session.get(ChannelContentTemplate, (await state.get_data()).get("channel_template_id"))
    body = (message.text or "").strip()
    if not template or not body:
        await message.answer("❌ متن قالب نمی‌تواند خالی باشد.")
        return
    documented = {item["key"] for item in template_variables(template.variable_definitions)}
    unsupported = set(re.findall(r"\{([a-z][a-z0-9_]*)\}", body)) - documented
    if unsupported:
        await message.answer("❌ این متغیرها برای قالب مستند نشده‌اند: " + "، ".join(sorted(unsupported)))
        return
    template.body = body
    await session.commit()
    await state.clear()
    await message.answer("✅ قالب ذخیره شد.", reply_markup=_menu())


@router.callback_query(F.data.regexp(r"^channel:save_draft:\d+$"), IsAdmin())
async def confirm_draft_saved(callback: CallbackQuery, session: AsyncSession):
    content = await session.get(ChannelContent, int(callback.data.rsplit(":", 1)[1]))
    if not content or content.status != "draft":
        await callback.answer("پیش‌نویس پیدا نشد.", show_alert=True)
        return
    await callback.answer("✅ پیش‌نویس ذخیره شده است.")


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
