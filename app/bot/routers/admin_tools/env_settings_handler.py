import html
import re
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools

router = Router(name=__name__)

ENV_FILE = Path("/app/.env")
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ENV_KEY_LINE_RE = re.compile(
    r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*?)(\r?\n)?$"
)

SECRET_KEY_PARTS = (
    "TOKEN",
    "PASSWORD",
    "SECRET",
    "PRIVATE_KEY",
    "API_KEY",
    "MERCHANT_ID",
)


class EnvSettingsStates(StatesGroup):
    waiting_value = State()


def _is_secret(name: str) -> bool:
    upper = name.upper()
    return any(part in upper for part in SECRET_KEY_PARTS)


def _mask(value: str) -> str:
    if not value:
        return "<i>خالی</i>"

    if len(value) <= 8:
        return "••••••••"

    return f"{html.escape(value[:4])}••••••••{html.escape(value[-4:])}"


def _display_value(name: str, value: str) -> str:
    if _is_secret(name):
        return _mask(value)

    if not value:
        return "<i>خالی</i>"

    return html.escape(value)


def _read_env_lines() -> list[str]:
    if not ENV_FILE.exists():
        return []

    return ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)


def _parse_env() -> list[tuple[str, str]]:
    result: list[tuple[str, str]] = []

    for line in _read_env_lines():
        match = ENV_KEY_LINE_RE.match(line)
        if not match:
            continue

        key = match.group(2)
        raw_value = match.group(4)

        value = raw_value.strip()

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ('"', "'")
        ):
            value = value[1:-1]

        result.append((key, value))

    return result


def _find_value(name: str) -> str | None:
    for key, value in _parse_env():
        if key == name:
            return value

    return None


def _write_env_value(name: str, value: str) -> None:
    if not KEY_RE.fullmatch(name):
        raise ValueError("نام متغیر نامعتبر است.")

    if "\\n" in value or "\\r" in value:
        raise ValueError("مقدار نمی‌تواند شامل خط جدید باشد.")

    if not ENV_FILE.exists():
        raise FileNotFoundError(str(ENV_FILE))

    lines = _read_env_lines()
    output: list[str] = []
    found = False

    for line in lines:
        match = ENV_KEY_LINE_RE.match(line)

        if not match:
            output.append(line)
            continue

        indent, key, separator, old_value, newline = match.groups()

        if key == name:
            output.append(
                f"{indent}{key}{separator}{value}"
                f"{newline or chr(10)}"
            )
            found = True
        else:
            output.append(line)

    if not found:
        output.append(f"{name}={value}\\n")

    # /app/.env is a Docker bind mount.
    # Do NOT rename/replace the mount point with a temporary file.
    # Write directly to the mounted file so the change reaches the
    # host .env file as well.
    ENV_FILE.write_text(
        "".join(output),
        encoding="utf-8",
    )

def _delete_env_value(name: str) -> None:
    if not KEY_RE.fullmatch(name):
        raise ValueError("Invalid environment variable name")

    if not ENV_FILE.exists():
        raise FileNotFoundError(str(ENV_FILE))

    lines = _read_env_lines()
    found = False
    output: list[str] = []

    for line in lines:
        match = ENV_KEY_LINE_RE.match(line)

        if match and match.group(2) == name:
            found = True
            continue

        output.append(line)

    if not found:
        raise KeyError(name)

    tmp_file = ENV_FILE.with_name(".env.tmp")

    tmp_file.write_text(
        "".join(output),
        encoding="utf-8",
    )

    tmp_file.replace(ENV_FILE)


def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔙 بازگشت",
                    callback_data=NavAdminTools.MAIN,
                )
            ]
        ]
    )


def _variable_keyboard(
    index: int,
    name: str,
) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(
            text=f"✏️ ویرایش {name}",
            callback_data=f"env:edit:{index}",
        ),
        InlineKeyboardButton(
            text="🗑️ حذف",
            callback_data=f"env:delete:{index}",
        ),
    ]


