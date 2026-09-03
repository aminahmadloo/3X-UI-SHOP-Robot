from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, TelegramObject
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin

logger = logging.getLogger(__name__)
router = Router(name=__name__)

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS force_join_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id TEXT NOT NULL UNIQUE,
    username TEXT,
    title TEXT NOT NULL,
    join_link TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    sort_order INTEGER NOT NULL DEFAULT 100
)
"""

_MESSAGE = (
    "🔐 <b>دسترسی به ToonelVPN</b>\n\n"
    "برای استفاده از ربات و دریافت خدمات، ابتدا باید در کانال‌های زیر عضو شوید.\n\n"
    "📢 لطفاً روی دکمه عضویت هر کانال بزنید و پس از عضویت در همه کانال‌ها، "
    "روی «✅ بررسی عضویت» بزنید.\n\n"
    "✨ با عضویت در کانال‌ها، از اطلاعیه‌ها، اخبار و پیشنهادهای جدید ToonelVPN باخبر می‌شوید."
)


class ForceJoinStates(StatesGroup):
    waiting_chat = State()
    waiting_link = State()


async def ensure_table(session: AsyncSession) -> None:
    await session.execute(text(_CREATE_SQL))
    await session.commit()


async def get_active_channels(session: AsyncSession) -> list[dict[str, Any]]:
    await ensure_table(session)
    result = await session.execute(
        text("SELECT * FROM force_join_channels WHERE is_active = 1 ORDER BY sort_order, id")
    )
    return [dict(row) for row in result.mappings().all()]


async def get_all_channels(session: AsyncSession) -> list[dict[str, Any]]:
    await ensure_table(session)
    result = await session.execute(text("SELECT * FROM force_join_channels ORDER BY sort_order, id"))
    return [dict(row) for row in result.mappings().all()]


async def check_membership(bot, user_id: int, channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    valid_statuses = {"creator", "administrator", "member"}
    for channel in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel["chat_id"], user_id=user_id)
            if member.status not in valid_statuses and not (
                member.status == "restricted" and getattr(member, "is_member", False)
            ):
                missing.append(channel)
        except Exception as exc:
            logger.warning("Force-join membership check failed for channel %s: %s", channel["id"], exc)
            missing.append(channel)
    return missing


def join_keyboard(channels: list[dict[str, Any]]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for channel in channels:
        builder.row(InlineKeyboardButton(text=f"📢 عضویت در {channel['title']}", url=channel["join_link"]))
    builder.row(InlineKeyboardButton(text="✅ بررسی عضویت", callback_data="forcejoin:check"))
    return builder.as_markup()


async def show_join_message(target: Message | CallbackQuery, channels: list[dict[str, Any]]) -> None:
    if isinstance(target, CallbackQuery):
        if target.message:
            await target.message.edit_text(_MESSAGE, reply_markup=join_keyboard(channels))
        await target.answer("ابتدا در همه کانال‌ها عضو شوید.", show_alert=True)
    else:
        await target.answer(_MESSAGE, reply_markup=join_keyboard(channels))


class ForceJoinMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = getattr(event, "from_user", None)
        if user is None:
            return await handler(event, data)

        try:
            if await IsAdmin()(user_id=user.id):
                return await handler(event, data)
        except Exception:
            logger.exception("Unable to determine admin status for force-join middleware")

        chat = getattr(event, "chat", None)
        if chat is None or getattr(chat, "type", None) != "private":
            return await handler(event, data)

        session: AsyncSession | None = data.get("session")
        bot = data.get("bot")
        if session is None or bot is None:
            return await handler(event, data)

        channels = await get_active_channels(session)
        if not channels:
            return await handler(event, data)

        # The dedicated verification callback must reach its handler so it can
        # re-check membership and open the normal main menu on success.
        if getattr(event, "data", None) == "forcejoin:check":
            return await handler(event, data)

        missing = await check_membership(bot, user.id, channels)
        if not missing:
            return await handler(event, data)

        await show_join_message(event, missing)
        return None


@router.callback_query(F.data == "forcejoin:check")
async def force_join_check(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    user,
    services,
    config,
) -> None:
    channels = await get_active_channels(session)
    missing = await check_membership(callback.bot, user.tg_id, channels)
    if missing:
        await show_join_message(callback, missing)
        return

    await callback.answer("✅ عضویت شما تأیید شد.")
    try:
        await callback.message.delete()
    except Exception:
        pass

    from app.bot.routers.main_menu.handler import send_main_menu
    from app.bot.utils.constants import MAIN_MESSAGE_ID_KEY

    main_menu = await send_main_menu(
        bot=callback.bot,
        user=user,
        services=services,
        config=config,
        state=state,
        session=session,
    )
    await state.update_data({MAIN_MESSAGE_ID_KEY: main_menu.message_id})


@router.callback_query(F.data == "forcejoin:menu")
async def force_join_menu(callback: CallbackQuery, session: AsyncSession) -> None:
    if not await IsAdmin()(user_id=callback.from_user.id):
        return
    channels = await get_all_channels(session)
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="➕ افزودن کانال", callback_data="forcejoin:add"))
    for ch in channels:
        status = "🟢" if ch["is_active"] else "🔴"
        builder.row(InlineKeyboardButton(text=f"{status} {ch['title']}", callback_data=f"forcejoin:view:{ch['id']}"))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_tools"))
    await callback.answer()
    await callback.message.edit_text(
        "📢 <b>مدیریت عضویت اجباری</b>\n\n"
        "کانال‌های فعال برای کاربران نمایش داده می‌شوند و عضویت در همه آن‌ها الزامی است.\n"
        "🟢 فعال   🔴 غیرفعال",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data == "forcejoin:add")
async def force_join_add(callback: CallbackQuery, state: FSMContext) -> None:
    if not await IsAdmin()(user_id=callback.from_user.id):
        return
    await state.set_state(ForceJoinStates.waiting_chat)
    await callback.answer()
    await callback.message.edit_text(
        "➕ <b>افزودن کانال</b>\n\n"
        "شناسه کانال یا نام کاربری کانال را ارسال کنید.\n\n"
        "مثال کانال عمومی: <code>@ToonelVPN</code>\n"
        "مثال کانال خصوصی: <code>-1001234567890</code>\n\n"
        "⚠️ ربات باید در کانال ادمین باشد تا بتواند عضویت کاربران را بررسی کند."
    )


@router.message(ForceJoinStates.waiting_chat)
async def force_join_receive_chat(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not await IsAdmin()(user_id=message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw:
        await message.answer("❌ شناسه کانال معتبر نیست.")
        return
    if not raw.lstrip("-").isdigit() and not raw.startswith("@"):
        await message.answer("❌ برای کانال عمومی @username و برای کانال خصوصی chat ID را ارسال کنید.")
        return

    try:
        chat = await message.bot.get_chat(raw)
        bot_member = await message.bot.get_chat_member(chat_id=chat.id, user_id=message.bot.id)
    except Exception as exc:
        logger.warning("Failed to validate force-join channel %s: %s", raw, exc)
        await message.answer(
            "❌ کانال پیدا نشد یا ربات به آن دسترسی ندارد.\n\n"
            "مطمئن شوید ربات داخل کانال است و دسترسی ادمین دارد."
        )
        return

    if bot_member.status not in {"administrator", "creator"}:
        await message.answer("❌ ربات در این کانال ادمین نیست. ابتدا ربات را ادمین کانال کنید و دوباره تلاش کنید.")
        return

    username = getattr(chat, "username", None)
    if username:
        join_link = f"https://t.me/{username}"
        await ensure_table(session)
        result = await session.execute(text("SELECT COALESCE(MAX(sort_order), 0) FROM force_join_channels"))
        sort_order = int(result.scalar() or 0) + 10
        try:
            await session.execute(
                text("INSERT INTO force_join_channels(chat_id, username, title, join_link, is_active, sort_order) VALUES (:chat_id,:username,:title,:join_link,1,:sort_order)"),
                {"chat_id": str(chat.id), "username": username, "title": chat.title or username, "join_link": join_link, "sort_order": sort_order},
            )
            await session.commit()
        except Exception:
            await session.rollback()
            await message.answer("❌ این کانال قبلاً ثبت شده است.")
            return
        await state.clear()
        await message.answer("✅ کانال عمومی با موفقیت به عضویت اجباری اضافه شد.")
        return

    await state.update_data(
        force_join_chat_id=str(chat.id),
        force_join_title=chat.title or str(chat.id),
    )
    await state.set_state(ForceJoinStates.waiting_link)
    await message.answer(
        "🔗 <b>لینک دعوت کانال خصوصی</b>\n\n"
        "لینک دعوت دائمی کانال را ارسال کنید؛ مثلاً <code>https://t.me/+...</code>"
    )


@router.message(ForceJoinStates.waiting_link)
async def force_join_receive_link(message: Message, state: FSMContext, session: AsyncSession) -> None:
    if not await IsAdmin()(user_id=message.from_user.id):
        return
    link = (message.text or "").strip()
    if not link.startswith("https://t.me/"):
        await message.answer("❌ لینک دعوت معتبر نیست. باید با <code>https://t.me/</code> شروع شود.")
        return
    data = await state.get_data()
    chat_id = data.get("force_join_chat_id")
    title = data.get("force_join_title")
    if not chat_id or not title:
        await state.clear()
        await message.answer("❌ اطلاعات افزودن کانال منقضی شد. دوباره شروع کنید.")
        return

    await ensure_table(session)
    result = await session.execute(text("SELECT COALESCE(MAX(sort_order), 0) FROM force_join_channels"))
    sort_order = int(result.scalar() or 0) + 10
    try:
        await session.execute(
            text("INSERT INTO force_join_channels(chat_id, username, title, join_link, is_active, sort_order) VALUES (:chat_id,NULL,:title,:join_link,1,:sort_order)"),
            {"chat_id": str(chat_id), "title": title, "join_link": link, "sort_order": sort_order},
        )
        await session.commit()
    except Exception:
        await session.rollback()
        await message.answer("❌ این کانال قبلاً ثبت شده است.")
        return
    await state.clear()
    await message.answer("✅ کانال خصوصی با موفقیت اضافه شد.")


@router.callback_query(F.data.regexp(r"^forcejoin:view:\d+$"))
async def force_join_view(callback: CallbackQuery, session: AsyncSession) -> None:
    if not await IsAdmin()(user_id=callback.from_user.id):
        return
    channel_id = int(callback.data.rsplit(":", 1)[1])
    await ensure_table(session)
    result = await session.execute(text("SELECT * FROM force_join_channels WHERE id=:id"), {"id": channel_id})
    ch = result.mappings().first()
    if not ch:
        await callback.answer("کانال پیدا نشد.", show_alert=True)
        return
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔴 غیرفعال کردن" if ch["is_active"] else "🟢 فعال کردن", callback_data=f"forcejoin:toggle:{channel_id}"))
    builder.row(InlineKeyboardButton(text="🗑 حذف کانال", callback_data=f"forcejoin:delete:{channel_id}"))
    builder.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data="forcejoin:menu"))
    await callback.answer()
    await callback.message.edit_text(
        f"📢 <b>{ch['title']}</b>\n\n"
        f"وضعیت: {'فعال' if ch['is_active'] else 'غیرفعال'}\n"
        f"شناسه: <code>{ch['chat_id']}</code>\n"
        f"لینک: {ch['join_link']}",
        reply_markup=builder.as_markup(),
    )


@router.callback_query(F.data.regexp(r"^forcejoin:toggle:\d+$"))
async def force_join_toggle(callback: CallbackQuery, session: AsyncSession) -> None:
    if not await IsAdmin()(user_id=callback.from_user.id):
        return
    channel_id = int(callback.data.rsplit(":", 1)[1])
    await session.execute(text("UPDATE force_join_channels SET is_active = CASE WHEN is_active=1 THEN 0 ELSE 1 END WHERE id=:id"), {"id": channel_id})
    await session.commit()
    await callback.answer("وضعیت کانال تغییر کرد.")
    await force_join_view(callback, session)


@router.callback_query(F.data.regexp(r"^forcejoin:delete:\d+$"))
async def force_join_delete(callback: CallbackQuery, session: AsyncSession) -> None:
    if not await IsAdmin()(user_id=callback.from_user.id):
        return
    channel_id = int(callback.data.rsplit(":", 1)[1])
    await session.execute(text("DELETE FROM force_join_channels WHERE id=:id"), {"id": channel_id})
    await session.commit()
    await callback.answer("کانال حذف شد.")
    await force_join_menu(callback, session)


# Keep the existing, large admin keyboard untouched: inject one management entry
# at import time into the handler's already-imported keyboard function.
try:
    from app.bot.routers.admin_tools import admin_tools_handler as _admin_handler
    _original_admin_tools_keyboard = _admin_handler.admin_tools_keyboard

    def _admin_tools_keyboard_with_force_join(is_dev: bool):
        markup = _original_admin_tools_keyboard(is_dev)
        markup.inline_keyboard.insert(
            -1,
            [InlineKeyboardButton(text="📢 عضویت اجباری کانال‌ها", callback_data="forcejoin:menu")],
        )
        return markup

    _admin_handler.admin_tools_keyboard = _admin_tools_keyboard_with_force_join
except Exception:
    logger.exception("Unable to patch admin tools keyboard for force-join")
