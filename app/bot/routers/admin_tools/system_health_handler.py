from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.models import ServicesContainer
from app.bot.services.system_health import HealthCollector, INTERVALS, load_health_settings, save_health_settings
from app.bot.tasks import system_health as system_health_task
from app.config import Config

router = Router(name=__name__)

MENU = "system_health:menu"
REPORT = "system_health:report"
SETTINGS = "system_health:settings"
TOGGLE = "system_health:toggle"
ERRORS = "system_health:errors"
INTERVAL = "system_health:interval"


def install_admin_menu_button() -> None:
    """Extend the existing admin menu without replacing its canonical handler."""
    from app.bot.routers.admin_tools import admin_tools_handler
    if getattr(admin_tools_handler, "_system_health_installed", False):
        return

    original = admin_tools_handler.admin_tools_keyboard

    def wrapped(is_dev: bool):
        markup = original(is_dev)
        button = InlineKeyboardButton(text="❤️ مدیریت سلامت سیستم", callback_data=MENU)
        rows = markup.inline_keyboard
        if not any(any(item.callback_data == MENU for item in row) for row in rows):
            rows.insert(-1, [button])
        return markup

    admin_tools_handler.admin_tools_keyboard = wrapped
    admin_tools_handler._system_health_installed = True


install_admin_menu_button()


def keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 گزارش کامل سلامت", callback_data=REPORT)],
        [InlineKeyboardButton(text="🌍 وضعیت سرورها", callback_data="system_health:servers")],
        [InlineKeyboardButton(text="📡 وضعیت X-UI", callback_data="system_health:xui")],
        [InlineKeyboardButton(text="🔌 وضعیت Inboundها", callback_data="system_health:inbounds")],
        [InlineKeyboardButton(text="👤 وضعیت Clientها", callback_data="system_health:clients")],
        [InlineKeyboardButton(text="🐳 وضعیت Docker", callback_data="system_health:docker")],
        [InlineKeyboardButton(text="⚙️ وضعیت Process", callback_data="system_health:processes")],
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
        [InlineKeyboardButton(text=f"🔔 Enable: {enabled}", callback_data=TOGGLE)],
        [InlineKeyboardButton(text=f"⏱ Interval: {settings['interval_minutes']} دقیقه", callback_data=INTERVAL)],
        [InlineKeyboardButton(text=f"🚨 Error only: {errors}", callback_data=ERRORS)],
        [InlineKeyboardButton(text="🔙 بازگشت", callback_data=MENU)],
    ])


def _collector(config: Config, services: ServicesContainer, bot, session: AsyncSession) -> HealthCollector:
    return HealthCollector(config=config, server_pool=services.server_pool, bot=bot, session=session)


async def _render_detail(report: dict, kind: str) -> str:
    if kind == "servers":
        lines = ["🌍 <b>وضعیت سرورها</b>"]
        for server in report["servers"]:
            lines.append(f"\n<b>{server['name']}</b> — {'🟢 سالم' if server.get('status') == 'healthy' else '🔴 مشکل'}\nHost: <code>{server.get('host','-')}</code>")
        return "\n".join(lines)
    if kind == "xui":
        return "📡 <b>وضعیت X-UI</b>\n\n" + "\n".join(f"{('🟢' if s.get('panel',{}).get('ok') else '🔴')} {s['name']}: {s.get('panel',{}).get('message') or 'API reachable'}" for s in report["servers"])
    if kind in {"inbounds", "clients"}:
        lines = [f"{'🔌' if kind == 'inbounds' else '👤'} <b>{'Inboundها' if kind == 'inbounds' else 'Clientها'}</b>"]
        for s in report["servers"]:
            if kind == "inbounds":
                lines.append(f"\n<b>{s['name']}</b>: {s.get('inbound_enabled',0)}/{s.get('inbound_total',0)} فعال")
                for i in s.get("inbounds", []):
                    lines.append(f"{'🟢' if i.get('enable') else '🔴'} {i.get('remark') or '-'} | {i.get('protocol') or '-'} | {i.get('port') or '-'}")
            else:
                c = s.get("clients", {})
                lines.append(f"\n<b>{s['name']}</b>: {c.get('enabled',0)}/{c.get('total',0)} فعال | {c.get('disabled',0)} غیرفعال | {c.get('expired',0)} منقضی")
        return "\n".join(lines)
    if kind == "docker":
        d = report["robot"]["docker"]
        return f"🐳 <b>Docker</b>\n\nBot: {'🟢' if d['bot'].get('ok') is True else '🔴' if d['bot'].get('ok') is False else '⚪️'} {d['bot'].get('state') or d['bot'].get('message','-')}\nRedis: {'🟢' if d['redis'].get('ok') is True else '🔴' if d['redis'].get('ok') is False else '⚪️'} {d['redis'].get('state') or d['redis'].get('message','-')}"
    if kind == "processes":
        p = report["robot"]["process"]
        return f"⚙️ <b>Process</b>\n\nBot process: {'🟢' if p['ok'] else '🔴'}\nPID: <code>{p.get('pid','-')}</code>"
    if kind == "webhook":
        w = report["robot"]["webhook"]
        return f"🔗 <b>Webhook</b>\n\n{'🟢' if w['ok'] else '🔴'}\nExpected: <code>{w.get('expected','-')}</code>\nActual: <code>{w.get('actual','-')}</code>\nPending: {w.get('pending_updates',0)}\nError: {w.get('last_error') or '-'}"
    if kind == "sqlite":
        s = report["robot"]["sqlite"]
        return f"🗄 <b>SQLite</b>\n\n{'🟢' if s['ok'] else '🔴'}\nPath: <code>{s.get('path','-')}</code>\nSize: {s.get('size',0):,} bytes\nIntegrity: {s.get('integrity','-')}"
    r = report["resources"]
    return f"📊 <b>CPU / RAM / Disk</b>\n\nCPU: {r['cpu']['percent']}% | Load: {r['cpu']['load1']}\nRAM: {r['ram']['percent']}%\nDisk: {r['disk']['percent']}%"