def _menu_keyboard(
    variables: list[tuple[str, str]],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for index, (name, _) in enumerate(variables):
        rows.append(_variable_keyboard(index, name))

    rows.append(
        [
            InlineKeyboardButton(
                text="🔄 تازه‌سازی",
                callback_data=NavAdminTools.ENV_SETTINGS,
            )
        ]
    )

    rows.append(
        [
            InlineKeyboardButton(
                text="🔙 بازگشت",
                callback_data=NavAdminTools.MAIN,
            )
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _menu_text(
    variables: list[tuple[str, str]],
) -> str:
    lines = [
        "⚙️ <b>تنظیمات .env</b>",
        "",
        f"📄 تعداد متغیرها: <b>{len(variables)}</b>",
        "",
    ]

    for index, (name, value) in enumerate(variables, start=1):
        lines.append(
            f"{index}. <code>{html.escape(name)}</code> = "
            f"<code>{_display_value(name, value)}</code>"
        )

    lines.extend(
        [
            "",
            "✏️ برای تغییر مقدار، دکمه ویرایش همان متغیر را بزنید.",
            "🗑️ برای حذف متغیر، دکمه حذف همان متغیر را بزنید.",
            "",
            "🔐 مقادیر حساس مانند Token و Password به‌صورت مخفی نمایش داده می‌شوند.",
        ]
    )

    return "\n".join(lines)


async def _show_menu(
    target: Message | CallbackQuery,
) -> None:
    variables = _parse_env()

    if not variables:
        text = (
            "⚙️ <b>تنظیمات .env</b>\n\n"
            "❌ فایل <code>.env</code> پیدا نشد یا هیچ متغیری "
            "داخل آن وجود ندارد."
        )

        if isinstance(target, CallbackQuery):
            await target.message.edit_text(
                text,
                reply_markup=_main_keyboard(),
            )
        else:
            await target.answer(
                text,
                reply_markup=_main_keyboard(),
            )

        return

    text = _menu_text(variables)
    keyboard = _menu_keyboard(variables)

    if isinstance(target, CallbackQuery):
        await target.message.edit_text(
            text,
            reply_markup=keyboard,
        )
    else:
        await target.answer(
            text,
            reply_markup=keyboard,
        )


@router.callback_query(
    F.data == NavAdminTools.ENV_SETTINGS,
    IsAdmin(),
)
async def env_settings_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await _show_menu(callback)


@router.callback_query(
    F.data.startswith("env:edit:"),
    IsAdmin(),
)
async def env_edit_start(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    try:
        index = int(callback.data.rsplit(":", 1)[1])
    except (TypeError, ValueError):
        await callback.answer(
            "متغیر نامعتبر است.",
            show_alert=True,
        )
        return

    variables = _parse_env()

    if index < 0 or index >= len(variables):
        await callback.answer(
            "متغیر پیدا نشد.",
            show_alert=True,
        )
        return

    name, value = variables[index]

    await state.clear()
    await state.update_data(
        env_name=name,
        env_index=index,
    )
    await state.set_state(EnvSettingsStates.waiting_value)

    if _is_secret(name):
        current_instruction = (
            "🔐 مقدار فعلی به‌دلیل حساس بودن مخفی شده است."
        )
    else:
        current_instruction = (
            f"مقدار فعلی:\n<code>{_display_value(name, value)}</code>"
        )

    await callback.answer()

    await callback.message.edit_text(
        "✏️ <b>ویرایش متغیر .env</b>\n\n"
        f"🔑 نام متغیر:\n<code>{html.escape(name)}</code>\n\n"
        f"{current_instruction}\n\n"
        "مقدار جدید را ارسال کنید.\n\n"
        "⚠️ برای ذخیره مقدار خالی، فقط عبارت زیر را ارسال کنید:\n"
        "<code>__EMPTY__</code>",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔙 انصراف",
                        callback_data=NavAdminTools.ENV_SETTINGS,
                    )
                ]
            ]
        ),
    )


