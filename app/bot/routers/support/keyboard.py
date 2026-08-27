from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.routers.misc.keyboard import back_button, back_to_main_menu_button
from app.bot.utils.constants import APP_ANDROID_LINK, APP_IOS_LINK, APP_WINDOWS_LINK
from app.bot.utils.navigation import NavMain, NavSupport


def support_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📚 آموزش", callback_data=NavSupport.TRAINING))
    builder.row(
        InlineKeyboardButton(
            text="💬 ارتباط با پشتیبانی", callback_data=NavSupport.CONTACT
        )
    )
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def training_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="🤖 آموزش اندروید", callback_data=NavSupport.TRAINING_ANDROID
        ),
        InlineKeyboardButton(
            text="🍎 آموزش آیفون", callback_data=NavSupport.TRAINING_IOS
        ),
    )
    builder.row(
        InlineKeyboardButton(
            text="💻 آموزش ویندوز", callback_data=NavSupport.TRAINING_WINDOWS
        )
    )
    builder.row(back_button(NavSupport.MAIN), back_to_main_menu_button())
    return builder.as_markup()


def training_platform_keyboard(platform: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    links = {
        "android": APP_ANDROID_LINK,
        "ios": APP_IOS_LINK,
        "windows": APP_WINDOWS_LINK,
    }
    link = links.get(platform)
    if link:
        builder.row(InlineKeyboardButton(text="📥 دریافت برنامه", url=link))
    builder.row(back_button(NavSupport.TRAINING))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def contact_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="✏️ ارسال پیام", callback_data=NavSupport.SEND_MESSAGE)
    )
    builder.row(
        InlineKeyboardButton(text="📋 تیکت‌های من", callback_data=NavSupport.MY_TICKETS)
    )
    builder.row(back_button(NavSupport.MAIN), back_to_main_menu_button())
    return builder.as_markup()


def ticket_keyboard(ticket_id: int, can_reply: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="💬 مشاهده مکالمه",
            callback_data=f"{NavSupport.TICKET_CONVERSATION}:{ticket_id}",
        )
    )
    if can_reply:
        builder.row(
            InlineKeyboardButton(
                text="✏️ پاسخ به تیکت",
                callback_data=f"{NavSupport.TICKET_REPLY}:{ticket_id}",
            )
        )
        builder.row(
            InlineKeyboardButton(
                text="🔒 بستن تیکت",
                callback_data=f"{NavSupport.TICKET_CLOSE}:{ticket_id}",
            )
        )
    builder.row(
        InlineKeyboardButton(
            text="🔙 تیکت‌های من", callback_data=NavSupport.MY_TICKETS
        )
    )
    builder.row(
        InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)
    )
    return builder.as_markup()


def admin_ticket_keyboard(ticket_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="✏️ پاسخ به کاربر",
            callback_data=f"{NavSupport.TICKET_REPLY}:{ticket_id}",
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🔒 بستن تیکت",
            callback_data=f"{NavSupport.TICKET_CLOSE}:{ticket_id}",
        )
    )
    return builder.as_markup()
