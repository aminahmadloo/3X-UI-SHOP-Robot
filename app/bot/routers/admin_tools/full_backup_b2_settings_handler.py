from __future__ import annotations

import html
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.filters import IsAdmin
from app.bot.services.full_backup_storage import BackupStorageConfig
from app.bot.utils.navigation import NavAdminTools
from app.config import Config

router = Router(name=__name__)

B2_SETTINGS_MENU = "full_backup:b2_settings"
B2_SETTINGS_PREFIX = "full_backup:b2_edit:"
B2_SETTINGS_TOGGLE = "full_backup:b2_toggle"
B2_SETTINGS_VALUES = (
    ("FULL_BACKUP_STORAGE_ENABLED", "فعال‌سازی Storage خارجی", "bool"),
    ("FULL_BACKUP_STORAGE_ENDPOINT", "Endpoint", "url"),
    ("FULL_BACKUP_STORAGE_BUCKET", "Bucket", "text"),
    ("FULL_BACKUP_STORAGE_ACCESS_KEY_ID", "Key ID", "secret"),
    ("FULL_BACKUP_STORAGE_SECRET_ACCESS_KEY", "Application Key", "secret"),
    ("FULL_BACKUP_STORAGE_REGION", "Region", "text"),
    ("FULL_BACKUP_STORAGE_URL_EXPIRES_SECONDS", "مدت اعتبار لینک (ثانیه)", "int"),
    ("FULL_BACKUP_STORAGE_PREFIX", "Prefix", "text"),
)
ENV_FILE = Path("/app/.env")
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ENV_KEY_LINE_RE = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*?)(\r?\n)?$")


class B2SettingsStates(StatesGroup):
    waiting_value = State()


def _read_env_lines() -> list[str]:
    if not ENV_FILE.exists():
        return []
    return ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)


def _parse_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _read_env_lines():
        match = ENV_KEY_LINE_RE.match(line)
        if not match:
            continue
        value = match.group(4).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        values[match.group(2)] = value
    return values


def _get(name: str) -> str:
    return _parse_env().get(name, os.getenv(name, ""))


def _mask(value: str) -> str:
    if not value:
        return "<i>خالی</i>"
    if len(value) <= 8:
        return "••••••••"
    return f"{html.escape(value[:4])}••••••••{html.escape(value[-4:])}"


def _display(name: str, value: str, kind: str) -> str:
    if kind == "secret":
        return _mask(value)
    if not value:
        return "<i>خالی</i>"
    return html.escape(value)


def _write_env_value(name: str, value: str) -> None:
    if not KEY_RE.fullmatch(name):
        raise ValueError("نام متغیر نامعتبر است.")
    if "\n" in value or "\r" in value:
        raise ValueError("مقدار نمی‌تواند شامل خط جدید باشد.")
    if not ENV_FILE.exists():
        raise FileNotFoundError(str(ENV_FILE))

    output: list[str] = []
    found = False
    for line in _read_env_lines():
        match = ENV_KEY_LINE_RE.match(line)
        if not match:
            output.append(line)
            continue
        indent, key, separator, _old_value, newline = match.groups()
        if key == name:
            output.append(f"{indent}{key}{separator}{value}{newline or chr(10)}")
            found = True
        else:
            output.append(line)
    if not found:
        output.append(f"{name}={value}\n")

    ENV_FILE.write_text("".join(output), encoding="utf-8")
    # Apply the new value to the running process immediately. No Docker socket
    # or container-internal access is needed; the next backup reads os.getenv().
    os.environ[name] = value


def _validate(name: str, value: str, kind: str) -> str:
    value = value.strip()
    if kind == "bool":
        normalized = value.lower()
        if normalized in {"1", "true", "yes", "on", "فعال", "روشن"}:
            return "true"
        if normalized in {"0", "false", "no", "off", "غیرفعال", "خاموش"}:
            return "false"
        raise ValueError("برای این گزینه فقط true یا false وارد کنید.")
    if kind == "int":
        try:
            seconds = int(value)
        except ValueError as exc:
            raise ValueError("مدت اعتبار باید عدد صحیح باشد.") from exc
        if not 1 <= seconds <= 604800:
            raise ValueError("مدت اعتبار باید بین 1 تا 604800 ثانیه باشد.")
        return str(seconds)
    if kind == "url":
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Endpoint باید یک URL معتبر با http یا https باشد.")
        return value.rstrip("/")
    if "\n" in value or "\r" in value:
        raise ValueError("مقدار نمی‌تواند شامل خط جدید باشد.")
    return value


