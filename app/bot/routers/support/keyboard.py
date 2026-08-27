from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.routers.misc.keyboard import back_button, back_to_main_menu_button
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
        InlineKeyboardButton(text="🟢 Happ", callback_data=NavSupport.TRAINING_HAPP),
        InlineKeyboardButton(text="🔵 V2Ray", callback_data=NavSupport.TRAINING_V2RAY),
    )
    builder.row(
        InlineKeyboardButton(text="🟣 V2Box", callback_data=NavSupport.TRAINING_V2BOX)
    )
    builder.row(back_button(NavSupport.MAIN), back_to_main_menu_button())
    return builder.as_markup()


def training_app_keyboard(app: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    platforms = {
        "happ": [
            ("🤖 Android", "android"),
            ("🍎 iPhone / iPad", "ios"),
            ("💻 Windows", "windows"),
            ("🖥 macOS", "macos"),
            ("🐧 Linux", "linux"),
        ],
        "v2ray": [
            ("🤖 Android — v2rayNG", "android"),
            ("💻 Windows — v2rayN", "windows"),
            ("🖥 macOS — v2rayN", "macos"),
            ("🐧 Linux — v2rayN", "linux"),
        ],
        "v2box": [
            ("🍎 iPhone / iPad", "ios"),
            ("🖥 macOS", "macos"),
        ],
    }
    for text, platform in platforms.get(app, []):
        builder.row(
            InlineKeyboardButton(
                text=text,
                callback_data=f"{NavSupport.TRAINING_APP_PLATFORM}:{app}:{platform}",
            )
        )
    builder.row(back_button(NavSupport.TRAINING), back_to_main_menu_button())
    return builder.as_markup()


def training_detail_keyboard(
    app: str,
    platform: str,
    download_url: str | None = None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if download_url:
        builder.row(InlineKeyboardButton(text="📥 دریافت برنامه", url=download_url))
    builder.row(
        InlineKeyboardButton(
            text="🔙 انتخاب سیستم‌عامل",
            callback_data=f"{NavSupport.TRAINING_APP_PLATFORM.rsplit(':', 1)[0]}:{app}",
        )
    )
    builder.row(back_button(NavSupport.TRAINING), back_to_main_menu_button())
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
