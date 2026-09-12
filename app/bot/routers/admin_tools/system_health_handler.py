from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.models import ServicesContainer
from app.bot.services.system_health import INTERVALS, load_health_settings, save_health_settings
from app.bot.services.system_health_comprehensive import ComprehensiveHealthCollector, create_sqlite_backup, latest_sqlite_backup
from app.bot.tasks import system_health as system_health_task
from app.config import Config

router = Router(name=__name__)

MENU = "system_health:menu"
REPORT = "system_health:report"
SETTINGS = "system_health:settings"
TOGGLE = "system_health:toggle"
ERRORS = "system_health:errors"
INTERVAL = "system_health:interval"
BACKUP = "system_health:backup"
SEND_BACKUP = "system_health:send_backup"
DETAIL_KINDS = {"servers", "nodes", "xui", "inbounds", "clients", "docker", "processes", "webhook", "sqlite", "resources"}


def install_admin_menu_button() -> None:
    from app.bot.routers.admin_tools import admin_tools_handler
    if getattr(admin_tools_handler, "_system_health_installed", False):
        return
    original = admin_tools_handler.admin_tools_keyboard

    def wrapped(is_dev: bool):
        markup = original(is_dev)
        button = InlineKeyboardButton(text="❤️ مدیریت سلامت سیستم", callback_data=MENU)
        if not any(any(item.callback_data == MENU for item in row) for row in markup.inline_keyboard):
            markup.inline_keyboard.insert(-1, [button])
        return markup

    admin_tools_handler.admin_tools_keyboard = wrapped
    admin_tools_handler._system_health_installed = True


install_admin_menu_button()


def keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 گزارش کامل سلامت", callback_data=REPORT)],
        [InlineKeyboardButton(text="🌍 وضعیت سرورها", callback_data="system_health:servers")],
        [InlineKeyboardButton(text="🧩 وضعیت Nodeها", callback_data="system_health:nodes")],
        [InlineKeyboardButton(text="📡 وضعیت X-UI", callback_data="system_health:xui")],
        [InlineKeyboardButton(text="🔌 وضعیت Inboundها", callback_data="system_health:inbounds")],
        [InlineKeyboardButton(text="👤 وضعیت Clientها", callback_data="system_health:clients")],
        [InlineKeyboardButton(text="🐳 وضعیت Docker", callback_data="system_health:docker")],
        [InlineKeyboardButton(text="⚙️ وضعیت فرآیندها", callback_data="system_health:processes")],
        [InlineKeyboardButton(text="🔗 وضعیت Webhook", callback_data="system_health:webhook")],
        [InlineKeyboardButton(text="🗄 وضعیت SQLite", callback_data="system_health:sqlite")],
        [InlineKeyboardButton(text="📊 CPU / RAM / Disk", callback_data="system_health:resources")],
        [InlineKeyboardButton(text="🔔 تنظیمات گزارش خودکار", callback_data=SETTINGS)],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data="admin_tools")],
    ])


def settings_keyboard(settings: dict) -> InlineKeyboardMarkup:
    enabled = "🟢 فعال" if settings["enabled"] else "🔴 غیرفعال"
    errors = "🟢 فقط خطا" if settings["errors_only"] else "🔵 همه گزارش‌ها"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔔 گزارش خودکار: {enabled}", callback_data=TOGGLE)],
        [InlineKeyboardButton(text=f"⏱ فاصله بررسی: {settings['interval_minutes']} دقیقه", callback_data=INTERVAL)],
        [InlineKeyboardButton(text=f"🚨 حالت فقط خطا: {errors}", callback_data=ERRORS)],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data=MENU)],
    ])


def _collector(config: Config, services: ServicesContainer, bot, session: AsyncSession) -> ComprehensiveHealthCollector:
    return ComprehensiveHealthCollector(config=config, server_pool=services.server_pool, bot=bot, session=session)


