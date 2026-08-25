import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.filters import IsAdmin
from app.db.models import User

logger = logging.getLogger(__name__)

router = Router(name=__name__)

ENV_CALLBACK = "admin_env"
ENV_SCAN_CALLBACK = "admin_env:scan"
ENV_BACK_CALLBACK = "admin_env:back"

# مسیرهایی که نباید برای جستجوی .env وارد آنها شویم.
SKIP_DIRS = {
    "/proc",
    "/sys",
    "/dev",
    "/run",
    "/snap",
    "/var/lib/docker/overlay2",
    "/var/lib/docker/containers",
}

# برای جلوگیری از اسکن بی‌نهایت، فقط فایل‌های کوچک و واقعی .env را قبول می‌کنیم.
MAX_ENV_SIZE = 1024 * 1024


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


def _find_env_files() -> list[Path]:
    found: list[Path] = []

    # مسیرهای محتمل ابتدا بررسی می‌شوند.
    priority_paths = [
        Path("/tmp/toonelvpn-repo/.env"),
        Path("/opt/toonelvpn-bot/.env"),
        Path("/opt/3xui-shop/.env"),
        Path("/root/.env"),
        Path("/.env"),
    ]

    seen: set[str] = set()

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
            continue

    # سپس جستجوی عمومی روی فایل‌سیستم.
    roots = [
        Path("/tmp"),
        Path("/opt"),
        Path("/root"),
        Path("/home"),
        Path("/etc"),
    ]

    for root in roots:
        if not root.exists():
            continue

        try:
            for path in root.rglob(".env"):
                try:
                    path_str = str(path)

                    if path_str in seen:
                        continue

                    if any(
                        path_str == skip or path_str.startswith(skip + "/")
                        for skip in SKIP_DIRS
                    ):
                        continue

                    if not path.is_file():
                        continue

                    if path.stat().st_size > MAX_ENV_SIZE:
                        continue

                    found.append(path)
                    seen.add(path_str)

                    if len(found) >= 50:
                        return found

                except (OSError, PermissionError):
                    continue

        except (OSError, PermissionError):
            continue

    return found


@router.callback_query(F.data == ENV_CALLBACK, IsAdmin())
async def env_main(
    callback: CallbackQuery,
    user: User,
) -> None:
    await callback.answer()

    await callback.message.edit_text(
        "⚙️ <b>مدیریت متغیرهای ENV.</b>\n\n"
        "از این بخش می‌توانید فایل‌های <code>.env</code> موجود روی سرور "
        "را پیدا و مدیریت کنید.\n\n"
        "برای شروع، دکمه «جستجوی فایل‌های ENV» را بزنید.",
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
            "❌ هیچ فایل <code>.env</code> قابل دسترسی پیدا نشد.",
            reply_markup=_env_keyboard(),
        )
        return

    text = (
        "⚙️ <b>فایل‌های ENV پیدا شده</b>\n\n"
        f"تعداد فایل‌های پیدا شده: <b>{len(found)}</b>\n\n"
        "فایل موردنظر را انتخاب کنید:"
    )

    # فعلاً فقط نمایش مسیر؛ محتوای ENV در این مرحله خوانده نمی‌شود.
    await callback.message.edit_text(
        text,
        reply_markup=_env_keyboard(found),
    )


@router.callback_query(F.data == ENV_BACK_CALLBACK, IsAdmin())
async def env_back(
    callback: CallbackQuery,
    user: User,
) -> None:
    from app.bot.routers.admin_tools.keyboard import admin_tools_keyboard
    from app.bot.filters import IsDev

    await callback.answer()

    is_dev = await IsDev()(user_id=user.tg_id)

    await callback.message.edit_text(
        "⚙️ <b>مدیریت ربات</b>",
        reply_markup=admin_tools_keyboard(is_dev),
    )


@router.callback_query(F.data.startswith("admin_env:file:"), IsAdmin())
async def env_file_selected(
    callback: CallbackQuery,
    user: User,
) -> None:
    await callback.answer(
        "این بخش در مرحله بعد فعال می‌شود.",
        show_alert=True,
    )
