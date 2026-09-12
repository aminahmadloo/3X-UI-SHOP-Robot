from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton

from app.bot.filters import IsAdmin
from app.bot.services.system_health_comprehensive import create_sqlite_backup, latest_sqlite_backup
from app.bot.routers.admin_tools import system_health_handler

router = Router(name=__name__)

BACKUP = "system_health:backup"
SEND_BACKUP = "system_health:send_backup"


_original_keyboard = system_health_handler.keyboard


def _keyboard_with_backup(*args, **kwargs):
    markup = _original_keyboard(*args, **kwargs)
    if not any(any(button.callback_data in {BACKUP, SEND_BACKUP} for button in row) for row in markup.inline_keyboard):
        insert_at = next((i for i, row in enumerate(markup.inline_keyboard) if any(button.callback_data == "system_health:settings" for button in row)), len(markup.inline_keyboard))
        markup.inline_keyboard.insert(insert_at, [
            InlineKeyboardButton(text="💾 Backup SQLite", callback_data=BACKUP),
            InlineKeyboardButton(text="📤 آخرین Backup", callback_data=SEND_BACKUP),
        ])
    return markup


system_health_handler.keyboard = _keyboard_with_backup


@router.callback_query(F.data == BACKUP, IsAdmin())
async def sqlite_backup(callback: CallbackQuery) -> None:
    await callback.answer("در حال تهیه Backup SQLite...")
    path, error = await create_sqlite_backup()
    if error or path is None:
        await callback.message.answer(f"❌ تهیه Backup ناموفق بود:\n<code>{error or 'نامشخص'}</code>")
        return
    await callback.message.answer_document(FSInputFile(path), caption=f"💾 Backup SQLite آماده شد\n<code>{path.name}</code>")


@router.callback_query(F.data == SEND_BACKUP, IsAdmin())
async def sqlite_send_backup(callback: CallbackQuery) -> None:
    await callback.answer("در حال آماده‌سازی آخرین Backup...")
    path = await latest_sqlite_backup()
    if path is None:
        path, error = await create_sqlite_backup()
        if error or path is None:
            await callback.message.answer(f"❌ Backup قابل ارسال نیست:\n<code>{error or 'نامشخص'}</code>")
            return
    await callback.message.answer_document(FSInputFile(path), caption=f"📤 آخرین Backup SQLite\n<code>{path.name}</code>")
