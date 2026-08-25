import logging
import os
import re
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.filters import IsAdmin
from app.db.models import User

logger = logging.getLogger(__name__)

router = Router(name=__name__)

ENV_CALLBACK = "admin_env"
ENV_SCAN_CALLBACK = "admin_env:scan"
ENV_BACK_CALLBACK = "admin_env:back"
ENV_REFRESH_CALLBACK = "admin_env:refresh"

ENV_ADD_CALLBACK = "admin_env:add"
ENV_DELETE_CALLBACK = "admin_env:delete"
ENV_DELETE_CONFIRM = "admin_env:delete_confirm"
ENV_DELETE_CANCEL = "admin_env:delete_cancel"

MAX_ENV_SIZE = 1024 * 1024

# فقط فایل‌هایی که واقعاً از داخل کانتینر قابل دسترسی هستند.
ENV_SEARCH_ROOTS = [
    Path("/app"),
    Path("/root"),
    Path("/opt"),
    Path("/tmp"),
    Path("/etc"),
]

# متغیرهایی که مقدارشان نباید در Telegram نمایش داده شود.
SECRET_PATTERNS = (
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "SECRET",
    "PRIVATE",
    "API_KEY",
    "ACCESS_KEY",
    "AUTH",
    "CREDENTIAL",
)


class EnvStates(StatesGroup):
    waiting_for_value = State()
    waiting_for_new_name = State()
    waiting_for_new_value = State()


def _is_secret(name: str) -> bool:
    upper = name.upper()
    return any(pattern in upper for pattern in SECRET_PATTERNS)


def _mask_value(value: str) -> str:
    if not value:
        return "—"

    if len(value) <= 6:
        return "••••••"

    return value[:3] + "••••••" + value[-3:]


def _find_env_files() -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()

    priority_paths = [
        Path("/app/.env"),
        Path("/app/data/.env"),
        Path("/root/.env"),
        Path("/opt/toonelvpn-bot/.env"),
        Path("/opt/3xui-shop/.env"),
    ]

    for path in priority_paths:
        try:
            if (
                path.is_file()
                and path.stat().st_size <= MAX_ENV_SIZE
                and str(path) not in seen
            ):
                found.append(path)
                seen.add(str(path))
        except (OSError, PermissionError):
            pass

    for root in ENV_SEARCH_ROOTS:
        if not root.exists():
            continue

        try:
            for path in root.rglob(".env"):
                try:
                    path_str = str(path)

                    if path_str in seen:
                        continue

                    if not path.is_file():
                        continue

                    if path.stat().st_size > MAX_ENV_SIZE:
                        continue

                    found.append(path)
                    seen.add(path_str)

                    if len(found) >= 30:
                        return found

                except (OSError, PermissionError):
                    continue

        except (OSError, PermissionError):
            continue

    return found


def _parse_env(path: Path) -> list[tuple[str, str, str]]:
    """
    Returns:
        (name, value, original_line)
    """
    result = []

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return result

    for line in content.splitlines():
        stripped = line.strip()

        if not stripped or stripped.startswith("#"):
            continue

        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$", line)

        if not match:
            continue

        name = match.group(1)
        value = match.group(2)

        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in ("'", '"')
        ):
            value = value[1:-1]

        result.append((name, value, line))

    return result


