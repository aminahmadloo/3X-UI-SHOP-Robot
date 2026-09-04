from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.routers.admin_tools.channel_management_handler import _show_menu

router = Router(name=__name__)


@router.callback_query(F.data == "channel:menu", IsAdmin())
async def channel_menu_with_campaigns(callback: CallbackQuery, session: AsyncSession):
    await callback.answer()
    await _show_menu(callback, session)
    markup = callback.message.reply_markup
    builder = InlineKeyboardBuilder()
    if markup:
        for row in markup.inline_keyboard:
            builder.row(*row)
    builder.row(InlineKeyboardButton(text="🎯 کمپین‌ها", callback_data="campaign:menu"))
    builder.row(InlineKeyboardButton(text="📈 رشد کانال", callback_data="campaign:channel_growth"))
    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