def _menu_keyboard(enabled: bool) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, (_name, label, _kind) in enumerate(B2_SETTINGS_VALUES):
        rows.append([InlineKeyboardButton(text=f"✏️ {label}", callback_data=f"{B2_SETTINGS_PREFIX}{index}")])
    rows.append([
        InlineKeyboardButton(
            text="🟢 Storage فعال" if enabled else "🔴 Storage غیرفعال",
            callback_data=B2_SETTINGS_TOGGLE,
        )
    ])
    rows.append([
        InlineKeyboardButton(text="🔄 تازه‌سازی", callback_data=B2_SETTINGS_MENU),
        InlineKeyboardButton(text="⬅️ بازگشت", callback_data="full_backup:menu"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _menu_text(config: Config) -> str:
    values = _parse_env()
    storage = BackupStorageConfig.from_env()
    lines = [
        "☁️ <b>تنظیمات Backblaze B2</b>",
        "",
        "این بخش مستقیماً تنظیمات Storage خارجی Backup را مدیریت می‌کند.",
        "",
    ]
    for name, label, kind in B2_SETTINGS_VALUES:
        value = values.get(name, os.getenv(name, ""))
        lines.append(f"🔹 <b>{html.escape(label)}</b>\n<code>{_display(name, value, kind)}</code>")
    lines.extend([
        "",
        f"📡 وضعیت فعلی: <b>{'فعال' if storage.enabled else 'غیرفعال'}</b>",
        "",
        "🔐 Key ID و Application Key مخفی نمایش داده می‌شوند.",
        "⚠️ تغییرات بلافاصله در تنظیمات اجرای Bot اعمال می‌شوند و در فایل واقعی <code>.env</code> نیز ذخیره می‌شوند.",
        "ℹ️ Backblaze B2 از S3-Compatible API استفاده می‌کند؛ Key ID معادل Access Key ID و Application Key معادل Secret Access Key است.",
    ])
    return "\n".join(lines)


async def _show_menu(target: Message | CallbackQuery, config: Config) -> None:
    storage = BackupStorageConfig.from_env()
    text = _menu_text(config)
    markup = _menu_keyboard(storage.enabled)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=markup)
    else:
        await target.answer(text, reply_markup=markup)


@router.callback_query(F.data == B2_SETTINGS_MENU, IsAdmin())
async def b2_settings_menu(callback: CallbackQuery, config: Config) -> None:
    if callback.from_user.id != config.bot.DEV_ID:
        await callback.answer("این بخش فقط برای توسعه‌دهنده اصلی فعال است.", show_alert=True)
        return
    await callback.answer()
    await _show_menu(callback, config)


@router.callback_query(F.data == B2_SETTINGS_TOGGLE, IsAdmin())
async def b2_settings_toggle(callback: CallbackQuery, config: Config) -> None:
    if callback.from_user.id != config.bot.DEV_ID:
        await callback.answer("این بخش فقط برای توسعه‌دهنده اصلی فعال است.", show_alert=True)
        return
    current = _get("FULL_BACKUP_STORAGE_ENABLED").lower() in {"1", "true", "yes", "on"}
    _write_env_value("FULL_BACKUP_STORAGE_ENABLED", "false" if current else "true")
    await callback.answer("وضعیت Storage تغییر کرد.")
    await _show_menu(callback, config)


@router.callback_query(F.data.startswith(B2_SETTINGS_PREFIX), IsAdmin())
async def b2_settings_edit_start(callback: CallbackQuery, state: FSMContext, config: Config) -> None:
    if callback.from_user.id != config.bot.DEV_ID:
        await callback.answer("این بخش فقط برای توسعه‌دهنده اصلی فعال است.", show_alert=True)
        return
    try:
        index = int(callback.data.rsplit(":", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("گزینه نامعتبر است.", show_alert=True)
        return
    if index < 0 or index >= len(B2_SETTINGS_VALUES):
        await callback.answer("گزینه پیدا نشد.", show_alert=True)
        return

    name, label, kind = B2_SETTINGS_VALUES[index]
    current = _get(name)
    await state.clear()
    await state.update_data(b2_name=name, b2_label=label, b2_kind=kind)
    await state.set_state(B2SettingsStates.waiting_value)
    await callback.answer()

    if kind == "bool":
        instruction = "مقدار جدید را به‌صورت <code>true</code> یا <code>false</code> ارسال کنید."
    elif kind == "int":
        instruction = "مقدار جدید را به‌صورت تعداد ثانیه بین <code>1</code> تا <code>604800</code> ارسال کنید."
    elif kind == "url":
        instruction = "Endpoint کامل را با http یا https ارسال کنید."
    elif kind == "secret":
        instruction = "مقدار جدید Secret را ارسال کنید. مقدار فعلی نمایش داده نمی‌شود."
    else:
        instruction = "مقدار جدید را ارسال کنید."

    await callback.message.edit_text(
        "✏️ <b>ویرایش تنظیمات Backblaze B2</b>\n\n"
        f"🔑 گزینه: <code>{html.escape(label)}</code>\n"
        f"مقدار فعلی: <code>{_display(name, current, kind)}</code>\n\n"
        f"{instruction}\n\n"
        "⚠️ برای لغو، دکمه زیر را بزنید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 انصراف", callback_data=B2_SETTINGS_MENU)]]),
    )


@router.message(B2SettingsStates.waiting_value, IsAdmin())
async def b2_settings_edit_save(message: Message, state: FSMContext, config: Config) -> None:
    if message.from_user.id != config.bot.DEV_ID:
        await state.clear()
        return
    data = await state.get_data()
    name = data.get("b2_name")
    label = data.get("b2_label")
    kind = data.get("b2_kind")
    if not name or not label or not kind:
        await state.clear()
        await message.answer("❌ اطلاعات ویرایش پیدا نشد.")
        return
    if message.text is None:
        await message.answer("❌ مقدار متنی ارسال کنید.")
        return
    try:
        value = _validate(name, message.text, kind)
        _write_env_value(name, value)
    except Exception as exc:
        await message.answer(f"❌ ذخیره انجام نشد.\n<code>{html.escape(str(exc))}</code>")
        return

    await state.clear()
    await message.answer(
        "✅ <b>تنظیمات Backblaze B2 با موفقیت ذخیره شد.</b>\n\n"
        f"🔑 <code>{html.escape(label)}</code>\n"
        f"💾 مقدار: <code>{_display(name, value, kind)}</code>\n\n"
        "تغییر در فایل واقعی <code>.env</code> ذخیره شد و برای اجرای فعلی Bot نیز اعمال شد.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="☁️ تنظیمات Backblaze B2", callback_data=B2_SETTINGS_MENU)],
            [InlineKeyboardButton(text="💾 Backup کامل ربات", callback_data="full_backup:menu")],
        ]),
    )
