from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from app.bot.filters import IsAdmin
from app.bot.services.health_monitor import collect_health_report

router = Router(name=__name__)


@router.callback_query(IsAdmin(), F.data == "admin:health_monitor")
async def health_monitor(callback: CallbackQuery) -> None:
    report = await collect_health_report()

    text = (
        "📊 <b>گزارش سلامت ToonelVPN</b>\n\n"
        f"🖥 Host: <code>{report['hostname']}</code>\n"
        f"⏱ Uptime: <b>{report['uptime']}</b>\n"
        f"💾 Disk: <b>{report['disk_percent']}%</b>\n\n"
        "🟢 Event Loop: OK\n"
        "🟢 Python Runtime: OK"
    )

    await callback.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔄 بروزرسانی", callback_data="admin:health_monitor")]]
        ),
    )
    await callback.answer()