@router.callback_query(F.data == MENU, IsAdmin())
async def health_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "❤️ <b>مدیریت سلامت سیستم</b>\n\nبررسی واقعی Bot، ServerPool، X-UI، Inboundها، Clientها، Docker، Process، Webhook، SQLite و منابع سیستم.",
        reply_markup=keyboard(),
    )


@router.callback_query(F.data == REPORT, IsAdmin())
async def health_report(callback: CallbackQuery, services: ServicesContainer, config: Config, session: AsyncSession) -> None:
    await callback.answer("در حال بررسی...")
    report = await _collector(config, services, callback.bot, session).collect()
    await callback.message.edit_text(HealthCollector.render(report), reply_markup=keyboard())


@router.callback_query(F.data.startswith("system_health:"), IsAdmin())
async def health_detail(callback: CallbackQuery, services: ServicesContainer, config: Config, session: AsyncSession) -> None:
    kind = callback.data.split(":", 1)[1]
    if kind not in {"servers", "xui", "inbounds", "clients", "docker", "processes", "webhook", "sqlite", "resources"}:
        return
    await callback.answer("در حال بررسی...")
    report = await _collector(config, services, callback.bot, session).collect()
    await callback.message.edit_text(
        await _render_detail(report, kind),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 بازخوانی", callback_data=f"system_health:{kind}")],
                [InlineKeyboardButton(text="🔙 مدیریت سلامت", callback_data=MENU)],
            ]
        ),
    )


@router.callback_query(F.data == SETTINGS, IsAdmin())
async def health_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    settings = load_health_settings()
    await callback.message.edit_text(
        "🔔 <b>تنظیمات گزارش خودکار سلامت</b>\n\nEnable: فعال/غیرفعال کردن گزارش دوره‌ای\nInterval: فاصله اجرای بررسی\nError only: فقط تغییر وضعیت به خطا یا بازگشت را گزارش می‌کند و از اسپم جلوگیری می‌شود.",
        reply_markup=settings_keyboard(settings),
    )


@router.callback_query(F.data == TOGGLE, IsAdmin())
async def toggle_enabled(callback: CallbackQuery) -> None:
    settings = save_health_settings(enabled=not load_health_settings()["enabled"])
    await callback.answer("تنظیم Enable تغییر کرد")
    await callback.message.edit_reply_markup(reply_markup=settings_keyboard(settings))


@router.callback_query(F.data == ERRORS, IsAdmin())
async def toggle_errors(callback: CallbackQuery) -> None:
    settings = save_health_settings(errors_only=not load_health_settings()["errors_only"])
    await callback.answer("تنظیم Error only تغییر کرد")
    await callback.message.edit_reply_markup(reply_markup=settings_keyboard(settings))


@router.callback_query(F.data == INTERVAL, IsAdmin())
async def interval_menu(callback: CallbackQuery) -> None:
    settings = load_health_settings()
    rows = [[InlineKeyboardButton(text=f"{'✅ ' if settings['interval_minutes']==minutes else ''}{minutes} دقیقه", callback_data=f"{INTERVAL}:{minutes}")] for minutes in INTERVALS]
    rows.append([InlineKeyboardButton(text="🔙 تنظیمات گزارش", callback_data=SETTINGS)])
    await callback.answer()
    await callback.message.edit_text("⏱ <b>Interval گزارش خودکار</b>\n\nفاصله اجرای بررسی سلامت را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith(f"{INTERVAL}:"), IsAdmin())
async def set_interval(callback: CallbackQuery) -> None:
    minutes = int(callback.data.rsplit(":", 1)[1])
    settings = save_health_settings(interval_minutes=minutes)
    system_health_task.restart_scheduler()
    await callback.answer(f"Interval روی {minutes} دقیقه تنظیم شد")
    await callback.message.edit_text("🔔 <b>تنظیمات گزارش خودکار سلامت</b>", reply_markup=settings_keyboard(settings))
