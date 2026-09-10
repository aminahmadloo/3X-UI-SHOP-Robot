import platform
import time

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools
from app.db.models import User

router = Router(name=__name__)

_STARTED_AT = time.time()


def system_health_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 بروزرسانی گزارش", callback_data="system_health:refresh")],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)],
        ]
    )


async def build_system_health_text() -> str:
    uptime = int(time.time() - _STARTED_AT)
    hours, rem = divmod(uptime, 3600)
    minutes, _ = divmod(rem, 60)

    return (
        "🖥 <b>گزارش سلامت سیستم ToonelVPN</b>\n\n"
        "🤖 Bot: 🟢 Running\n"
        f"⏱ Uptime: <b>{hours}h {minutes}m</b>\n"
        f"🐍 Python: <code>{platform.python_version()}</code>\n"
        f"🖥 Host: <code>{platform.node()}</code>\n\n"
        "📦 بررسی‌های تکمیلی دیتابیس، Redis و Nodeها در نسخه بعدی این ماژول اضافه می‌شود."
    )


@router.callback_query(F.data == "system_health:menu", IsAdmin())
async def system_health_menu(callback: CallbackQuery, user: User) -> None:
    await callback.answer()
    await callback.message.edit_text(
        await build_system_health_text(),
        reply_markup=system_health_keyboard(),
    )


@router.callback_query(F.data == "system_health:refresh", IsAdmin())
async def system_health_refresh(callback: CallbackQuery) -> None:
    await callback.answer("بروزرسانی شد")
    await callback.message.edit_text(
        await build_system_health_text(),
        reply_markup=system_health_keyboard(),
    )
