from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools

router = Router(name=__name__)


@router.callback_query(F.data == NavAdminTools.MAIN, IsAdmin())
async def keep_system_health_extension(callback: CallbackQuery) -> None:
    # Extension point reserved for unified system administration menu.
    await callback.answer()
