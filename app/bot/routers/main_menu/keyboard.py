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
    show_custom_service_button: bool = True,
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
    if show_custom_service_button:
        builder.row(
            InlineKeyboardButton(
                text="⚙️ خرید سرویس با مشخصات دلخواه",
                callback_data=NavMain.CUSTOM_SERVICE,
                style="success",
            )
        )

    # 3. تمدید سرویس | سرویس های من
    builder.row(
        InlineKeyboardButton(
            text="🔄 تمدید سرویس",
            callback_data="main_menu:renew_service",
        ),
        InlineKeyboardButton(
            text="📦 سرویس های من",
            callback_data=NavMain.MY_SERVICES,
        ),
    )

    # 4. حساب کاربری | کیف پول
    builder.row(
        InlineKeyboardButton(
            text="👤 حساب کاربری",
            callback_data=NavProfile.MAIN,
        ),
        InlineKeyboardButton(
            text="💰 کیف پول",
            callback_data=NavMain.WALLET,
        ),
    )

    # 5. معرفی به دوستان | سطح من
    builder.row(
        InlineKeyboardButton(
            text="🤝 معرفی به دوستان",
            callback_data=NavReferral.MAIN,
        ),
        InlineKeyboardButton(
            text="🏆 سطح من",
            callback_data=NavMain.CUSTOMER_LEVEL,
        ),
    )

    # 6. اکانت تست | آموزش و پشتیبانی
    # اکانت تست فعلاً همیشه نمایش داده می‌شود.
    # منطق نهایی دسترسی/فعال‌سازی بعداً جداگانه اصلاح خواهد شد.
    builder.row(
        InlineKeyboardButton(
            text="🎁 اکانت تست",
            callback_data=NavSubscription.GET_TRIAL,
        ),
        InlineKeyboardButton(
            text="آموزش و پشتیبانی",
            callback_data=NavSupport.MAIN,
        ),
    )

    # 7. مدیریت — فقط برای ادمین
    if is_admin:
        builder.row(
            InlineKeyboardButton(
                text=_("main_menu:button:admin_tools"),
                callback_data=NavAdminTools.MAIN,
            )
        )

    return builder.as_markup()
