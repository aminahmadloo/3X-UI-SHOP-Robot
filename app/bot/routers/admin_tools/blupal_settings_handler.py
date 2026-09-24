from __future__ import annotations

import html

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.filters import IsAdmin
from app.bot.routers.admin_tools import payment_gateway_settings_handler as payment_gateway_admin
from app.bot.utils.navigation import NavAdminTools

router = Router(name=__name__)

BLUPAL_KEY = "BLUPAL_API_KEY"
BLUPAL_BASE = "BLUPAL_API_BASE_URL"
BLUPAL_WEBHOOK_PATH = "/webhooks/blupal"


class BluPalSettingsState(StatesGroup):
    waiting_api_key = State()


def _read(name: str) -> str:
    return payment_gateway_admin._read_env_value(name)


def _write(name: str, value: str) -> None:
    payment_gateway_admin._write_env_value(name, value)


def _mask(value: str) -> str:
    return payment_gateway_admin._mask_secret(value)


def _menu() -> InlineKeyboardMarkup:
    configured = bool(_read(BLUPAL_KEY))
    status = "🟢 فعال" if configured else "🔴 تنظیم نشده"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 تنظیم / تغییر API Key", callback_data="paymentgateway:blupal:key")],
        [InlineKeyboardButton(text="🔄 تازه‌سازی وضعیت", callback_data="paymentgateway:blupal")],
        [InlineKeyboardButton(text="⚙️ مدیریت سایر متغیرهای .env", callback_data=NavAdminTools.ENV_SETTINGS)],
        [InlineKeyboardButton(text="🔙 تنظیمات درگاه‌ها", callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS)],
    ])


def _show_text(config) -> str:
    api_key = _read(BLUPAL_KEY)
    base_url = _read(BLUPAL_BASE) or "https://blupal.top/api"
    webhook = f"{config.bot.DOMAIN.rstrip('/')}{BLUPAL_WEBHOOK_PATH}"
    mode = "Sandbox" if api_key.startswith("blu_test_") else "Live" if api_key.startswith("blu_live_") else "نامشخص"
    return (
        "💳 <b>تنظیمات کارت به کارت هوشمند بلوپال</b>\n\n"
        f"وضعیت اتصال: <b>{'🟢 آماده استفاده' if api_key else '🔴 نیازمند تنظیمات'}</b>\n"
        f"🔑 API Key: <b>{_mask(api_key)}</b>\n"
        f"🧪 محیط: <b>{html.escape(mode)}</b>\n"
        f"🌐 API: <code>{html.escape(base_url)}</code>\n"
        f"🔗 Webhook: <code>{html.escape(webhook)}</code>\n\n"
        "Webhook را دقیقاً با همین آدرس در پنل BluPal برای API Key ثبت کنید.\n"
        "کلید API فقط سمت سرور استفاده می‌شود و در پنل به‌صورت کامل نمایش داده نمی‌شود."
    )


_original_menu_markup = payment_gateway_admin.menu_markup


def _patched_menu_markup(settings):
    markup = _original_menu_markup(settings)
    rows = list(markup.inline_keyboard)
    button = [InlineKeyboardButton(text="💳 تنظیمات کارت به کارت هوشمند بلوپال", callback_data="paymentgateway:blupal")]
    insert_at = max(0, len(rows) - 2)
    rows.insert(insert_at, button)
    return InlineKeyboardMarkup(inline_keyboard=rows)


payment_gateway_admin.menu_markup = _patched_menu_markup


@router.callback_query(F.data == "paymentgateway:blupal", IsAdmin())
async def blupal_settings_menu(callback: CallbackQuery, config) -> None:
    await callback.answer()
    await callback.message.edit_text(_show_text(config), reply_markup=_menu())


@router.callback_query(F.data == "paymentgateway:blupal:key", IsAdmin())
async def blupal_key_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(BluPalSettingsState.waiting_api_key)
    await callback.answer()
    await callback.message.edit_text(
        "🔑 <b>تنظیم API Key بلوپال</b>\n\n"
        "کلید Sandbox باید با <code>blu_test_</code> و کلید Live با <code>blu_live_</code> شروع شود.\n\n"
        "کلید را ارسال کنید؛ مقدار کامل هرگز در پنل نمایش داده نمی‌شود.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 انصراف", callback_data="paymentgateway:blupal")],
        ]),
    )


@router.message(BluPalSettingsState.waiting_api_key, IsAdmin())
async def blupal_key_save(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value.startswith(("blu_test_", "blu_live_")) or len(value) <= 10:
        await message.answer("❌ API Key معتبر نیست. باید با <code>blu_test_</code> یا <code>blu_live_</code> شروع شود.")
        return
    try:
        _write(BLUPAL_KEY, value)
        if not _read(BLUPAL_BASE):
            _write(BLUPAL_BASE, "https://blupal.top/api")
    except Exception as exc:
        await state.clear()
        await message.answer(f"❌ ذخیره API Key انجام نشد.\n<code>{html.escape(str(exc))}</code>")
        return
    await state.clear()
    await message.answer("✅ <b>API Key بلوپال ذخیره شد.</b>\n\nبرای فعال‌شدن اتصال جدید، ربات را ری‌استارت کنید.")
