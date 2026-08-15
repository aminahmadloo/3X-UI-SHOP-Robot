from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.utils.navigation import NavMain


def wallet_keyboard(amounts, language: str = "fa") -> InlineKeyboardMarkup:
    if language == "en":
        refresh_text = "🔄 Refresh"
        back_text = "🔙 Back"
        custom_text = "💰 Custom amount"
    elif language == "ru":
        refresh_text = "🔄 Обновить"
        back_text = "🔙 Назад"
        custom_text = "💰 Своя сумма"
    else:
        refresh_text = "🔄 بروزرسانی"
        back_text = "🔙 بازگشت"
        custom_text = "💰 مبلغ دلخواه"

    rows = []
    for item in amounts:
        if language == "en":
            label = f"💰 {item.amount:,} Toman"
        elif language == "ru":
            label = f"💰 {item.amount:,} томан"
        else:
            label = f"💰 {item.amount:,} تومان"

        rows.append(
            [
                InlineKeyboardButton(
                    text=label,
                    callback_data=f"wallet:topup:{item.id}",
                )
            ]
        )

    rows.append(
        [
            InlineKeyboardButton(
                text=custom_text,
                callback_data="wallet:custom",
            )
        ]
    )
    rows.append([InlineKeyboardButton(text=refresh_text, callback_data=NavMain.WALLET)])
    rows.append([InlineKeyboardButton(text=back_text, callback_data=NavMain.MAIN_MENU)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
