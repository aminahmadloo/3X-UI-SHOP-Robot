from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton

from app.bot.filters import IsAdmin, IsDev
from app.bot.routers.admin_tools.keyboard import admin_tools_keyboard
from app.bot.utils.navigation import NavAdminTools
from app.db.models import User

router = Router(name=__name__)


@router.callback_query(F.data == NavAdminTools.MAIN, IsAdmin())
async def payment_gateway_settings_admin_menu(callback: CallbackQuery, user: User) -> None:
    is_dev = await IsDev()(user_id=user.tg_id)
    markup = admin_tools_keyboard(is_dev)
    markup.inline_keyboard.insert(
        3,
        [InlineKeyboardButton(text="💳 تنظیمات درگاه‌های پرداخت", callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS)],
    )
    await callback.answer()
    await callback.message.edit_text(text="🛠 <b>ابزارهای مدیریت</b>", reply_markup=markup)
