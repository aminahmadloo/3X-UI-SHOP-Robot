from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.filters import IsAdmin
from app.bot.services.system_health import get_system_health_report
from app.bot.utils.navigation import NavAdminTools

router = Router(name=__name__)


@router.callback_query(F.data == "system_health", IsAdmin())
async def system_health_callback(callback: CallbackQuery) -> None:
    await callback.answer()

    data = await get_system_health_report()

    disk = data.get("disk", {})

    text = (
        "🩺 <b>سلامت سیستم</b>\n\n"
        f"🟢 وضعیت: <b>{data.get('status')}</b>\n"
        f"🖥 هاست: <code>{data.get('hostname')}</code>\n"
        f"🐍 Python: <code>{data.get('python')}</code>\n"
        f"⚙️ CPU: <b>{data.get('cpu_count')}</b>\n\n"
        "💾 دیسک:\n"
        f"• کل: {disk.get('total')}\n"
        f"• مصرف شده: {disk.get('used')}\n"
        f"• آزاد: {disk.get('free')}\n\n"
        "🌍 نودها:\n"
    )

    for node in data.get("nodes", []):
        node_status = node.get("status")
        icon = "🟢" if node_status else "🔴"
        text += f"{icon} {node.get('name')}: {node_status}\n"

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 بروزرسانی",
                    callback_data="system_health",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت",
                    callback_data=NavAdminTools.MAIN,
                )
            ],
        ]
    )

    await callback.message.edit_text(
        text,
        reply_markup=kb,
    )
