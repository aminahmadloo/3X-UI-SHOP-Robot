import html
import re
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools

router = Router(name=__name__)

ENV_FILE = Path("/app/.env")
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ENV_KEY_LINE_RE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*(?:\r?\n)?$")


class EnvAddStates(StatesGroup):
    key = State()
    value = State()


def _read_lines() -> list[str]:
    if not ENV_FILE.exists():
        return []
    return ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)


def _variables() -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []
    for line in _read_lines():
        match = ENV_KEY_LINE_RE.match(line)
        if not match:
            continue
        value = match.group(2).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        result.append((match.group(1), value))
    return result


def _is_secret(name: str) -> bool:
    upper = name.upper()
    return any(part in upper for part in ("TOKEN", "PASSWORD", "SECRET", "PRIVATE_KEY", "API_KEY", "MERCHANT_ID"))


def _display(name: str, value: str) -> str:
    if not value:
        return "<i>خالی</i>"
    if _is_secret(name):
        if len(value) <= 8:
            return "••••••••"
        return html.escape(value[:4]) + "••••••••" + html.escape(value[-4:])
    return html.escape(value)


def _menu() -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, (name, _) in enumerate(_variables()):
        rows.append([
            InlineKeyboardButton(text=f"✏️ ویرایش {name}", callback_data=f"env:edit:{index}"),
            InlineKeyboardButton(text="🗑️ حذف", callback_data=f"env:delete:{index}"),
        ])
    rows.append([InlineKeyboardButton(text="➕ افزودن متغیر جدید", callback_data="env:add")])
    rows.append([InlineKeyboardButton(text="🔄 تازه‌سازی", callback_data=NavAdminTools.ENV_SETTINGS)])
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show(callback: CallbackQuery) -> None:
    variables = _variables()
    lines = [
        "⚙️ <b>تنظیمات .env</b>",
        "",
        f"📄 تعداد متغیرها: <b>{len(variables)}</b>",
        "",
    ]
    for index, (name, value) in enumerate(variables, start=1):
        lines.append(f"{index}. <code>{html.escape(name)}</code> = <code>{_display(name, value)}</code>")
    lines.extend(["", "➕ امکان افزودن متغیر جدید نیز از همین بخش فراهم است.", "🔐 مقادیر حساس مخفی نمایش داده می‌شوند."])
    await callback.message.edit_text("\n".join(lines), reply_markup=_menu())


@router.callback_query(F.data == NavAdminTools.ENV_SETTINGS, IsAdmin())
async def env_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await _show(callback)


@router.callback_query(F.data == "env:add", IsAdmin())
async def env_add_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(EnvAddStates.key)
    await callback.answer()
    await callback.message.edit_text(
        "➕ <b>افزودن متغیر جدید به .env</b>\n\n"
        "نام متغیر را ارسال کنید.\n\n"
        "مثال:\n<code>NEW_SETTING</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🔙 انصراف", callback_data=NavAdminTools.ENV_SETTINGS)
        ]]),
    )


@router.message(EnvAddStates.key, IsAdmin())
async def env_add_key(message: Message, state: FSMContext) -> None:
    name = (message.text or "").strip()
    if not KEY_RE.fullmatch(name):
        await message.answer("❌ نام متغیر نامعتبر است. فقط حروف انگلیسی، عدد و _ مجاز است و نام نباید با عدد شروع شود.")
        return
    if any(existing == name for existing, _ in _variables()):
        await message.answer("❌ این متغیر از قبل وجود دارد. از گزینه ویرایش استفاده کنید.")
        return
    await state.update_data(env_new_name=name)
    await state.set_state(EnvAddStates.value)
    await message.answer(
        f"🔑 نام متغیر: <code>{html.escape(name)}</code>\n\n"
        "مقدار آن را ارسال کنید. برای مقدار خالی <code>__EMPTY__</code> را بفرستید."
    )


@router.message(EnvAddStates.value, IsAdmin())
async def env_add_value(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    name = data.get("env_new_name")
    value = message.text
    if not name or value is None:
        await state.clear()
        await message.answer("❌ اطلاعات افزودن متغیر ناقص است.", reply_markup=_menu())
        return
    if value == "__EMPTY__":
        value = ""
    if "\n" in value or "\r" in value:
        await message.answer("❌ مقدار باید در یک پیام و بدون خط جدید ارسال شود.")
        return
    if any(existing == name for existing, _ in _variables()):
        await state.clear()
        await message.answer("❌ این متغیر هم‌اکنون وجود دارد. عملیات لغو شد.", reply_markup=_menu())
        return
    try:
        with ENV_FILE.open("a", encoding="utf-8") as file:
            file.write(f"{name}={value}\n")
    except Exception as exc:
        await state.clear()
        await message.answer(f"❌ ذخیره انجام نشد:\n<code>{html.escape(str(exc))}</code>", reply_markup=_menu())
        return
    await state.clear()
    await message.answer(
        "✅ متغیر با موفقیت به فایل واقعی <code>.env</code> اضافه شد.\n\n"
        f"🔑 <code>{html.escape(name)}</code>\n"
        f"💾 مقدار: <code>{_display(name, value)}</code>\n\n"
        "⚠️ برای اعمال آن در محیط اجرای ربات، Bot را restart/recreate کنید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚙️ تنظیمات .env", callback_data=NavAdminTools.ENV_SETTINGS)],
            [InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)],
        ]),
    )


@router.callback_query(F.data.startswith("env:delete:"), IsAdmin())
async def env_delete(callback: CallbackQuery) -> None:
    try:
        index = int(callback.data.rsplit(":", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("متغیر نامعتبر است.", show_alert=True)
        return
    variables = _variables()
    if index < 0 or index >= len(variables):
        await callback.answer("متغیر پیدا نشد.", show_alert=True)
        return
    name, _ = variables[index]
    lines = _read_lines()
    output: list[str] = []
    removed = False
    for line in lines:
        match = ENV_KEY_LINE_RE.match(line)
        if match and match.group(1) == name:
            removed = True
            continue
        output.append(line)
    if not removed:
        await callback.answer("متغیر پیدا نشد.", show_alert=True)
        return
    try:
        ENV_FILE.write_text("".join(output), encoding="utf-8")
    except Exception as exc:
        await callback.answer(f"حذف ناموفق: {exc}", show_alert=True)
        return
    await callback.answer("متغیر حذف شد.")
    await _show(callback)