async def _render_detail(report: dict, kind: str) -> str:
    if kind == "servers":
        lines = ["🌍 <b>وضعیت سرورها</b>"]
        for server in report.get("servers", []):
            panel = server.get("panel", {})
            xray = panel.get("xray") or {}
            lines.append(
                f"\n<b>{server['name']}</b> — {'🟢 سالم' if server.get('status') == 'healthy' else '🔴 مشکل'}"
                f"\nآدرس: <code>{server.get('host','-')}</code>"
                f"\nX-UI: {'🟢' if panel.get('ok') else '🔴'} | Xray: {'🟢' if str(xray.get('state','')).lower() == 'running' else '🔴'}"
                f"\nCPU: {panel.get('cpu','-')}% | RAM: {panel.get('memory_percent','-')}% | Disk: {panel.get('disk_percent','-')}%"
            )
        return "\n".join(lines)

    if kind == "nodes":
        lines = ["🧩 <b>وضعیت 3X-UI Nodeها</b>"]
        if not report.get("nodes"):
            return "\n".join(lines + ["\n⚪️ هیچ Node مدیریتشده‌ای پیدا نشد."])
        for node in report["nodes"]:
            state = "⚪️ غیرفعال" if not node.get("enabled", True) else "🟢 سالم" if node.get("ok") else "🔴 مشکل"
            lines.append(
                f"\n<b>{node.get('name','-')}</b> — {state}"
                f"\nسرور مادر: {node.get('parent_server','-')}"
                f"\nآدرس: <code>{node.get('address','-')}</code>:{node.get('port','-')}"
                f"\nوضعیت: {node.get('status','-')} | Ping: {node.get('latency_ms','-')} ms"
                f"\nCPU: {node.get('cpu_percent','-')}% | RAM: {node.get('memory_percent','-')}%"
                f"\nXray: {node.get('xray_state','-')} {('— ' + node.get('xray_error')) if node.get('xray_error') else ''}"
                f"\nInbound: {node.get('inbound_count',0)} | Client: {node.get('client_count',0)} | Online: {node.get('online_count',0)}"
            )
        return "\n".join(lines)

    if kind == "xui":
        lines = ["📡 <b>وضعیت X-UI</b>"]
        for server in report.get("servers", []):
            panel = server.get("panel", {})
            lines.append(f"\n<b>{server['name']}</b> — {'🟢' if panel.get('ok') else '🔴'} {panel.get('message') or 'API قابل دسترسی است'}")
        for node in report.get("nodes", []):
            lines.append(f"🧩 <b>{node.get('name','-')}</b> — {'🟢' if node.get('ok') else '🔴'} | {node.get('status','-')} | Ping {node.get('latency_ms','-')} ms")
        return "\n".join(lines)

    if kind == "inbounds":
        lines = ["🔌 <b>Inboundها</b>"]
        for server in report.get("servers", []):
            groups = server.get("inbound_groups") or []
            for group in groups:
                lines.append(f"\n<b>{server['name']} / {group['name']}</b>: {group['enabled']}/{group['total']} فعال")
                for inbound in group["inbounds"]:
                    icon = "🟢" if inbound.get("enable") else "🔴"
                    lines.append(f"{icon} {inbound.get('remark','-')} | {inbound.get('protocol','-')} | {inbound.get('port','-')}")
        return "\n".join(lines)

    if kind == "clients":
        lines = ["👤 <b>Clientها</b>"]
        for server in report.get("servers", []):
            for group in server.get("client_groups") or []:
                c = group["stats"]
                lines.append(
                    f"\n<b>{server['name']} / {group['name']}</b>\n"
                    f"فعال: {c.get('enabled',0)} | کل: {c.get('total',0)} | غیرفعال: {c.get('disabled',0)} | منقضی: {c.get('expired',0)} | Online: {group.get('online',0)}"
                )
        return "\n".join(lines)

    if kind == "docker":
        d = report["robot"]["docker"]
        def dicon(value):
            return "🟢" if value is True else "🔴" if value is False else "⚪️"
        return (
            "🐳 <b>وضعیت Docker</b>\n\n"
            f"Bot runtime — Bot: {dicon(d['bot'].get('ok'))} | Redis: {dicon(d['redis'].get('ok'))}\n\n"
            "وضعیت Docker Hostهای Server/Node از API رسمی 3X-UI ارائه نمی‌شود. برای نمایش Docker واقعی هر Host باید Agent یا دسترسی امن به Docker daemon اضافه شود؛ از mount کردن Docker socket داخل Bot خودداری شده است."
        )

    if kind == "processes":
        p = report["robot"]["process"]
        lines = ["⚙️ <b>وضعیت فرآیندها</b>", f"\nBot: {'🟢' if p.get('ok') else '🔴'} | PID: <code>{p.get('pid','-')}</code>"]
        for server in report.get("servers", []):
            xray = (server.get("panel") or {}).get("xray") or {}
            lines.append(f"{server['name']} — Xray: {'🟢' if str(xray.get('state','')).lower() == 'running' else '🔴'}")
        for node in report.get("nodes", []):
            lines.append(f"{node.get('name','-')} — Xray: {'🟢' if str(node.get('xray_state','')).lower() == 'running' else '🔴'}")
        return "\n".join(lines)

    if kind == "webhook":
        w = report["robot"]["webhook"]
        return (
            "🔗 <b>وضعیت Webhook</b>\n\n"
            f"{'🟢' if w['ok'] else '🔴'}\n"
            f"آدرس مورد انتظار: <code>{w.get('expected','-')}</code>\n"
            f"آدرس فعلی: <code>{w.get('actual','-')}</code>\n"
            f"پیام‌های در انتظار: {w.get('pending_updates',0)}\n"
            f"آخرین خطا: {w.get('last_error') or 'ندارد'}"
        )

    if kind == "sqlite":
        s = report["robot"]["sqlite"]
        return (
            "🗄 <b>وضعیت SQLite</b>\n\n"
            f"{'🟢' if s['ok'] else '🔴'}\n"
            f"مسیر: <code>{s.get('path','-')}</code>\n"
            f"حجم: {s.get('size',0):,} bytes\n"
            f"Integrity: {s.get('integrity','-')}"
        )

    lines = ["📊 <b>منابع Server / Node</b>"]
    for item in report.get("resources_by_server", []):
        lines.append(
            f"\n<b>{item.get('name','-')}</b> — <code>{item.get('address','-')}</code>\n"
            f"CPU: {item.get('cpu','-')}% | RAM: {item.get('ram','-')}% | Disk: {item.get('disk','-') if item.get('disk') is not None else 'در API Node موجود نیست'}"
        )
    r = report.get("resources", {})
    lines.append(f"\n<b>Bot runtime</b> — CPU: {r.get('cpu',{}).get('percent','-')}% | RAM: {r.get('ram',{}).get('percent','-')}% | Disk: {r.get('disk',{}).get('percent','-')}%")
    return "\n".join(lines)


