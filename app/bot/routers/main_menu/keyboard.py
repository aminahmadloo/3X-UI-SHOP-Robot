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

    # 3. سرویس های من | کیف پول
    # callbackهای هر دو دکمه بدون تغییر
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

    # 4. تمدید سرویس | حساب کاربری
    # callbackهای هر دو دکمه بدون تغییر
    builder.row(
        InlineKeyboardButton(
            text="🔄 تمدید سرویس",
            callback_data="main_menu:renew_service",
        ),
        InlineKeyboardButton(
            text="👤 حساب کاربری",
            callback_data=NavProfile.MAIN,
        ),
    )

    # 5. معرفی به دوستان | پشتیبانی
    builder.row(
        InlineKeyboardButton(
            text="🤝 معرفی به دوستان",
            callback_data=NavReferral.MAIN,
        ),
        InlineKeyboardButton(
            text=_("main_menu:button:support"),
            callback_data=NavSupport.MAIN,
        ),
    )

    # 6. مدیریت — فقط برای ادمین
    if is_admin:
        builder.row(
            InlineKeyboardButton(
                text=_("main_menu:button:admin_tools"),
                callback_data=NavAdminTools.MAIN,
            )
        )

    return builder.as_markup()
