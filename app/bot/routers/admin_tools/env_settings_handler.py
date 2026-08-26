import os

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools

router = Router(name=__name__)


def _value(name: str, secret: bool = False) -> str:
    value = os.getenv(name, "")
    if not value:
        return "<i>تنظیم نشده</i>"
    if secret:
        if len(value) <= 8:
            return "••••••••"
        return f"{value[:4]}••••••••{value[-4:]}"
    return value


def _keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)],
        ]
    )


@router.callback_query(F.data == NavAdminTools.ENV_SETTINGS, IsAdmin())
async def env_settings_menu(callback: CallbackQuery) -> None:
    text = (
        "⚙️ <b>تنظیمات .env</b>\n\n"
        "وضعیت متغیرهای اصلی محیط اجرای ربات:\n\n"
        f"🤖 BOT_DOMAIN: <code>{_value('BOT_DOMAIN')}</code>\n"
        f"🌐 BOT_PORT: <code>{_value('BOT_PORT')}</code>\n"
        f"💳 SHOP_PAYMENT_ZARINPAL_ENABLED: <code>{_value('SHOP_PAYMENT_ZARINPAL_ENABLED')}</code>\n"
        f"🔐 ZARINPAL_MERCHANT_ID: <code>{_value('ZARINPAL_MERCHANT_ID', True)}</code>\n"
        f"🔗 ZARINPAL_PAYMENT_BASE_URL: <code>{_value('ZARINPAL_PAYMENT_BASE_URL')}</code>\n"
        f"👤 BOT_ADMINS: <code>{_value('BOT_ADMINS')}</code>\n\n"
        "برای تغییر مقادیر .env، فایل <code>.env</code> روی سرور را ویرایش و ربات را ری‌استارت کنید."
    )
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=_keyboard())
