from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools
from app.db.models import SubscriptionSettings

from .keyboard import subscription_settings_keyboard


router = Router(name=__name__)


async def _settings_text(session: AsyncSession) -> str:
    settings = await SubscriptionSettings.get_or_create(session)
    user_control = "🟢 فعال" if settings.allow_user_client_toggle else "🔴 غیرفعال"
    return (
        "🌐 <b>مدیریت لینک اشتراک</b>\n\n"
        f"دامنه: <code>{settings.domain or 'IP سرور'}</code>\n"
        f"پورت: <code>{settings.port}</code>\n"
        f"مسیر: <code>{settings.path}</code>\n\n"
        "👤 <b>اجازه فعال/غیرفعال کردن کلاینت توسط کاربر:</b> "
        f"{user_control}\n\n"
        "وقتی این گزینه فعال باشد، کاربر می‌تواند از بخش «سرویس‌های من» فقط کلاینت همان سرویس خودش را فعال یا غیرفعال کند."
    )


async def _render(callback: CallbackQuery, session: AsyncSession) -> None:
    settings = await SubscriptionSettings.get_or_create(session)
    markup = subscription_settings_keyboard()
    button_text = (
        "👤 خاموش کردن کنترل کلاینت توسط کاربر"
        if settings.allow_user_client_toggle
        else "👤 روشن کردن کنترل کلاینت توسط کاربر"
    )
    markup.inline_keyboard.insert(
        -2,
        [InlineKeyboardButton(text=button_text, callback_data="subscription_settings:user_client_toggle")],
    )
    await callback.message.edit_text(
        await _settings_text(session),
        reply_markup=markup,
    )


@router.callback_query(
    F.data == NavAdminTools.SUBSCRIPTION_SETTINGS,
    IsAdmin(),
)
async def subscription_settings_menu(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    await callback.answer()
    await _render(callback, session)


@router.callback_query(
    F.data == "subscription_settings:user_client_toggle",
    IsAdmin(),
)
async def toggle_user_client_control(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    settings = await SubscriptionSettings.get_or_create(session)
    settings.allow_user_client_toggle = not settings.allow_user_client_toggle
    await session.commit()

    state_text = "فعال شد" if settings.allow_user_client_toggle else "غیرفعال شد"
    await callback.answer(f"کنترل فعال/غیرفعال کردن کلاینت توسط کاربر {state_text}.")
    await _render(callback, session)
