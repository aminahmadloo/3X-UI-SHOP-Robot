from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.services.ai_content import AIContentError, AIContentService
from app.db.models import AdvertisingChannel
from app.config import Config
from sqlalchemy import select

router = Router(name=__name__)


def _menu(settings) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    mode = {"approval": "✋ تأیید من", "auto": "⚡ خودکار", "smart": "🧠 هوشمند"}.get(settings.mode, settings.mode)
    b.row(InlineKeyboardButton(text=f"🤖 حالت: {mode}", callback_data="ai_content:mode"))
    b.row(InlineKeyboardButton(text="✨ تولید محتوا الآن", callback_data="ai_content:generate"))
    b.row(InlineKeyboardButton(text="📊 وضعیت AI", callback_data="ai_content:status"))
    b.row(InlineKeyboardButton(text="🔄 فعال/غیرفعال", callback_data="ai_content:toggle"))
    return b.as_markup()


async def _channel(session: AsyncSession):
    result = await session.execute(select(AdvertisingChannel).where(AdvertisingChannel.is_active.is_(True)).order_by(AdvertisingChannel.id).limit(1))
    return result.scalar_one_or_none()


async def _settings(session: AsyncSession):
    service = AIContentService(None)
    settings = await service.get_settings(session)
    return service, settings


@router.callback_query(F.data == "channel:ai_content", IsAdmin())
async def ai_menu(callback: CallbackQuery, session: AsyncSession):
    service, settings = await _settings(session)
    await session.commit()
    enabled = "🟢 فعال" if settings.enabled else "🔴 غیرفعال"
    await callback.answer()
    await callback.message.edit_text(
        f"🤖 <b>مدیریت محتوای AI</b>\n\nوضعیت: {enabled}\nمدل: <code>{html.escape(settings.model)}</code>\nپست روزانه: {settings.posts_per_day}\n\nAI می‌تواند محتوا را به‌صورت پیش‌نویس بسازد یا طبق حالت انتخابی مستقیماً وارد زمان‌بندی انتشار کند.",
        reply_markup=_menu(settings),
    )


@router.callback_query(F.data == "ai_content:toggle", IsAdmin())
async def toggle(callback: CallbackQuery, session: AsyncSession):
    _, settings = await _settings(session)
    settings.enabled = not settings.enabled
    await session.commit()
    await callback.answer("فعال شد" if settings.enabled else "غیرفعال شد")
    await ai_menu(callback, session)


@router.callback_query(F.data == "ai_content:mode", IsAdmin())
async def mode(callback: CallbackQuery, session: AsyncSession):
    _, settings = await _settings(session)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="✋ همه با تأیید من", callback_data="ai_content:setmode:approval"))
    b.row(InlineKeyboardButton(text="⚡ انتشار خودکار", callback_data="ai_content:setmode:auto"))
    b.row(InlineKeyboardButton(text="🧠 حالت هوشمند", callback_data="ai_content:setmode:smart"))
    b.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="channel:ai_content"))
    await callback.answer()
    await callback.message.edit_text(f"🤖 <b>حالت انتشار AI</b>\n\nحالت فعلی: <b>{settings.mode}</b>", reply_markup=b.as_markup())


@router.callback_query(F.data.regexp(r"^ai_content:setmode:(approval|auto|smart)$"), IsAdmin())
async def set_mode(callback: CallbackQuery, session: AsyncSession):
    _, settings = await _settings(session)
    settings.mode = callback.data.rsplit(":", 1)[1]
    await session.commit()
    await callback.answer("حالت ذخیره شد")
    await ai_menu(callback, session)


@router.callback_query(F.data == "ai_content:generate", IsAdmin())
async def generate(callback: CallbackQuery, session: AsyncSession, config: Config):
    channel = await _channel(session)
    if not channel:
        await callback.answer("ابتدا کانال را متصل کن.", show_alert=True)
        return
    service, settings = await _settings(session)
    if not config.bot.TOKEN:
        await callback.answer("تنظیمات ربات ناقص است.", show_alert=True)
        return
    try:
        content = await service.create_content(session, channel.id, settings)
        service.schedule_next(settings)
        await session.commit()
    except AIContentError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    except Exception as exc:
        await session.rollback()
        await callback.answer(f"خطا در تولید محتوا: {exc}", show_alert=True)
        return
    await callback.answer("محتوا ساخته شد")
    await callback.message.edit_text(
        f"✅ <b>محتوای AI #{content.id} ساخته شد</b>\n\n🏷 {html.escape(content.title)}\n📌 هدف: {html.escape(str(content.status))}\n\n{html.escape(content.body)}\n\n🔘 دکمه‌ها: {len(content.buttons)}\n\n" + ("✋ برای تأیید شما در پیش‌نویس‌ها قرار گرفت." if content.status == "draft" else "⚡ برای انتشار خودکار وارد زمان‌بندی شد."),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📂 پیش‌نویس‌ها", callback_data="channel:content:drafts")]]),
    )


@router.callback_query(F.data == "ai_content:status", IsAdmin())
async def status(callback: CallbackQuery, session: AsyncSession):
    _, settings = await _settings(session)
    await session.commit()
    await callback.answer()
    await callback.message.edit_text(
        "🤖 <b>وضعیت AI</b>\n\n"
        f"فعال: {'بله' if settings.enabled else 'خیر'}\n"
        f"حالت: {settings.mode}\n"
        f"مدل: {settings.model}\n"
        f"پست در روز: {settings.posts_per_day}\n"
        f"آخرین تولید: {settings.last_run_at or 'هنوز اجرا نشده'}",
        reply_markup=_menu(settings),
    )
