from __future__ import annotations

import html
import json
import os

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.services.ai_content import (
    DEFAULT_SMART_RULES,
    RISK_LEVELS,
    SMART_CATEGORIES,
    AIContentError,
    AIContentService,
)
from app.db.models import AdvertisingChannel

router = Router(name=__name__)

RISK_LABELS = {
    "conservative": "🟢 محافظه‌کار",
    "balanced": "🟡 متعادل",
    "free": "🔴 آزاد",
}
DECISION_LABELS = {
    "auto": "⚡ خودکار",
    "approval": "✋ تأیید",
    "mandatory": "🚨 اجباری",
}
CATEGORY_ITEMS = list(SMART_CATEGORIES.items())
PAGE_SIZE = 8


def _menu(settings) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    mode = {"approval": "✋ تأیید من", "auto": "⚡ خودکار", "smart": "🧠 هوشمند"}.get(settings.mode, settings.mode)
    b.row(InlineKeyboardButton(text=f"🤖 حالت: {mode}", callback_data="ai_content:mode"))
    if settings.mode == "smart":
        b.row(InlineKeyboardButton(text="🧠 تنظیمات حالت هوشمند", callback_data="ai_content:smart:page:0"))
    b.row(InlineKeyboardButton(text="✨ تولید محتوا الآن", callback_data="ai_content:generate"))
    b.row(InlineKeyboardButton(text="📊 وضعیت AI", callback_data="ai_content:status"))
    b.row(InlineKeyboardButton(text="🔄 فعال/غیرفعال", callback_data="ai_content:toggle"))
    b.row(InlineKeyboardButton(text="🔙 مدیریت کانال", callback_data="channel:menu"))
    return b.as_markup()


