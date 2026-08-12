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

    if is_referred_trial_available:
        builder.row(
            InlineKeyboardButton(
                text=_("referral:button:get_referred_trial"),
                callback_data=NavReferral.GET_REFERRED_TRIAL,
            )
        )
    elif is_trial_available:
        builder.row(
            InlineKeyboardButton(
                text=_("subscription:button:get_trial"), callback_data=NavSubscription.GET_TRIAL
            )
        )

    # Main customer actions.
    # Order: 1) Buy Service, 2) Custom Service, 3) My Services, 4) Wallet.
    builder.row(
        InlineKeyboardButton(
            text="🛒 خرید سرویس",
            callback_data=NavSubscription.MAIN,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="⚙️ خرید سرویس با مشخصات دلخواه",
            callback_data=NavMain.CUSTOM_SERVICE,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="📦 سرویس های من",
            callback_data=NavProfile.MAIN,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="💰 کیف پول",
            callback_data=NavMain.WALLET,
        )
    )

    # Keep the remaining menu buttons in their existing place/order.
    builder.row(
        *(
            [
                InlineKeyboardButton(
                    text=_("main_menu:button:referral"),
                    callback_data=NavReferral.MAIN,
                )
            ]
            if is_referral_available
            else []
        ),
        InlineKeyboardButton(
            text=_("main_menu:button:support"),
            callback_data=NavSupport.MAIN,
        ),
    )

    if is_admin:
        builder.row(
            InlineKeyboardButton(
                text=_("main_menu:button:admin_tools"),
                callback_data=NavAdminTools.MAIN,
            )
        )

    builder.row(
        InlineKeyboardButton(
            text="🌐 تغییر زبان",
            callback_data=NavMain.LANGUAGE,
        )
    )

    return builder.as_markup()
