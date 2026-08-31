from urllib.parse import urlencode

from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.routers.misc.keyboard import back_to_main_menu_button
from app.bot.utils.navigation import NavDownload


def referral_keyboard(
    referral_link: str | None = None,
    connect: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if referral_link:
        builder.row(
            InlineKeyboardButton(
                text="📋 کپی لینک دعوت",
                copy_text=CopyTextButton(text=referral_link),
            ),
            InlineKeyboardButton(
                text="📨 دعوت دوستان",
                url=(
                    "https://t.me/share/url?"
                    + urlencode(
                        {
                            "url": referral_link,
                            "text": (
                                "من به‌تازگی مشتری تونلVPN شدم و از کیفیت سرویس‌هاش واقعاً راضی‌ام. "
                                "پینگ عالی، سرعت مناسب و قیمت‌های مقرون‌به‌صرفه از مزیت‌های این سرویسه.\n"
                                "اگر دوست داشتی تو هم امتحانش کنی، از طریق لینک زیر وارد شو و خریدت رو انجام بده:\n\n"
                                f"🔗 {referral_link}"
                            ),
                        }
                    )
                ),
            ),
        )

    if connect:
        builder.row(
            InlineKeyboardButton(
                text=_("subscription:button:connect"),
                callback_data=NavDownload.MAIN,
            )
        )
    builder.row(back_to_main_menu_button())

    return builder.as_markup()
