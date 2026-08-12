from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.i18n import I18n, gettext as _

from app.bot.filters.is_admin import IsAdmin
from app.bot.models import ServicesContainer
from app.bot.routers.main_menu.keyboard import main_menu_keyboard
from app.bot.utils.navigation import NavMain
from app.db.models.user import User

router = Router()

MAIN_MESSAGE_ID_KEY = "main_message_id"


@router.callback_query(F.data == NavMain.CUSTOM_SERVICE)
async def callback_custom_service(callback: CallbackQuery) -> None:
    await callback.answer("🚧 خرید سرویس با مشخصات دلخواه به‌زودی فعال می‌شود.", show_alert=True)


@router.callback_query(F.data == NavMain.MY_SERVICES)
async def callback_my_services(callback: CallbackQuery) -> None:
    await callback.answer("📦 بخش سرویس های من به‌زودی فعال می‌شود.", show_alert=True)


@router.callback_query(F.data == NavMain.WALLET)
async def callback_wallet(callback: CallbackQuery) -> None:
    await callback.answer("💰 کیف پول به‌زودی فعال می‌شود.", show_alert=True)