async def _channel(session: AsyncSession):
    result = await session.execute(
        select(AdvertisingChannel)
        .where(AdvertisingChannel.is_active.is_(True))
        .order_by(AdvertisingChannel.id)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _settings(session: AsyncSession):
    service = AIContentService(os.getenv("OPENAI_API_KEY"))
    settings = await service.get_settings(session)
    return service, settings


def _rules(settings) -> dict[str, str]:
    return AIContentService.smart_rules(settings)


def _smart_menu(settings, page: int = 0) -> InlineKeyboardMarkup:
    rules = _rules(settings)
    total_pages = max(1, (len(CATEGORY_ITEMS) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    start = page * PAGE_SIZE
    items = CATEGORY_ITEMS[start : start + PAGE_SIZE]

    b = InlineKeyboardBuilder()
    for key, (label, _) in items:
        decision = rules.get(key, "approval")
        b.row(
            InlineKeyboardButton(
                text=f"{label}  {DECISION_LABELS[decision]}",
                callback_data=f"ai_content:smart:cat:{key}",
            )
        )
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️ قبلی", callback_data=f"ai_content:smart:page:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="بعدی ➡️", callback_data=f"ai_content:smart:page:{page + 1}"))
    if nav:
        b.row(*nav)
    b.row(
        InlineKeyboardButton(
            text=f"🎚️ سطح ریسک: {RISK_LABELS.get(settings.smart_risk_level, RISK_LABELS['balanced'])}",
            callback_data="ai_content:smart:risk",
        )
    )
    b.row(InlineKeyboardButton(text="🔄 بازگردانی تنظیمات پیش‌فرض", callback_data="ai_content:smart:reset"))
    b.row(InlineKeyboardButton(text="🔙 مدیریت محتوای AI", callback_data="channel:ai_content"))
    return b.as_markup()


def _smart_text(settings, page: int) -> str:
    rules = _rules(settings)
    total_pages = max(1, (len(CATEGORY_ITEMS) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    lines = [
        "🧠 <b>تنظیمات حالت هوشمند</b>",
        "",
        "AI ابتدا نوع محتوا و ریسک آن را تشخیص می‌دهد، سپس طبق این تنظیمات تصمیم می‌گیرد محتوا خودکار منتشر شود یا برای تأیید بیاید.",
        "",
        f"🎚️ سطح ریسک: <b>{RISK_LABELS.get(settings.smart_risk_level, RISK_LABELS['balanced'])}</b>",
        f"📄 صفحه {page + 1} از {total_pages}",
        "",
    ]
    for key, (label, _) in CATEGORY_ITEMS[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]:
        lines.append(f"{label} — <b>{DECISION_LABELS[rules.get(key, 'approval')]}</b>")
    lines.extend(["", "💡 با لمس هر دسته، تصمیم آن بین خودکار، تأیید و اجباری تغییر می‌کند."])
    return "\n".join(lines)


@router.callback_query(F.data == "channel:menu", IsAdmin())
async def channel_menu_with_ai(callback: CallbackQuery, session: AsyncSession):
    channel = await _channel(session)
    b = InlineKeyboardBuilder()
    b.row(InlineKeyboardButton(text="📝 ایجاد پست", callback_data="channel:content:create"))
    b.row(
        InlineKeyboardButton(text="📅 زمان‌بندی", callback_data="channel:content:scheduled"),
        InlineKeyboardButton(text="📂 پیش‌نویس‌ها", callback_data="channel:content:drafts"),
    )
    b.row(InlineKeyboardButton(text="📤 منتشرشده‌ها", callback_data="channel:content:published"))
    b.row(
        InlineKeyboardButton(text="🔥 فروش ویژه", callback_data="channel:special"),
        InlineKeyboardButton(text="⚡ اطلاعیه سرور", callback_data="channel:server_notice"),
    )
    b.row(
        InlineKeyboardButton(text="📊 نظرسنجی", callback_data="channel:poll:create"),
        InlineKeyboardButton(text="🧩 قالب‌ها", callback_data="channel:templates"),
    )
    b.row(
        InlineKeyboardButton(text="📈 آمار کانال", callback_data="channel:stats"),
        InlineKeyboardButton(text="📊 تحلیل محتوا", callback_data="channel:analytics"),
    )
    b.row(InlineKeyboardButton(text="🤖 مدیریت محتوای AI", callback_data="channel:ai_content"))
    b.row(InlineKeyboardButton(text="⚙️ تنظیمات کانال", callback_data="channel:settings"))
    b.row(InlineKeyboardButton(text="🔙 مرکز تبلیغات", callback_data="advertising:menu"))
    text = "📢 <b>مدیریت کانال</b>\n\n"
    if channel:
        text += f"📣 کانال: <b>{html.escape(channel.title)}</b>\n🆔 <code>{channel.chat_id}</code>\n🟢 اتصال فعال"
    else:
        text += "⚠️ هنوز کانالی برای انتشار تنظیم نشده است.\nابتدا از «⚙️ تنظیمات کانال» کانال را متصل کن."
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=b.as_markup())


@router.callback_query(F.data == "channel:ai_content", IsAdmin())
async def ai_menu(callback: CallbackQuery, session: AsyncSession):
    _, settings = await _settings(session)
    await session.commit()
    enabled = "🟢 فعال" if settings.enabled else "🔴 غیرفعال"
    await callback.answer()
    await callback.message.edit_text(
        f"🤖 <b>مدیریت محتوای AI</b>\n\nوضعیت: {enabled}\nمدل: <code>{html.escape(settings.model)}</code>\nپست روزانه: {settings.posts_per_day}\nتولید خودکار زمان‌بندی‌شده: {'🟢 فعال' if settings.auto_schedule else '🔴 خاموش'}\n\nAI می‌تواند محتوا را به‌صورت پیش‌نویس بسازد یا طبق حالت انتخابی وارد صف انتشار شود.",
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
    await callback.message.edit_text(
        f"🤖 <b>حالت انتشار AI</b>\n\nحالت فعلی: <b>{settings.mode}</b>",
        reply_markup=b.as_markup(),
    )


@router.callback_query(F.data.regexp(r"^ai_content:setmode:(approval|auto|smart)$"), IsAdmin())
async def set_mode(callback: CallbackQuery, session: AsyncSession):
    _, settings = await _settings(session)
    settings.mode = callback.data.rsplit(":", 1)[1]
    settings.auto_schedule = settings.mode in {"auto", "smart"}
    await session.commit()
    await callback.answer("حالت ذخیره شد")
    await ai_menu(callback, session)


@router.callback_query(F.data.regexp(r"^ai_content:smart:page:\d+$"), IsAdmin())
async def smart_page(callback: CallbackQuery, session: AsyncSession):
    _, settings = await _settings(session)
    page = int(callback.data.rsplit(":", 1)[1])
    await callback.answer()
    await callback.message.edit_text(_smart_text(settings, page), reply_markup=_smart_menu(settings, page))


@router.callback_query(F.data.regexp(r"^ai_content:smart:cat:[a-z_]+$"), IsAdmin())
async def smart_category(callback: CallbackQuery, session: AsyncSession):
    _, settings = await _settings(session)
    key = callback.data.rsplit(":", 1)[1]
    if key not in SMART_CATEGORIES:
        await callback.answer("دسته نامعتبر است.", show_alert=True)
        return
    rules = _rules(settings)
    order = ["auto", "approval", "mandatory"]
    current = rules.get(key, DEFAULT_SMART_RULES[key])
    rules[key] = order[(order.index(current) + 1) % len(order)]
    settings.smart_rules = json.dumps(rules, ensure_ascii=False)
    await session.commit()
    page = next((i // PAGE_SIZE for i, (item_key, _) in enumerate(CATEGORY_ITEMS) if item_key == key), 0)
    await callback.answer(f"{SMART_CATEGORIES[key][0]} → {DECISION_LABELS[rules[key]]}")
    await callback.message.edit_text(_smart_text(settings, page), reply_markup=_smart_menu(settings, page))


@router.callback_query(F.data == "ai_content:smart:risk", IsAdmin())
async def smart_risk(callback: CallbackQuery, session: AsyncSession):
    _, settings = await _settings(session)
    order = ["conservative", "balanced", "free"]
    current = settings.smart_risk_level if settings.smart_risk_level in RISK_LEVELS else "balanced"
    settings.smart_risk_level = order[(order.index(current) + 1) % len(order)]
    await session.commit()
    await callback.answer(f"سطح ریسک: {RISK_LABELS[settings.smart_risk_level]}")
    await callback.message.edit_text(_smart_text(settings, 0), reply_markup=_smart_menu(settings, 0))


@router.callback_query(F.data == "ai_content:smart:reset", IsAdmin())
async def smart_reset(callback: CallbackQuery, session: AsyncSession):
    _, settings = await _settings(session)
    settings.smart_rules = json.dumps(DEFAULT_SMART_RULES, ensure_ascii=False)
    settings.smart_risk_level = "balanced"
    await session.commit()
    await callback.answer("تنظیمات هوشمند به پیش‌فرض برگشت")
    await callback.message.edit_text(_smart_text(settings, 0), reply_markup=_smart_menu(settings, 0))


@router.callback_query(F.data == "ai_content:generate", IsAdmin())
async def generate(callback: CallbackQuery, session: AsyncSession):
    channel = await _channel(session)
    if not channel:
        await callback.answer("ابتدا کانال را متصل کن.", show_alert=True)
        return

    service, settings = await _settings(session)
    if not settings.enabled:
        await callback.answer("AI غیرفعال است. ابتدا آن را فعال کن.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        "⏳ <b>در حال تولید محتوا با AI...</b>\n\nلطفاً چند لحظه صبر کنید.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 مدیریت AI", callback_data="channel:ai_content")],
            ]
        ),
    )

    try:
        content = await service.create_content(session, channel.id, settings)
        service.schedule_next(settings)
        await session.commit()
    except AIContentError as exc:
        await session.rollback()
        await callback.message.edit_text(
            f"❌ <b>تولید محتوا انجام نشد</b>\n\n{html.escape(str(exc))}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 تلاش دوباره", callback_data="ai_content:generate")],
                    [InlineKeyboardButton(text="🤖 مدیریت AI", callback_data="channel:ai_content")],
                ]
            ),
        )
        return
    except Exception as exc:
        await session.rollback()
        await callback.message.edit_text(
            f"❌ <b>خطا در تولید محتوا</b>\n\n{html.escape(str(exc))}",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔄 تلاش دوباره", callback_data="ai_content:generate")],
                    [InlineKeyboardButton(text="🤖 مدیریت AI", callback_data="channel:ai_content")],
                ]
            ),
        )
        return

    await callback.message.edit_text(
        f"✅ <b>محتوای AI #{content.id} ساخته شد</b>\n\n🏷 {html.escape(content.title)}\n📌 وضعیت: <b>{html.escape(content.status)}</b>\n🔘 دکمه‌ها: {len(content.buttons)}\n\n{html.escape(content.body)}\n\n" + ("✋ در پیش‌نویس‌ها منتظر تأیید شماست." if content.status == "draft" else "⚡ برای انتشار وارد صف زمان‌بندی شد."),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📂 پیش‌نویس‌ها", callback_data="channel:content:drafts")],
                [InlineKeyboardButton(text="🤖 مدیریت AI", callback_data="channel:ai_content")],
            ]
        ),
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
        f"تولید خودکار: {'بله' if settings.auto_schedule else 'خیر'}\n"
        f"پست در روز: {settings.posts_per_day}\n"
        f"سطح ریسک هوشمند: {RISK_LABELS.get(settings.smart_risk_level, RISK_LABELS['balanced'])}\n"
        f"آخرین تولید: {settings.last_run_at or 'هنوز اجرا نشده'}",
        reply_markup=_menu(settings),
    )
