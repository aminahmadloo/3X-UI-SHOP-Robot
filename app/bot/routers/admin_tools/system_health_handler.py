from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.filters import IsAdmin
from app.bot.services.system_health import get_system_health_report

router = Router(name=__name__)


@router.callback_query(F.data == "system_health", IsAdmin())
async def system_health(callback: CallbackQuery) -> None:
    report = await get_system_health_report()
    text = (
        "🖥 <b>گزارش سلامت سیستم</b>\n\n"
        f"✅ وضعیت: {report['status']}\n"
        f"🖥 میزبان: <code>{report['hostname']}</code>\n"
        f"🐍 Python: <code>{report['python']}</code>\n"
        f"⏱ Uptime: <code>{report['uptime_seconds']}s</code>"
    )
    await callback.answer()
    await callback.message.edit_text(text)
