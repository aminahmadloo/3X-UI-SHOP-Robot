from __future__ import annotations

import html
import os
import re
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.config import Config
from app.db.models import PaymentMethodSettings

router = Router(name=__name__)
ENV_FILE = Path("/app/.env")
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class VarizaSettingsState(StatesGroup):
    waiting_api_key = State()
    waiting_webhook_secret = State()
    waiting_card_last_4 = State()
    waiting_expires_in = State()


def _read_env() -> list[str]:
    if not ENV_FILE.exists():
        return []
    return ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)


def _read_env_value(name: str, default: str = "") -> str:
    for line in _read_env():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        if key == name:
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            return value.strip()
    return os.getenv(name, default).strip()


def _write_env_value(name: str, value: str) -> None:
    if not ENV_KEY_RE.fullmatch(name):
        raise ValueError("نام متغیر نامعتبر است.")
    if "\n" in value or "\r" in value:
        raise ValueError("مقدار نمی‌تواند شامل خط جدید باشد.")
    lines = _read_env()
    output: list[str] = []
    found = False
    for line in lines:
        raw = line.rstrip("\r\n")
        newline = line[len(raw):] or "\n"
        if raw.strip().startswith(f"{name}=") or raw.strip().startswith(f"{name} ="):
            output.append(f"{name}={value}{newline}")
            found = True
        else:
            output.append(line)
    if not found:
        output.append(f"{name}={value}\n")
    ENV_FILE.write_text("".join(output), encoding="utf-8")
    try:
        ENV_FILE.chmod(0o600)
    except OSError:
        pass


def _mask(value: str) -> str:
    if not value:
        return "🔴 تنظیم نشده"
    if len(value) <= 8:
        return "🟢 ••••••••"
    return f"🟢 {html.escape(value[:4])}••••••••{html.escape(value[-4:])}"


def _enabled() -> bool:
    return _read_env_value("VARIZA_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


def _configured() -> bool:
    return bool(_read_env_value("VARIZA_API_KEY") and _read_env_value("VARIZA_WEBHOOK_SECRET"))


def _markup(aban_enabled: bool) -> InlineKeyboardMarkup:
    variza_enabled = _enabled()
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{'🟢' if aban_enabled else '🔴'} درگاه آبان گیت — {'فعال' if aban_enabled else 'غیرفعال'}", callback_data="variza_admin:toggle_aban")],
        [InlineKeyboardButton(text=f"{'🟢' if variza_enabled else '🔴'} درگاه واریزا — {'فعال' if variza_enabled else 'غیرفعال'}", callback_data="variza_admin:toggle_variza")],
        [InlineKeyboardButton(text="🔑 API Key واریزا", callback_data="variza_admin:api")],
        [InlineKeyboardButton(text="🔐 Webhook Secret واریزا", callback_data="variza_admin:secret")],
        [InlineKeyboardButton(text="💳 تنظیم کارت مقصد", callback_data="variza_admin:card")],
        [InlineKeyboardButton(text="⏱️ تنظیم مهلت لینک", callback_data="variza_admin:expires")],
        [InlineKeyboardButton(text="🔄 تازه‌سازی", callback_data="paymentgateway:smart_card")],
        [InlineKeyboardButton(text="🔙 تنظیمات درگاه‌ها", callback_data="paymentgateway:settings_back")],
    ])


async def _aban_enabled(session: AsyncSession) -> bool:
    item = await PaymentMethodSettings.get_by_key(session, "pay_aban")
    return bool(item and item.enabled)


