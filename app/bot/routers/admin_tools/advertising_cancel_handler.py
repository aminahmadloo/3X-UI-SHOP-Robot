from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery

from app.bot.filters import IsAdmin
from app.bot.routers.admin_tools.advertising_builder_handler import menu_keyboard

router = Router(name=__name__)


@router.callback_query(F.data == "advertising:cancel", IsAdmin())
async def cancel_advertising_builder(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel every step of the advertising builder and return to its menu."""
    await state.clear()
    await callback.answer("لغو شد")
    await callback.message.edit_text(
        "❌ <b>ساخت تبلیغ لغو شد.</b>",
        reply_markup=menu_keyboard(),
    )


@router.callback_query(F.data == "advertising:manage:cancel", IsAdmin())
async def cancel_advertising_button_edit(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel an in-progress custom-button edit/add flow."""
    await state.clear()
    await callback.answer("لغو شد")
    await callback.message.edit_text(
        "❌ <b>عملیات افزودن دکمه لغو شد.</b>",
        reply_markup=menu_keyboard(),
    )
