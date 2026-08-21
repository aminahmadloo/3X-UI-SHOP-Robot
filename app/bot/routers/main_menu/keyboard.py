from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.utils.navigation import (
    NavAdminTools,
    NavMain,
    NavProfile,
    NavReferral,
    NavSubscription,
    NavSupport,
)


def main_menu_keyboard(
    is_admin: bool = False,
    is_referral_available: bool = False,
    is_trial_available: bool = False,
    is_referred_trial_available: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    # Main menu layout:
    # 1. Buy Service
    # 2. Custom Service
    # 3. My Services + Wallet
    # 4. Renew Service + Add Traffic
    # 5. Account + Referral
    # 6. Support + Language
    # 7. Admin (admin only)
    builder.row(
        InlineKeyboardButton(
            text="🛒 خرید سرویس",
            callback_data=NavSubscription.BUY,
            style="primary",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="⚙️ خرید سرویس با مشخصات دلخواه",
            callback_data=NavMain.CUSTOM_SERVICE,
            style="success",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="📦 سرویس های من",
            callback_data=NavMain.MY_SERVICES,
        ),
        InlineKeyboardButton(
            text="💰 کیف پول",
            callback_data=NavMain.WALLET,
        ),
    )

    builder.row(
        InlineKeyboardButton(
            text="⏳ افزایش زمان سرویس",
            callback_data=NavSubscription.RENEW_SERVICE,
        ),
        InlineKeyboardButton(
            text="➕ افزایش حجم",
            callback_data=NavSubscription.ADD_TRAFFIC,
        ),
    )

    builder.row(
        InlineKeyboardButton(
            text="👤 حساب کاربری",
            callback_data=NavProfile.MAIN,
        ),
        InlineKeyboardButton(
            text="🤝 معرفی به دوستان",
            callback_data=NavReferral.MAIN,
        ),
    )

    builder.row(
        InlineKeyboardButton(
            text=_("main_menu:button:support"),
            callback_data=NavSupport.MAIN,
        ),
        InlineKeyboardButton(
            text="🌐 تغییر زبان",
            callback_data=NavMain.LANGUAGE,
        ),
    )

    if is_admin:
        builder.row(
            InlineKeyboardButton(
                text=_("main_menu:button:admin_tools"),
                callback_data=NavAdminTools.MAIN,
            )
        )

    return builder.as_markup()