async def _show(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    await callback.answer()
    aban_enabled = await _aban_enabled(session)
    api_key = _read_env_value("VARIZA_API_KEY")
    secret = _read_env_value("VARIZA_WEBHOOK_SECRET")
    card = _read_env_value("VARIZA_CARD_LAST_4") or "پیش‌فرض حساب واریزا"
    expires = _read_env_value("VARIZA_EXPIRES_IN", "1h")
    webhook = f"{config.bot.DOMAIN.rstrip('/')}/webhooks/variza"
    text = (
        "💳 <b>کارت به کارت هوشمند — مدیریت درگاه‌ها</b>\n\n"
        f"1️⃣ آبان گیت: <b>{'🟢 فعال' if aban_enabled else '🔴 غیرفعال'}</b>\n"
        f"2️⃣ واریزا: <b>{'🟢 فعال' if _enabled() else '🔴 غیرفعال'}</b>\n\n"
        f"🔑 API Key واریزا: {_mask(api_key)}\n"
        f"🔐 Webhook Secret: {_mask(secret)}\n"
        f"💳 کارت مقصد: <code>{html.escape(card)}</code>\n"
        f"⏱️ مهلت لینک: <code>{html.escape(expires)}</code>\n"
        f"🔗 Webhook: <code>{html.escape(webhook)}</code>\n"
        f"📡 آمادگی اتصال: <b>{'🟢 آماده' if _configured() else '🔴 ابتدا API Key و Secret را تنظیم کنید'}</b>\n\n"
        "واریزا کاملاً جدا از Factory و تنظیمات داخلی درگاه‌های دیگر اجرا می‌شود."
    )
    await callback.message.edit_text(text, reply_markup=_markup(aban_enabled))


@router.callback_query(F.data == "paymentgateway:smart_card", IsAdmin())
async def smart_card_menu(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    await _show(callback, session, config)


@router.callback_query(F.data == "paymentgateway:settings_back", IsAdmin())
async def settings_back(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    await callback.answer()
    from .payment_gateway_settings_handler import show_menu
    await show_menu(callback, session, config)


@router.callback_query(F.data == "variza_admin:toggle_aban", IsAdmin())
async def toggle_aban(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    item = await PaymentMethodSettings.get_by_key(session, "pay_aban")
    if item is None:
        await callback.answer("تنظیم آبان گیت پیدا نشد.", show_alert=True)
        return
    item.enabled = not item.enabled
    await session.commit()
    await _show(callback, session, config)


@router.callback_query(F.data == "variza_admin:toggle_variza", IsAdmin())
async def toggle_variza(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    try:
        _write_env_value("VARIZA_ENABLED", "false" if _enabled() else "true")
    except Exception as exc:
        await callback.answer(f"خطا: {exc}", show_alert=True)
        return
    await _show(callback, session, config)


@router.callback_query(F.data == "variza_admin:api", IsAdmin())
async def api_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(VarizaSettingsState.waiting_api_key)
    await callback.answer()
    await callback.message.edit_text("🔑 <b>API Key واریزا</b>\n\nکلید API را ارسال کنید.\nمقدار در پنل نمایش داده نمی‌شود.")


@router.message(VarizaSettingsState.waiting_api_key, IsAdmin())
async def api_save(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if len(value) < 12:
        await message.answer("❌ API Key کوتاه یا نامعتبر است.")
        return
    _write_env_value("VARIZA_API_KEY", value)
    await state.clear()
    await message.answer("✅ API Key واریزا ذخیره شد.")


@router.callback_query(F.data == "variza_admin:secret", IsAdmin())
async def secret_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(VarizaSettingsState.waiting_webhook_secret)
    await callback.answer()
    await callback.message.edit_text("🔐 <b>Webhook Secret واریزا</b>\n\nSecret را ارسال کنید.")


@router.message(VarizaSettingsState.waiting_webhook_secret, IsAdmin())
async def secret_save(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if len(value) < 8:
        await message.answer("❌ Webhook Secret کوتاه یا نامعتبر است.")
        return
    _write_env_value("VARIZA_WEBHOOK_SECRET", value)
    await state.clear()
    await message.answer("✅ Webhook Secret واریزا ذخیره شد.")


@router.callback_query(F.data == "variza_admin:card", IsAdmin())
async def card_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(VarizaSettingsState.waiting_card_last_4)
    await callback.answer()
    await callback.message.edit_text("💳 <b>۴ رقم آخر کارت مقصد</b>\n\nعدد ۴ رقمی وارد کنید یا برای استفاده از رفتار پیش‌فرض واریزا خالی بگذارید.")


@router.message(VarizaSettingsState.waiting_card_last_4, IsAdmin())
async def card_save(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if value and (not value.isdigit() or len(value) != 4):
        await message.answer("❌ باید دقیقاً ۴ رقم باشد.")
        return
    _write_env_value("VARIZA_CARD_LAST_4", value)
    await state.clear()
    await message.answer("✅ کارت مقصد واریزا ذخیره شد.")


@router.callback_query(F.data == "variza_admin:expires", IsAdmin())
async def expires_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(VarizaSettingsState.waiting_expires_in)
    await callback.answer()
    await callback.message.edit_text("⏱️ <b>مهلت لینک واریزا</b>\n\nیکی از مقادیر <code>30m</code>، <code>1h</code>، <code>2h</code>، <code>6h</code>، <code>1d</code> یا <code>1w</code> را ارسال کنید.")


@router.message(VarizaSettingsState.waiting_expires_in, IsAdmin())
async def expires_save(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip().lower()
    if value not in {"30m", "1h", "2h", "6h", "1d", "1w", "never"}:
        await message.answer("❌ مقدار معتبر نیست.")
        return
    _write_env_value("VARIZA_EXPIRES_IN", value)
    await state.clear()
    await message.answer("✅ مهلت لینک واریزا ذخیره شد.")