@router.callback_query(F.data == MENU, IsAdmin())
async def health_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "❤️ <b>مدیریت سلامت سیستم</b>\n\nبررسی واقعی Bot، همه Serverهای ثبت‌شده، همه 3X-UI Nodeهای مدیریت‌شده، X-UI، Inboundها، Clientها، Docker، فرآیندها، Webhook، SQLite و منابع سیستم.",
        reply_markup=keyboard(),
    )


@router.callback_query(F.data == REPORT, IsAdmin())
async def health_report(callback: CallbackQuery, services: ServicesContainer, config: Config, session: AsyncSession) -> None:
    await callback.answer("در حال بررسی همه Serverها و Nodeها...")
    report = await _collector(config, services, callback.bot, session).collect()
    await callback.message.edit_text(ComprehensiveHealthCollector.render(report), reply_markup=keyboard())


@router.callback_query(F.data.in_({f"system_health:{kind}" for kind in DETAIL_KINDS}), IsAdmin())
async def health_detail(callback: CallbackQuery, services: ServicesContainer, config: Config, session: AsyncSession) -> None:
    kind = callback.data.split(":", 1)[1]
    await callback.answer("در حال بررسی...")
    report = await _collector(config, services, callback.bot, session).collect()
    await callback.message.edit_text(
        await _render_detail(report, kind),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔄 بازخوانی", callback_data=f"system_health:{kind}")],
            [InlineKeyboardButton(text="🔙 مدیریت سلامت", callback_data=MENU)],
        ]),
    )


@router.callback_query(F.data == BACKUP, IsAdmin())
async def sqlite_backup(callback: CallbackQuery) -> None:
    await callback.answer("در حال تهیه Backup...")
    path, error = await create_sqlite_backup()
    if error or path is None:
        await callback.message.answer(f"❌ تهیه Backup SQLite ناموفق بود:\n<code>{error or 'نامشخص'}</code>")
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


@router.callback_query(F.data == SETTINGS, IsAdmin())
async def health_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text("🔔 <b>تنظیمات گزارش خودکار سلامت</b>\n\nگزارش دوره‌ای را فعال یا غیرفعال کنید و فاصله بررسی را تعیین کنید.", reply_markup=settings_keyboard(load_health_settings()))


@router.callback_query(F.data == TOGGLE, IsAdmin())
async def toggle_enabled(callback: CallbackQuery) -> None:
    settings = save_health_settings(enabled=not load_health_settings()["enabled"])
    system_health_task.restart_scheduler()
    await callback.answer("تنظیم گزارش خودکار تغییر کرد")
    await callback.message.edit_reply_markup(reply_markup=settings_keyboard(settings))


@router.callback_query(F.data == ERRORS, IsAdmin())
async def toggle_errors(callback: CallbackQuery) -> None:
    settings = save_health_settings(errors_only=not load_health_settings()["errors_only"])
    await callback.answer("حالت گزارش خطا تغییر کرد")
    await callback.message.edit_reply_markup(reply_markup=settings_keyboard(settings))


@router.callback_query(F.data == INTERVAL, IsAdmin())
async def interval_menu(callback: CallbackQuery) -> None:
    settings = load_health_settings()
    rows = [[InlineKeyboardButton(text=f"{'✅ ' if settings['interval_minutes']==minutes else ''}{minutes} دقیقه", callback_data=f"{INTERVAL}:{minutes}")] for minutes in INTERVALS]
    rows.append([InlineKeyboardButton(text="🔙 تنظیمات گزارش", callback_data=SETTINGS)])
    await callback.answer()
    await callback.message.edit_text("⏱ <b>فاصله بررسی سلامت</b>\n\nفاصله اجرای بررسی سلامت را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith(f"{INTERVAL}:"), IsAdmin())
async def set_interval(callback: CallbackQuery) -> None:
    minutes = int(callback.data.rsplit(":", 1)[1])
    settings = save_health_settings(interval_minutes=minutes)
    system_health_task.restart_scheduler()
    await callback.answer(f"فاصله روی {minutes} دقیقه تنظیم شد")
    await callback.message.edit_text("🔔 <b>تنظیمات گزارش خودکار سلامت</b>", reply_markup=settings_keyboard(settings))