@router.message(
    EnvSettingsStates.waiting_value,
    IsAdmin(),
)
async def env_edit_save(
    message: Message,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    name = data.get("env_name")

    if not name:
        await state.clear()
        await message.answer(
            "❌ اطلاعات ویرایش پیدا نشد.",
            reply_markup=_main_keyboard(),
        )
        return

    if message.text is None:
        await message.answer("❌ مقدار متنی ارسال کنید.")
        return

    value = message.text

    if value == "__EMPTY__":
        value = ""

    if "\n" in value or "\r" in value:
        await message.answer(
            "❌ مقدار نمی‌تواند شامل خط جدید باشد.\n"
            "لطفاً مقدار را در یک پیام ارسال کنید."
        )
        return

    try:
        _write_env_value(name, value)
    except FileNotFoundError:
        await state.clear()
        await message.answer(
            "❌ فایل <code>.env</code> پیدا نشد.",
            reply_markup=_main_keyboard(),
        )
        return
    except Exception as exc:
        await state.clear()
        await message.answer(
            "❌ ذخیره مقدار انجام نشد.\n\n"
            f"<code>{html.escape(str(exc))}</code>",
            reply_markup=_main_keyboard(),
        )
        return

    await state.clear()

    display = _display_value(name, value)

    await message.answer(
        "✅ <b>مقدار با موفقیت ذخیره شد.</b>\n\n"
        f"🔑 <code>{html.escape(name)}</code>\n"
        f"💾 مقدار ذخیره‌شده: <code>{display}</code>\n\n"
        "📁 تغییر در فایل واقعی <code>.env</code> ذخیره شد.\n\n"
        "⚠️ برای اعمال مقدار جدید در محیط اجرای ربات، "
        "کانتینر Bot باید دوباره ایجاد/راه‌اندازی شود.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⚙️ تنظیمات .env",
                        callback_data=NavAdminTools.ENV_SETTINGS,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 بازگشت",
                        callback_data=NavAdminTools.MAIN,
                    )
                ],
            ]
        ),
    )


@router.callback_query(
    F.data.startswith("env:delete:"),
    IsAdmin(),
)
async def env_delete_confirm(
    callback: CallbackQuery,
) -> None:
    try:
        index = int(callback.data.rsplit(":", 1)[1])
    except (TypeError, ValueError):
        await callback.answer(
            "متغیر نامعتبر است.",
            show_alert=True,
        )
        return

    variables = _parse_env()

    if index < 0 or index >= len(variables):
        await callback.answer(
            "متغیر پیدا نشد.",
            show_alert=True,
        )
        return

    name, value = variables[index]

    await callback.answer()

    await callback.message.edit_text(
        "⚠️ <b>تأیید حذف متغیر</b>\n\n"
        f"🔑 متغیر:\n<code>{html.escape(name)}</code>\n\n"
        f"مقدار فعلی:\n<code>{_display_value(name, value)}</code>\n\n"
        "❗ این متغیر از فایل واقعی <code>.env</code> حذف خواهد شد.\n"
        "آیا مطمئن هستید؟",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="❌ بله، حذف شود",
                        callback_data=f"env:delete_confirm:{index}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 انصراف",
                        callback_data=NavAdminTools.ENV_SETTINGS,
                    )
                ],
            ]
        ),
    )


@router.callback_query(
    F.data.startswith("env:delete_confirm:"),
    IsAdmin(),
)
async def env_delete_execute(
    callback: CallbackQuery,
) -> None:
    try:
        index = int(callback.data.rsplit(":", 1)[1])
    except (TypeError, ValueError):
        await callback.answer(
            "متغیر نامعتبر است.",
            show_alert=True,
        )
        return

    variables = _parse_env()

    if index < 0 or index >= len(variables):
        await callback.answer(
            "متغیر پیدا نشد؛ فایل .env تغییر کرده است.",
            show_alert=True,
        )
        return

    name, _ = variables[index]

    try:
        _delete_env_value(name)
    except FileNotFoundError:
        await callback.answer(
            "فایل .env پیدا نشد.",
            show_alert=True,
        )
        return
    except KeyError:
        await callback.answer(
            "متغیر قبلاً حذف شده است.",
            show_alert=True,
        )
        await _show_menu(callback)
        return
    except Exception as exc:
        await callback.answer(
            f"حذف انجام نشد: {exc}",
            show_alert=True,
        )
        return

    await callback.answer("متغیر حذف شد.")

    variables_after = _parse_env()

    await callback.message.edit_text(
        "🗑️ <b>متغیر با موفقیت حذف شد.</b>\n\n"
        f"🔑 <code>{html.escape(name)}</code>\n\n"
        "📁 متغیر از فایل واقعی <code>.env</code> حذف شد.\n\n"
        "⚠️ برای اعمال تغییر در محیط اجرای Bot، "
        "کانتینر باید دوباره ایجاد/راه‌اندازی شود.",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="⚙️ تنظیمات .env",
                        callback_data=NavAdminTools.ENV_SETTINGS,
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔙 بازگشت",
                        callback_data=NavAdminTools.MAIN,
                    )
                ],
            ]
        ),
    )
