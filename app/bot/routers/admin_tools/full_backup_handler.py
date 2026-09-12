from __future__ import annotations

import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools
from app.bot.services.full_backup import cleanup_full_backup, create_full_backup
from app.config import Config
from app.db.models import User

logger = logging.getLogger(__name__)
router = Router(name=__name__)

FULL_BACKUP_MENU = "full_backup:menu"
FULL_BACKUP_CREATE = "full_backup:create"


def full_backup_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📦 تهیه Backup کامل", callback_data=FULL_BACKUP_CREATE))
    builder.row(InlineKeyboardButton(text="⬅️ بازگشت", callback_data=NavAdminTools.MAIN))
    return builder.as_markup()


@router.callback_query(F.data == FULL_BACKUP_MENU, IsAdmin())
async def full_backup_menu(callback: CallbackQuery, config: Config) -> None:
    if callback.from_user.id != config.bot.DEV_ID:
        await callback.answer("این بخش فقط برای توسعه‌دهنده اصلی فعال است.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "💾 <b>Backup کامل ربات</b>\n\n"
        "این Backup شامل برنامه مستقر، دیتابیس SQLite، داده‌های runtime، تنظیمات .env و داده‌های Redis است.\n"
        "فایل‌های بزرگ به چند بخش کمتر از 49MB تقسیم و به‌ترتیب ارسال می‌شوند؛ بنابراین نیازی به Local Bot API Server نیست.\n\n"
        "⚠️ فایل Backup شامل اطلاعات محرمانه است و فقط به توسعه‌دهنده اصلی ارسال می‌شود.",
        reply_markup=full_backup_keyboard(),
    )


@router.callback_query(F.data == FULL_BACKUP_CREATE, IsAdmin())
async def create_full_backup_handler(
    callback: CallbackQuery,
    user: User,
    config: Config,
) -> None:
    if user.tg_id != config.bot.DEV_ID:
        await callback.answer("این عملیات فقط برای توسعه‌دهنده اصلی مجاز است.", show_alert=True)
        return

    await callback.answer("در حال تهیه Backup کامل...")
    status_message = await callback.message.answer(
        "⏳ <b>در حال تهیه Backup کامل ربات...</b>\n"
        "ممکن است بسته به حجم داده‌ها کمی زمان ببرد."
    )

    path: Path | None = None
    parts: tuple[Path, ...] = ()
    try:
        result = await create_full_backup(config)
        path = result.path
        parts = result.parts
        size_mb = result.size_bytes / (1024 * 1024)
        part_count = len(parts)

        await status_message.edit_text(
            "📤 <b>Backup ساخته شد؛ در حال ارسال...</b>\n"
            f"📦 حجم کل: <code>{size_mb:.2f} MB</code>\n"
            f"🧩 تعداد بخش‌ها: <code>{part_count}</code>\n"
            "بخش‌ها به‌ترتیب ارسال می‌شوند."
        )

        for index, part in enumerate(parts, start=1):
            part_size_mb = part.stat().st_size / (1024 * 1024)
            if part_count == 1:
                caption = (
                    "💾 <b>Backup کامل ToonelVPN</b>\n\n"
                    f"📦 حجم: <code>{size_mb:.2f} MB</code>\n"
                    f"🔑 Redis keys: <code>{result.redis_keys}</code>\n"
                    f"🔐 SHA-256:\n<code>{result.sha256}</code>"
                )
            else:
                caption = (
                    "💾 <b>Backup کامل ToonelVPN</b>\n"
                    f"🧩 بخش <code>{index}/{part_count}</code>\n"
                    f"📦 حجم این بخش: <code>{part_size_mb:.2f} MB</code>\n"
                    f"📦 حجم کل: <code>{size_mb:.2f} MB</code>\n"
                    f"🔐 SHA-256 کل فایل پس از اتصال بخش‌ها:\n<code>{result.sha256}</code>\n\n"
                    "⚠️ بخش‌ها را به ترتیب نگه دارید و طبق RESTORE.md به هم متصل کنید."
                )
            await callback.message.answer_document(FSInputFile(part), caption=caption)

        await status_message.edit_text(
            "✅ <b>Backup کامل با موفقیت ساخته و ارسال شد.</b>\n"
            f"📦 حجم کل: <code>{size_mb:.2f} MB</code>\n"
            f"🧩 تعداد بخش‌ها: <code>{part_count}</code>\n"
            f"🔐 SHA-256: <code>{result.sha256}</code>"
        )
        logger.info(
            "Full backup created and sent by developer %s: path=%s parts=%d size=%d redis_keys=%d sha256=%s",
            user.tg_id,
            path,
            part_count,
            result.size_bytes,
            result.redis_keys,
            result.sha256,
        )
    except TelegramAPIError as exception:
        logger.exception("Telegram failed while sending full backup: %s", exception)
        await status_message.edit_text("❌ Backup ساخته شد اما ارسال آن در تلگرام ناموفق بود.")
    except Exception as exception:
        logger.exception("Full backup creation failed: %s", exception)
        await status_message.edit_text(f"❌ تهیه Backup کامل ناموفق بود.\n<code>{exception}</code>")
    finally:
        if path is not None:
            await cleanup_full_backup(path, parts)


# The existing Admin Tools router already owns the main management menu. Importing
# it here keeps this feature self-contained and avoids changing the global router
# ordering; aiogram supports nested routers as long as there is no circular chain.
from app.bot.routers.admin_tools import admin_tools_handler  # noqa: E402

_original_admin_tools_keyboard = admin_tools_handler.admin_tools_keyboard


def _admin_tools_keyboard_with_full_backup(is_dev: bool) -> InlineKeyboardMarkup:
    markup = _original_admin_tools_keyboard(is_dev)
    if not any(
        button.callback_data == FULL_BACKUP_MENU
        for row in markup.inline_keyboard
        for button in row
    ):
        insert_at = max(len(markup.inline_keyboard) - 1, 0)
        markup.inline_keyboard.insert(
            insert_at,
            [InlineKeyboardButton(text="💾 Backup کامل ربات", callback_data=FULL_BACKUP_MENU)],
        )
    return markup


admin_tools_handler.admin_tools_keyboard = _admin_tools_keyboard_with_full_backup
admin_tools_handler.router.include_router(router)