def _env_keyboard(found: list[Path] | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    if found:
        for index, path in enumerate(found[:20]):
            builder.row(
                InlineKeyboardButton(
                    text=f"📄 {path}",
                    callback_data=f"admin_env:file:{index}",
                )
            )

    builder.row(
        InlineKeyboardButton(
            text="🔎 جستجوی مجدد",
            callback_data=ENV_SCAN_CALLBACK,
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="⬅️ بازگشت به مدیریت",
            callback_data=ENV_BACK_CALLBACK,
        )
    )

    return builder.as_markup()


def _variables_keyboard(
    path_index: int,
    variables: list[tuple[str, str, str]],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for index, (name, value, _) in enumerate(variables):
        shown = _mask_value(value) if _is_secret(name) else value

        if len(shown) > 35:
            shown = shown[:32] + "..."

        builder.row(
            InlineKeyboardButton(
                text=f"✏️ {name} = {shown}",
                callback_data=f"admin_env:edit:{path_index}:{index}",
            ),
            InlineKeyboardButton(
                text="🗑",
                callback_data=f"admin_env:delete:{path_index}:{index}",
            ),
        )

    builder.row(
        InlineKeyboardButton(
            text="➕ افزودن متغیر",
            callback_data=ENV_ADD_CALLBACK,
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="🔄 بازخوانی",
            callback_data=f"admin_env:open:{path_index}",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="⬅️ فایل‌های ENV",
            callback_data=ENV_SCAN_CALLBACK,
        )
    )

    return builder.as_markup()


def _get_env_path(index: int) -> Path | None:
    files = _find_env_files()

    if index < 0 or index >= len(files):
        return None

    return files[index]


def _env_variable_exists(path: Path, key: str) -> bool:
    """بررسی وجود یک متغیر ENV."""
    return any(name == key for name, _, _ in _parse_env(path))


def _append_env_value(path: Path, key: str, value: str) -> bool:
    """افزودن متغیر جدید به فایل ENV."""
    try:
        if not path.is_file():
            return False

        original = path.read_text(encoding="utf-8")

        if _env_variable_exists(path, key):
            return False

        separator = "" if not original or original.endswith("\n") else "\n"

        with path.open("a", encoding="utf-8") as f:
            f.write(f"{separator}{key}={value}\n")
            f.flush()

        return True

    except (OSError, UnicodeError) as exc:
        logger.exception(
            "Failed to append ENV variable %s in %s: %s",
            key,
            path,
            exc,
        )
        return False


def _delete_env_value(path: Path, key: str) -> bool:
    """حذف تعریف یک متغیر ENV بدون جایگزینی خود فایل."""
    try:
        if not path.is_file():
            return False

        original = path.read_text(encoding="utf-8")
        lines = original.splitlines(keepends=True)

        key_pattern = re.compile(
            rf"^\s*(?:export\s+)?{re.escape(key)}\s*="
        )

        deleted = False
        updated_lines = []

        for line in lines:
            if not deleted and key_pattern.match(line):
                deleted = True
                continue

            updated_lines.append(line)

        if not deleted:
            return False

        updated = "".join(updated_lines)

        with path.open("w", encoding="utf-8") as f:
            f.write(updated)
            f.flush()

        return True

    except (OSError, UnicodeError) as exc:
        logger.exception(
            "Failed to delete ENV variable %s in %s: %s",
            key,
            path,
            exc,
        )
        return False


def _update_env_value(path: Path, key: str, new_value: str) -> bool:
    """
    مقدار یک متغیر ENV را مستقیماً داخل فایل به‌روزرسانی می‌کند.

    توجه:
    فایل .env ممکن است bind-mounted باشد؛ بنابراین نباید از os.replace()
    برای جایگزین کردن فایل استفاده کنیم.
    """
    try:
        if not path.is_file():
            return False

        original = path.read_text(encoding="utf-8")

        lines = original.splitlines(keepends=True)
        key_prefix = f"{key}="

        found = False
        updated_lines = []

        for line in lines:
            stripped = line.lstrip()

            if stripped.startswith("#"):
                updated_lines.append(line)
                continue

            if stripped.startswith(key_prefix):
                newline = "\n" if line.endswith("\n") else ""
                updated_lines.append(f"{key}={new_value}{newline}")
                found = True
            else:
                updated_lines.append(line)

        if not found:
            return False

        updated = "".join(updated_lines)

        # مستقیماً خود فایل bind-mounted را بازنویسی می‌کنیم.
        with path.open("w", encoding="utf-8") as f:
            f.write(updated)
            f.flush()

        return True

    except (OSError, UnicodeError) as exc:
        logger.exception(
            "Failed to update ENV variable %s in %s: %s",
            key,
            path,
            exc,
        )
        return False

async def _show_env_file(
    callback: CallbackQuery,
    path_index: int,
) -> None:
    """نمایش متغیرهای یک فایل ENV."""

    path = _get_env_path(path_index)

    if path is None:
        await callback.message.edit_text(
            "⚙️ <b>مدیریت متغیرهای ENV.</b>\n\n"
            "❌ فایل ENV موردنظر دیگر قابل دسترسی نیست.\n\n"
            "لطفاً دوباره جستجو کنید.",
            reply_markup=_env_keyboard(),
        )
        return

    variables = _parse_env(path)

    if not variables:
        await callback.message.edit_text(
            "⚙️ <b>مدیریت متغیرهای ENV.</b>\n\n"
            f"📄 فایل: <code>{path}</code>\n\n"
            "❌ هیچ متغیر ENV قابل شناسایی در این فایل پیدا نشد.",
            reply_markup=_variables_keyboard(path_index, variables),
        )
        return

    text = (
        "⚙️ <b>مدیریت متغیرهای ENV</b>\n\n"
        f"📄 فایل: <code>{path}</code>\n"
        f"تعداد متغیرها: <b>{len(variables)}</b>\n\n"
        "🔐 مقادیر حساس به‌صورت مخفی نمایش داده می‌شوند.\n"
        "برای تغییر هر متغیر، روی آن بزنید:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=_variables_keyboard(path_index, variables),
    )


@router.callback_query(F.data == ENV_CALLBACK, IsAdmin())
async def env_main(
    callback: CallbackQuery,
    user: User,
) -> None:
    await callback.answer()

    await callback.message.edit_text(
        "⚙️ <b>مدیریت متغیرهای ENV.</b>\n\n"
        "فایل‌های <code>.env</code> قابل دسترسی از داخل ربات "
        "را می‌توانید از این بخش مدیریت کنید.\n\n"
        "فایل ENV اصلی ربات از مسیر <code>/app/.env</code> "
        "در دسترس است.",
        reply_markup=_env_keyboard(),
    )


@router.callback_query(F.data == ENV_SCAN_CALLBACK, IsAdmin())
async def env_scan(
    callback: CallbackQuery,
    user: User,
) -> None:
    await callback.answer("🔎 در حال جستجوی فایل‌های .env ...")

    found = _find_env_files()

    if not found:
        await callback.message.edit_text(
            "⚙️ <b>مدیریت متغیرهای ENV.</b>\n\n"
            "❌ هیچ فایل <code>.env</code> قابل دسترسی پیدا نشد.\n\n"
            "مسیرهای قابل بررسی داخل کانتینر بررسی شدند.",
            reply_markup=_env_keyboard(),
        )
        return

    text = (
        "⚙️ <b>فایل‌های ENV پیدا شده</b>\n\n"
        f"تعداد فایل‌های پیدا شده: <b>{len(found)}</b>\n\n"
        "فایل موردنظر را انتخاب کنید:"
    )

    await callback.message.edit_text(
        text,
        reply_markup=_env_keyboard(found),
    )


@router.callback_query(F.data.startswith("admin_env:file:"), IsAdmin())
async def env_file_selected(
    callback: CallbackQuery,
    user: User,
) -> None:
    await callback.answer()

    try:
        path_index = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await callback.answer("❌ فایل نامعتبر است.", show_alert=True)
        return

    await _show_env_file(callback, path_index)


@router.callback_query(F.data.startswith("admin_env:open:"), IsAdmin())
async def env_file_open(
    callback: CallbackQuery,
    user: User,
) -> None:
    await callback.answer("🔄 در حال بازخوانی...")

    try:
        path_index = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await callback.answer("❌ فایل نامعتبر است.", show_alert=True)
        return

    await _show_env_file(callback, path_index)


@router.callback_query(F.data.startswith("admin_env:edit:"), IsAdmin())
async def env_edit(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    await callback.answer()

    parts = callback.data.split(":")

    try:
        path_index = int(parts[2])
        variable_index = int(parts[3])
    except (ValueError, IndexError):
        await callback.answer("❌ متغیر نامعتبر است.", show_alert=True)
        return

    path = _get_env_path(path_index)

    if path is None:
        await callback.answer("❌ فایل ENV پیدا نشد.", show_alert=True)
        return

    variables = _parse_env(path)

    if variable_index < 0 or variable_index >= len(variables):
        await callback.answer("❌ متغیر پیدا نشد.", show_alert=True)
        return

    name, value, _ = variables[variable_index]

    await state.set_state(EnvStates.waiting_for_value)
    await state.update_data(
        env_path=str(path),
        env_key=name,
        env_path_index=path_index,
    )

    current = _mask_value(value) if _is_secret(name) else value

    await callback.message.edit_text(
        "✏️ <b>ویرایش متغیر ENV</b>\n\n"
        f"📄 فایل: <code>{path}</code>\n"
        f"🔑 نام متغیر: <code>{name}</code>\n"
        f"📌 مقدار فعلی: <code>{current}</code>\n\n"
        "مقدار جدید را در یک پیام ارسال کنید.\n\n"
        "⚠️ اگر این متغیر حساس است، مقدار ارسال‌شده در چت قابل مشاهده خواهد بود؛ "
        "پس بعد از ارسال، پیام خود را حذف کنید.",
    )


@router.message(EnvStates.waiting_for_value, IsAdmin())
async def env_value_received(
    message: Message,
    user: User,
    state: FSMContext,
) -> None:
    data = await state.get_data()

    path_str = data.get("env_path")
    key = data.get("env_key")
    path_index = data.get("env_path_index")

    if not path_str or not key:
        await state.clear()
        await message.answer("❌ اطلاعات ویرایش منقضی شده است.")
        return

    new_value = message.text or ""

    if "\n" in new_value or "\r" in new_value:
        await message.answer(
            "❌ مقدار باید تک‌خطی باشد. دوباره ارسال کنید."
        )
        return

    path = Path(path_str)

    if not path.is_file():
        await state.clear()
        await message.answer("❌ فایل ENV دیگر وجود ندارد.")
        return

    if not _update_env_value(path, key, new_value):
        await state.clear()
        await message.answer(
            "❌ ذخیره مقدار جدید انجام نشد."
        )
        return

    await state.clear()

    await message.answer(
        "✅ <b>متغیر با موفقیت ذخیره شد.</b>\n\n"
        f"🔑 <code>{key}</code>\n"
        "📁 فایل ENV به‌روزرسانی شد.",
    )

    # نمایش دوباره پنل
    if isinstance(path_index, int):
        variables = _parse_env(path)

        await message.answer(
            "⚙️ <b>متغیرهای ENV</b>\n\n"
            f"📄 <code>{path}</code>\n\n"
            "برای ویرایش یک متغیر، آن را انتخاب کنید:",
            reply_markup=_variables_keyboard(path_index, variables),
        )



@router.callback_query(F.data == ENV_ADD_CALLBACK, IsAdmin())
async def env_add_start(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    await callback.answer()

    await state.clear()
    await state.set_state(EnvStates.waiting_for_new_name)

    await callback.message.edit_text(
        "➕ <b>افزودن متغیر ENV</b>\n\n"
        "نام متغیر جدید را ارسال کنید.\n\n"
        "مثال:\n"
        "<code>NEW_SETTING</code>\n\n"
        "نام متغیر باید فقط شامل حروف انگلیسی، اعداد و <code>_</code> باشد "
        "و با حرف یا <code>_</code> شروع شود.\n\n"
        "❌ برای انصراف، /cancel را ارسال کنید.",
    )


@router.message(EnvStates.waiting_for_new_name, IsAdmin())
async def env_add_name_received(
    message: Message,
    user: User,
    state: FSMContext,
) -> None:
    name = (message.text or "").strip()

    if name == "/cancel":
        await state.clear()
        await message.answer("❌ عملیات افزودن متغیر لغو شد.")
        return

    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        await message.answer(
            "❌ نام متغیر نامعتبر است.\n\n"
            "نام باید با حرف انگلیسی یا <code>_</code> شروع شود "
            "و فقط شامل حروف، اعداد و <code>_</code> باشد.\n\n"
            "مثال: <code>NEW_SETTING</code>"
        )
        return

    path_index = 0

    await state.update_data(
        env_name=name,
        env_path_index=path_index,
    )

    path = _get_env_path(path_index)

    if path is None:
        await state.clear()
        await message.answer(
            "❌ فایل ENV دیگر قابل دسترسی نیست. لطفاً دوباره جستجو کنید."
        )
        return

    if _env_variable_exists(path, name):
        await message.answer(
            f"❌ متغیر <code>{name}</code> از قبل در این فایل وجود دارد."
        )
        return

    await state.set_state(EnvStates.waiting_for_new_value)

    await message.answer(
        "➕ <b>افزودن متغیر ENV</b>\n\n"
        f"🔑 نام متغیر: <code>{name}</code>\n\n"
        "مقدار متغیر جدید را در یک پیام ارسال کنید.\n\n"
        "❌ برای انصراف، /cancel را ارسال کنید."
    )


@router.message(EnvStates.waiting_for_new_value, IsAdmin())
async def env_add_value_received(
    message: Message,
    user: User,
    state: FSMContext,
) -> None:
    new_value = message.text or ""

    if new_value.strip() == "/cancel":
        await state.clear()
        await message.answer("❌ عملیات افزودن متغیر لغو شد.")
        return

    data = await state.get_data()
    name = data.get("env_name")
    path_index = data.get("env_path_index", 0)

    if not name:
        await state.clear()
        await message.answer(
            "❌ اطلاعات عملیات از بین رفته است. دوباره تلاش کنید."
        )
        return

    path = _get_env_path(int(path_index))

    if path is None:
        await state.clear()
        await message.answer(
            "❌ فایل ENV دیگر قابل دسترسی نیست. لطفاً دوباره جستجو کنید."
        )
        return

    if _env_variable_exists(path, name):
        await state.clear()
        await message.answer(
            f"❌ متغیر <code>{name}</code> از قبل وجود دارد."
        )
        return

    if not _append_env_value(path, name, new_value):
        await state.clear()
        await message.answer(
            "❌ افزودن متغیر جدید انجام نشد."
        )
        return

    await state.clear()

    variables = _parse_env(path)

    await message.answer(
        "✅ <b>متغیر جدید با موفقیت اضافه شد.</b>\n\n"
        f"📄 فایل: <code>{path}</code>\n"
        f"🔑 متغیر: <code>{name}</code>\n"
        f"📊 تعداد متغیرها: <b>{len(variables)}</b>",
        reply_markup=_variables_keyboard(int(path_index), variables),
    )


@router.callback_query(F.data.startswith("admin_env:delete:"), IsAdmin())
async def env_delete_start(
    callback: CallbackQuery,
    user: User,
) -> None:
    await callback.answer()

    parts = callback.data.split(":")

    try:
        path_index = int(parts[2])
        variable_index = int(parts[3])
    except (ValueError, IndexError, AttributeError):
        await callback.answer(
            "❌ متغیر نامعتبر است.",
            show_alert=True,
        )
        return

    path = _get_env_path(path_index)

    if path is None:
        await callback.answer(
            "❌ فایل ENV دیگر قابل دسترسی نیست.",
            show_alert=True,
        )
        return

    variables = _parse_env(path)

    if variable_index < 0 or variable_index >= len(variables):
        await callback.answer(
            "❌ متغیر دیگر وجود ندارد. لطفاً بازخوانی کنید.",
            show_alert=True,
        )
        return

    name, value, _ = variables[variable_index]

    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="✅ بله، حذف کن",
            callback_data=f"{ENV_DELETE_CONFIRM}:{path_index}:{variable_index}",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="❌ انصراف",
            callback_data=f"{ENV_DELETE_CANCEL}:{path_index}",
        )
    )

    await callback.message.edit_text(
        "⚠️ <b>حذف متغیر ENV</b>\n\n"
        f"📄 فایل: <code>{path}</code>\n"
        f"🔑 متغیر: <code>{name}</code>\n\n"
        "آیا مطمئن هستید که می‌خواهید این متغیر را حذف کنید؟\n\n"
        "⚠️ تعریف این متغیر از فایل <code>.env</code> حذف خواهد شد.",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(
    F.data.startswith("admin_env:delete_confirm:"),
    IsAdmin(),
)
async def env_delete_confirm(
    callback: CallbackQuery,
    user: User,
) -> None:
    await callback.answer()

    parts = callback.data.split(":")

    try:
        path_index = int(parts[2])
        variable_index = int(parts[3])
    except (ValueError, IndexError, AttributeError):
        await callback.answer(
            "❌ اطلاعات حذف نامعتبر است.",
            show_alert=True,
        )
        return

    path = _get_env_path(path_index)

    if path is None:
        await callback.answer(
            "❌ فایل ENV دیگر قابل دسترسی نیست.",
            show_alert=True,
        )
        return

    variables = _parse_env(path)

    if variable_index < 0 or variable_index >= len(variables):
        await callback.answer(
            "❌ متغیر دیگر وجود ندارد.",
            show_alert=True,
        )
        return

    name, _, _ = variables[variable_index]

    if not _delete_env_value(path, name):
        await callback.answer(
            "❌ حذف متغیر انجام نشد.",
            show_alert=True,
        )
        return

    variables = _parse_env(path)

    await callback.message.edit_text(
        "✅ <b>متغیر با موفقیت حذف شد.</b>\n\n"
        f"📄 فایل: <code>{path}</code>\n"
        f"🗑 متغیر حذف‌شده: <code>{name}</code>\n\n"
        f"تعداد متغیرها: <b>{len(variables)}</b>\n\n"
        "برای تغییر هر متغیر، روی آن بزنید:",
        reply_markup=_variables_keyboard(path_index, variables),
    )


@router.callback_query(
    F.data.startswith("admin_env:delete_cancel:"),
    IsAdmin(),
)
async def env_delete_cancel(
    callback: CallbackQuery,
    user: User,
) -> None:
    await callback.answer("❌ حذف لغو شد.")

    try:
        path_index = int(callback.data.rsplit(":", 1)[1])
    except (ValueError, AttributeError):
        await callback.answer(
            "❌ فایل نامعتبر است.",
            show_alert=True,
        )
        return

    path = _get_env_path(path_index)

    if path is None:
        await callback.message.edit_text(
            "⚙️ <b>مدیریت متغیرهای ENV</b>\n\n"
            "❌ فایل ENV دیگر قابل دسترسی نیست.",
            reply_markup=_env_keyboard(),
        )
        return

    variables = _parse_env(path)

    await callback.message.edit_text(
        "⚙️ <b>مدیریت متغیرهای ENV</b>\n\n"
        f"📄 فایل: <code>{path}</code>\n"
        f"تعداد متغیرها: <b>{len(variables)}</b>\n\n"
        "🔐 مقادیر حساس به‌صورت مخفی نمایش داده می‌شوند.\n"
        "برای تغییر هر متغیر، روی آن بزنید:",
        reply_markup=_variables_keyboard(path_index, variables),
    )


@router.callback_query(F.data == ENV_BACK_CALLBACK, IsAdmin())
async def env_back(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
) -> None:
    from app.bot.routers.admin_tools.keyboard import admin_tools_keyboard
    from app.bot.filters import IsDev

    await state.clear()
    await callback.answer()

    is_dev = await IsDev()(user_id=user.tg_id)

    await callback.message.edit_text(
        "⚙️ <b>مدیریت ربات</b>",
        reply_markup=admin_tools_keyboard(is_dev),
    )
