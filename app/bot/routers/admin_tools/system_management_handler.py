from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.services.system_monitor import collect_system_health
from app.bot.utils.navigation import NavAdminTools

router = Router(name=__name__)


@router.callback_query(F.data == "system_management")
async def system_management(callback: CallbackQuery):
    report = await collect_system_health()
    await callback.message.edit_text(
        report.render(),
        reply_markup=None,
    )
    await callback.answer()


@router.callback_query(F.data == "system_health_refresh")
async def system_health_refresh(callback: CallbackQuery):
    report = await collect_system_health()
    await callback.message.edit_text(report.render())
    await callback.answer()
