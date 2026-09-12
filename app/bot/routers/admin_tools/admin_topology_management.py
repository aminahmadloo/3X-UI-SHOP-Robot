from __future__ import annotations

import json
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsDev
from app.bot.routers.misc.keyboard import back_button, back_to_main_menu_button
from app.bot.services.admin_topology import get_server_inbound_groups, get_server_nodes, group_counts
from app.bot.utils.navigation import NavAdminTools
from app.config import Config
from app.db.models import Server, User

logger = logging.getLogger(__name__)
router = Router(name=__name__)
PREFIX = "admin_topology:"


def enhanced_servers_keyboard(servers: list[Server]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for server in servers:
        status = "🟢" if server.online else "🔴"
        builder.row(
            InlineKeyboardButton(
                text=f"{status} 🖥 {server.name}",
                callback_data=f"{PREFIX}server:{server.id}",
            )
        )
    builder.row(
        InlineKeyboardButton(text="🔄 همگام‌سازی سرورها", callback_data=NavAdminTools.SYNC_SERVERS),
        InlineKeyboardButton(text="➕ افزودن سرور", callback_data=NavAdminTools.ADD_SERVER),
    )
    builder.row(back_button(NavAdminTools.MAIN))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def _server_detail_keyboard(server: Server, node_count: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔄 بازخوانی سرور و نودها", callback_data=f"{PREFIX}server:{server.id}"),
    )
    builder.row(
        InlineKeyboardButton(text="✏️ ویرایش", callback_data=NavAdminTools.EDIT_SERVER + f"_{server.name}"),
        InlineKeyboardButton(text="📡 Ping", callback_data=NavAdminTools.PING_SERVER + f"_{server.name}"),
    )
    builder.row(
        InlineKeyboardButton(text="🗑 حذف سرور", callback_data=NavAdminTools.DELETE_SERVER + f"_{server.name}"),
    )
    builder.row(back_button(NavAdminTools.SERVER_MANAGEMENT))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


async def _render_server(callback: CallbackQuery, server: Server, config: Config) -> None:
    nodes = await get_server_nodes(server, config)
    status = "🟢 آنلاین" if server.online else "🔴 آفلاین"
    lines = [
        "🌐 <b>مدیریت سرور</b>",
        "",
        f"🖥 <b>{server.name}</b>",
        f"آدرس پنل: <code>{server.host}</code>",
        f"وضعیت اتصال: {status}",
        f"حداکثر کلاینت: <b>{server.max_clients}</b>",
        "",
        f"🧩 <b>نودهای زیرمجموعه: {len(nodes)}</b>",
    ]
    if nodes:
        for node in nodes:
            online = "🟢" if str(node.get("status", "")).lower() == "online" and node.get("enable", True) else "🔴"
            lines.append(
                f"\n{online} <b>{node['name']}</b>"
                f"\n├ آدرس: <code>{node['address']}:{node['port']}</code>"
                f"\n├ وضعیت: {node['status']} | Ping: {node.get('latency_ms', '-')} ms"
                f"\n├ CPU: {node.get('cpu_percent', '-')}% | RAM: {node.get('memory_percent', '-')}%"
                f"\n└ Inbound: {node.get('inbound_count', 0)} | Client: {node.get('client_count', 0)} | Online: {node.get('online_count', 0)}"
            )
    else:
        lines.append("\n⚪️ این سرور نود مدیریتشده‌ای ندارد یا فهرست نودها قابل دریافت نیست.")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=_server_detail_keyboard(server, len(nodes)),
    )


