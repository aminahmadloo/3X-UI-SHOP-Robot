"""Guard command messages while creating a special-offer campaign."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.filters import IsAdmin
from .special_offer_handler import SpecialOfferStates


router = Router(name=__name__)


@router.message(SpecialOfferStates.waiting_campaign_title, IsAdmin(), F.text.startswith("/"))
async def guard_special_offer_campaign_command(
    message: Message,
    state: FSMContext,
) -> None:
    """Never treat Telegram commands such as /start as campaign titles."""
    await state.clear()
    await message.answer(
        "❌ این پیام یک دستور تلگرام است و نمی‌تواند عنوان فروش ویژه باشد.\n\n"
        "برای ایجاد فروش ویژه دوباره وارد بخش «ایجاد فروش‌های ویژه» شوید و عنوان را به‌صورت متن ارسال کنید."
    )
