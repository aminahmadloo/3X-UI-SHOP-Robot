from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.utils.navigation import NavMain


def wallet_keyboard(amounts) -> InlineKeyboardMarkup:
    rows = []
    for item in amounts:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"💰 {item.amount:,} تومان",
                    callback_data=f"wallet:topup:{item.id}",
                )
            ]
        )

    rows.append(
        [InlineKeyboardButton(text="🔄 بروزرسانی", callback_data=NavMain.WALLET)]
    )
    rows.append(
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavMain.MAIN_MENU)]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
