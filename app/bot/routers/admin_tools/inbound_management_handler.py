import json
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsDev
from app.bot.models import ServicesContainer
from app.bot.routers.misc.keyboard import back_button, back_to_main_menu_button
from app.bot.routers.admin_tools.keyboard import (
    inbound_management_keyboard,
    inbound_selection_keyboard,
)
from app.bot.utils.navigation import NavAdminTools
from app.db.models import Server, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)

PREFIX = f"{NavAdminTools.INBOUND_MANAGEMENT}:"


async def _show_server_inbounds(
    callback: CallbackQuery,
    server: Server,
    services: ServicesContainer,
) -> None:
    inbounds = await services.server_pool.get_inbounds_for_server(server)
    if not inbounds:
        await callback.message.edit_text(
            f"🎯 <b>مدیریت اینباندهای سرویس</b>\n\n"
            f"سرور: <b>{server.name}</b>\n\n"
            "❌ اینباندی از 3X-UI دریافت نشد.",
            reply_markup=(
                InlineKeyboardBuilder()
                .button(text="🔄 تلاش مجدد", callback_data=f"{PREFIX}refresh:{server.id}")
                .button(text="🔙 بازگشت", callback_data=NavAdminTools.INBOUND_MANAGEMENT)
                .button(text="🏠 منوی اصلی", callback_data=NavAdminTools.MAIN)
                .adjust(1)
                .as_markup()
            ),
        )
        return

    configured = server.configured_inbound_ids
    configured_text = (
        "، ".join(str(value) for value in configured)
        if configured
        else "حالت پیش‌فرض (اولین اینباند)"
    )
    text = (
        "🎯 <b>مدیریت اینباندهای سرویس</b>\n\n"
        f"🖥 سرور: <b>{server.name}</b>\n"
        f"📌 انتخاب فعلی: <b>{configured_text}</b>\n\n"
        "اینباندهایی را که باید هنگام ساخت سرویس برای کلاینت استفاده شوند تیک بزنید.\n"
        "تغییرات به‌صورت لحظه‌ای ذخیره می‌شوند.\n\n"
        "اگر هیچ اینباندی انتخاب نشده باشد، رفتار قبلی حفظ می‌شود و اولین اینباند استفاده خواهد شد."
    )
    await callback.message.edit_text(
        text=text,
        reply_markup=inbound_selection_keyboard(server, inbounds),
    )


@router.callback_query(F.data == NavAdminTools.INBOUND_MANAGEMENT, IsDev())
async def callback_inbound_management(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
) -> None:
    logger.info("Dev %s opened inbound management.", user.tg_id)
    servers = await Server.get_all(session)
    text = (
        "🎯 <b>مدیریت اینباندهای سرویس</b>\n\n"
        "یک سرور را انتخاب کنید تا اینباندهای آن را ببینید و تعیین کنید کلاینت‌های جدید روی کدام اینباندها ساخته شوند."
    )
    if not servers:
        text += "\n\n❌ هیچ سروری ثبت نشده است."
    await callback.message.edit_text(
        text=text,
        reply_markup=inbound_management_keyboard(servers),
    )
    await callback.answer()


@router.callback_query(F.data.startswith(f"{PREFIX}server:"), IsDev())
async def callback_inbound_server(
    callback: CallbackQuery,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    server_id = int(callback.data.split(":")[-1])
    server = await Server.get_by_id(session=session, id=server_id)
    if not server:
        await callback.answer("سرور پیدا نشد.", show_alert=True)
        return
    await _show_server_inbounds(callback, server, services)
    await callback.answer()


@router.callback_query(F.data.startswith(f"{PREFIX}refresh:"), IsDev())
async def callback_inbound_refresh(
    callback: CallbackQuery,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    server_id = int(callback.data.split(":")[-1])
    server = await Server.get_by_id(session=session, id=server_id)
    if not server:
        await callback.answer("سرور پیدا نشد.", show_alert=True)
        return
    await services.server_pool.refresh_server(server)
    await _show_server_inbounds(callback, server, services)
    await callback.answer("اینباندها بازخوانی شدند.")


@router.callback_query(F.data.startswith(f"{PREFIX}toggle:"), IsDev())
async def callback_inbound_toggle(
    callback: CallbackQuery,
    session: AsyncSession,
    services: ServicesContainer,
) -> None:
    _, _, server_id_text, inbound_id_text = callback.data.split(":")
    server_id = int(server_id_text)
    inbound_id = int(inbound_id_text)

    server = await Server.get_by_id(session=session, id=server_id)
    if not server:
        await callback.answer("سرور پیدا نشد.", show_alert=True)
        return

    inbounds = await services.server_pool.get_inbounds_for_server(server)
    live_ids = {int(inbound.id) for inbound in inbounds}
    if inbound_id not in live_ids:
        await callback.answer("این اینباند دیگر در 3X-UI وجود ندارد.", show_alert=True)
        return

    selected = set(server.configured_inbound_ids)
    if inbound_id in selected:
        selected.remove(inbound_id)
        action = "حذف شد"
    else:
        selected.add(inbound_id)
        action = "انتخاب شد"

    selected_ids = sorted(selected)
    await Server.update(
        session=session,
        name=server.name,
        selected_inbound_ids=json.dumps(selected_ids),
    )

    server.selected_inbound_ids = json.dumps(selected_ids)
    await _show_server_inbounds(callback, server, services)
    await callback.answer(f"اینباند #{inbound_id} {action}.")