@router.callback_query(F.data.startswith(f"{PREFIX}server:"), IsDev())
async def callback_topology_server(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    server_id = int(callback.data.rsplit(":", 1)[1])
    server = await Server.get_by_id(session=session, id=server_id)
    if server is None:
        await callback.answer("سرور پیدا نشد.", show_alert=True)
        return
    await _render_server(callback, server, config)
    await callback.answer()


def enhanced_inbound_management_keyboard(servers: list[Server]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for server in servers:
        status = "🟢" if server.online else "🔴"
        builder.row(
            InlineKeyboardButton(
                text=f"{status} 🖥 {server.name} — مشاهده سرور اصلی + نودها",
                callback_data=f"{PREFIX}inbounds:{server.id}",
            )
        )
    builder.row(back_button(NavAdminTools.MAIN))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def _inbound_selection_keyboard(server: Server, groups: list[dict]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    selected = set(server.configured_inbound_ids)
    for group in groups:
        enabled, total = group_counts(group)
        builder.row(
            InlineKeyboardButton(
                text=f"{group['flag']} {group['title']} — {enabled}/{total} فعال",
                callback_data=f"{PREFIX}noop",
            )
        )
        for inbound in group.get("inbounds", []):
            mark = "☑️" if int(inbound["id"]) in selected else "⬜️"
            state = "فعال" if inbound.get("enable") else "غیرفعال"
            builder.row(
                InlineKeyboardButton(
                    text=f"{mark} #{inbound['id']} | {inbound['remark']} | {inbound['protocol']}:{inbound['port']} | {state}",
                    callback_data=f"{PREFIX}toggle:{server.id}:{inbound['id']}",
                )
            )
    builder.row(InlineKeyboardButton(text="🔄 بازخوانی سرور و نودها", callback_data=f"{PREFIX}inbounds:{server.id}"))
    builder.row(back_button(NavAdminTools.INBOUND_MANAGEMENT))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


async def _render_inbounds(callback: CallbackQuery, server: Server, config: Config, session: AsyncSession) -> None:
    groups = await get_server_inbound_groups(server, config)
    lines = [
        "🎯 <b>مدیریت اینباندهای سرویس</b>",
        "",
        f"🖥 سرور اصلی: <b>{server.name}</b>",
        f"🌐 پنل: <code>{server.host}</code>",
        "",
        "اینباندها بر اساس محل واقعی خودشان جدا شده‌اند؛ اینباندهای سرور اصلی با نودهای زیرمجموعه ادغام نمی‌شوند.",
        "",
    ]
    if not groups:
        lines.append("❌ هیچ اینباندی از 3X-UI دریافت نشد.")
    else:
        for group in groups:
            enabled, total = group_counts(group)
            lines.append(f"{group['flag']} <b>{group['title']}</b> — {enabled}/{total} فعال — <code>{group['address']}</code>")

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=_inbound_selection_keyboard(server, groups),
    )


@router.callback_query(F.data.startswith(f"{PREFIX}inbounds:"), IsDev())
async def callback_topology_inbounds(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    server_id = int(callback.data.rsplit(":", 1)[1])
    server = await Server.get_by_id(session=session, id=server_id)
    if server is None:
        await callback.answer("سرور پیدا نشد.", show_alert=True)
        return
    await _render_inbounds(callback, server, config, session)
    await callback.answer()


@router.callback_query(F.data.startswith(f"{PREFIX}toggle:"), IsDev())
async def callback_topology_toggle(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    _, _, _, server_id_text, inbound_id_text = callback.data.split(":")
    server_id = int(server_id_text)
    inbound_id = int(inbound_id_text)
    server = await Server.get_by_id(session=session, id=server_id)
    if server is None:
        await callback.answer("سرور پیدا نشد.", show_alert=True)
        return

    groups = await get_server_inbound_groups(server, config)
    live_ids = {
        int(inbound["id"])
        for group in groups
        for inbound in group.get("inbounds", [])
        if inbound.get("id") is not None
    }
    if inbound_id not in live_ids:
        await callback.answer("این اینباند دیگر در 3X-UI وجود ندارد.", show_alert=True)
        return

    selected = set(server.configured_inbound_ids)
    if not selected and groups:
        first = next((item for group in groups for item in group.get("inbounds", [])), None)
        if first and first.get("id") is not None:
            selected.add(int(first["id"]))

    if inbound_id in selected:
        selected.remove(inbound_id)
        message = "اینباند از انتخاب سرویس حذف شد."
    else:
        selected.add(inbound_id)
        message = "اینباند برای ساخت سرویس انتخاب شد."

    selected_ids = sorted(selected)
    await Server.update(
        session=session,
        name=server.name,
        selected_inbound_ids=json.dumps(selected_ids),
    )
    server.selected_inbound_ids = json.dumps(selected_ids)
    await _render_inbounds(callback, server, config, session)
    await callback.answer(message)


@router.callback_query(F.data == f"{PREFIX}noop", IsDev())
async def callback_topology_noop(callback: CallbackQuery) -> None:
    await callback.answer()


def install_keyboard_overrides() -> None:
    """Replace only the two admin management keyboards after legacy handlers load."""
    from app.bot.routers.admin_tools import inbound_management_handler, server_handler

    server_handler.servers_keyboard = enhanced_servers_keyboard
    inbound_management_handler.inbound_management_keyboard = enhanced_inbound_management_keyboard
    inbound_management_handler.inbound_selection_keyboard = _inbound_selection_keyboard


install_keyboard_overrides()
