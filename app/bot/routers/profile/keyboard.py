from aiogram.types import CopyTextButton, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.routers.misc.keyboard import back_to_main_menu_button
from app.bot.utils.navigation import NavMain, NavProfile, NavReferral, NavSupport


def profile_keyboard(language: str = "fa") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if language == "en":
        services_text = "📦 My Services"
        wallet_text = "💰 Wallet"
        referral_text = "🎁 Invite Friends"
        connection_text = "🔐 Connection Guide"
        key_text = "🔑 Show Connection Keys"
        language_text = "🌐 Change Language"
    elif language == "ru":
        services_text = "📦 Мои сервисы"
        wallet_text = "💰 Кошелёк"
        referral_text = "🎁 Пригласить друзей"
        connection_text = "🔐 Как подключиться"
        key_text = "🔑 Показать ключи подключения"
        language_text = "🌐 Изменить язык"
    else:
        services_text = "📦 سرویس‌های من"
        wallet_text = "💰 کیف پول"
        referral_text = "🎁 دعوت از دوستان"
        connection_text = "🔐 راهنمای اتصال"
        key_text = "🔑 نمایش کلیدهای اتصال"
        language_text = "🌐 تغییر زبان"

    builder.row(
        InlineKeyboardButton(text=services_text, callback_data=NavMain.MY_SERVICES),
        InlineKeyboardButton(text=wallet_text, callback_data=NavMain.WALLET),
    )
    builder.row(
        InlineKeyboardButton(text=referral_text, callback_data=NavReferral.MAIN),
    )
    builder.row(
        InlineKeyboardButton(text=connection_text, callback_data=NavSupport.TRAINING),
        InlineKeyboardButton(text=key_text, callback_data=NavProfile.SHOW_KEY),
    )
    builder.row(
        InlineKeyboardButton(text=language_text, callback_data=NavMain.LANGUAGE),
    )
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def connection_keys_keyboard(
    keys: list[tuple[int, str, str]],
    language: str = "fa",
) -> InlineKeyboardMarkup | None:
    if not keys:
        return None

    builder = InlineKeyboardBuilder()

    if language == "en":
        copy_button_text = "📋 Copy"
    elif language == "ru":
        copy_button_text = "📋 Копировать"
    else:
        copy_button_text = "📋 کپی"

    for number, (_subscription_id, config_name, connection_key) in enumerate(keys, start=1):
        label = f"{number}️⃣ {config_name}" if config_name else f"{number}️⃣ Connection Key"
        builder.row(
            InlineKeyboardButton(text=label, url=connection_key),
            InlineKeyboardButton(
                text=copy_button_text,
                copy_text=CopyTextButton(text=connection_key),
            ),
        )

    return builder.as_markup()
