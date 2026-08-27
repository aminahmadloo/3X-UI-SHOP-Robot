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

    # 1. خرید سرویس
    builder.row(
        InlineKeyboardButton(
            text="🛒 خرید سرویس",
            callback_data=NavSubscription.BUY,
            style="primary",
        )
    )

    # 2. خرید سرویس با مشخصات دلخواه
    builder.row(
        InlineKeyboardButton(
            text="⚙️ خرید سرویس با مشخصات دلخواه",
            callback_data=NavMain.CUSTOM_SERVICE,
            style="success",
        )
    )

    # 3. سرویس های من | تمدید سرویس
    builder.row(
        InlineKeyboardButton(
            text="📦 سرویس های من",
            callback_data=NavMain.MY_SERVICES,
        ),
        InlineKeyboardButton(
            text="🔄 تمدید سرویس",
            callback_data="main_menu:renew_service",
        ),
    )

    # 4. کیف پول | حساب کاربری
    builder.row(
        InlineKeyboardButton(
            text="💰 کیف پول",
            callback_data=NavMain.WALLET,
        ),
        InlineKeyboardButton(
            text="👤 حساب کاربری",
            callback_data=NavProfile.MAIN,
        ),
    )

    # 5. سطح من | معرفی به دوستان
    builder.row(
        InlineKeyboardButton(
            text="🏆 سطح من",
            callback_data=NavMain.CUSTOMER_LEVEL,
        ),
        InlineKeyboardButton(
            text="🤝 معرفی به دوستان",
            callback_data=NavReferral.MAIN,
        ),
    )

    # 6. پشتیبانی | اکانت تست
    support_button = InlineKeyboardButton(
        text=_("main_menu:button:support"),
        callback_data=NavSupport.MAIN,
    )

    if is_trial_available:
        builder.row(
            support_button,
            InlineKeyboardButton(
                text="🎁 اکانت تست",
                callback_data=NavSubscription.GET_TRIAL,
            ),
        )
    else:
        builder.row(support_button)

    # 7. مدیریت — فقط برای ادمین
    if is_admin:
        builder.row(
            InlineKeyboardButton(
                text=_("main_menu:button:admin_tools"),
                callback_data=NavAdminTools.MAIN,
            )
        )

    return builder.as_markup()
