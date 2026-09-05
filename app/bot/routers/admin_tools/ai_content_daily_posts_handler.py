from __future__ import annotations

from aiogram import F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.services.ai_content import AIContentService
from app.bot.routers.admin_tools import ai_content_handler


MIN_POSTS_PER_DAY = 1
MAX_POSTS_PER_DAY = 24


# Extend the existing AI menu without duplicating the main AI router.
_original_menu = ai_content_handler._menu


def _menu_with_daily_posts(settings) -> InlineKeyboardMarkup:
    markup = _original_menu(settings)
    rows = list(markup.inline_keyboard)
    rows.insert(
        2,
        [
            InlineKeyboardButton(
                text=f"📝 پست روزانه: {settings.posts_per_day}",
                callback_data="ai_content:posts",
            )
        ],
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


ai_content_handler._menu = _menu_with_daily_posts
router = ai_content_handler.router


def _posts_menu(current: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(text="➖", callback_data="ai_content:posts:dec"),
        InlineKeyboardButton(text=f"📝 {current} پست در روز", callback_data="ai_content:posts"),
        InlineKeyboardButton(text="➕", callback_data="ai_content:posts:inc"),
    )
    b.row(InlineKeyboardButton(text="🔙 مدیریت محتوای AI", callback_data="channel:ai_content"))
    return b.as_markup()


async def _show_posts(callback: CallbackQuery, session: AsyncSession) -> None:
    service = AIContentService()
    settings = await service.get_settings(session)
    await callback.answer()
    await callback.message.edit_text(
        "📝 <b>تعداد پست روزانه</b>\n\n"
        "تعداد تولید خودکار AI را برای هر شبانه‌روز مشخص کن.\n"
        f"\nمقدار فعلی: <b>{settings.posts_per_day}</b> پست در روز\n"
        "\nبازه مجاز: <b>۱ تا ۲۴</b> پست در روز.",
        reply_markup=_posts_menu(settings.posts_per_day),
    )


@router.callback_query(F.data == "ai_content:posts", IsAdmin())
async def daily_posts_menu(callback: CallbackQuery, session: AsyncSession):
    await _show_posts(callback, session)


@router.callback_query(F.data.regexp(r"^ai_content:posts:(inc|dec)$"), IsAdmin())
async def change_daily_posts(callback: CallbackQuery, session: AsyncSession):
    service = AIContentService()
    settings = await service.get_settings(session)
    direction = callback.data.rsplit(":", 1)[1]
    current = max(MIN_POSTS_PER_DAY, min(settings.posts_per_day, MAX_POSTS_PER_DAY))
    new_value = current + (1 if direction == "inc" else -1)

    if new_value < MIN_POSTS_PER_DAY or new_value > MAX_POSTS_PER_DAY:
        await callback.answer(
            "حد مجاز: ۱ تا ۲۴ پست در روز.",
            show_alert=True,
        )
        return

    settings.posts_per_day = new_value
    if settings.auto_schedule:
        service.schedule_next(settings)
    await session.commit()

    await callback.answer(f"تعداد پست روزانه روی {new_value} تنظیم شد.")
    await callback.message.edit_text(
        "📝 <b>تعداد پست روزانه</b>\n\n"
        "تعداد تولید خودکار AI را برای هر شبانه‌روز مشخص کن.\n"
        f"\nمقدار فعلی: <b>{new_value}</b> پست در روز\n"
        "\nبازه مجاز: <b>۱ تا ۲۴</b> پست در روز.",
        reply_markup=_posts_menu(new_value),
    )
