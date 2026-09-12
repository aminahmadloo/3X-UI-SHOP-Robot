from __future__ import annotations

from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.filters import IsAdmin
from app.bot.models import ServicesContainer
from app.bot.services.network_health import _load_state, collect_network_health, render_network_section
from app.bot.services.system_health import NETWORK_INTERVALS, load_health_settings, save_health_settings
from app.bot.tasks import system_health as system_health_task
from app.config import Config

router = Router(name=__name__)

NETWORK = "system_health:network"
NETWORK_HISTORY = "system_health:network_history"
NETWORK_RUN = "system_health:network_run"
NETWORK_SETTINGS = "system_health:network_settings"
NETWORK_TOGGLE = "system_health:network_toggle"
NETWORK_INTERVAL = "system_health:network_interval"


def _icon(severity: str) -> str:
    return {"healthy": "🟢", "warning": "🟡", "problem": "🟠", "critical": "🔴", "unknown": "⚪️"}.get(severity, "⚪️")


def _fmt_ts(value: int | float | None) -> str:
    if not value:
        return "-"
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return "-"


def _network_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 بررسی الآن", callback_data=NETWORK_RUN)],
        [InlineKeyboardButton(text="📈 تاریخچه شبکه", callback_data=NETWORK_HISTORY)],
        [InlineKeyboardButton(text="⚙️ تنظیمات Network Health", callback_data=NETWORK_SETTINGS)],
        [InlineKeyboardButton(text="🔙 مدیریت سلامت", callback_data="system_health:menu")],
    ])


def _settings_keyboard(settings: dict) -> InlineKeyboardMarkup:
    enabled = "🟢 فعال" if settings.get("network_monitor_enabled", True) else "🔴 غیرفعال"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🌐 مانیتور شبکه: {enabled}", callback_data=NETWORK_TOGGLE)],
        [InlineKeyboardButton(text=f"⏱ فاصله مانیتور: {settings.get('network_interval_minutes', 1)} دقیقه", callback_data=NETWORK_INTERVAL)],
        [InlineKeyboardButton(text="🔙 Network Health", callback_data=NETWORK)],
    ])


def _reschedule_network_job() -> None:
    scheduler = getattr(system_health_task, "_scheduler", None)
    if scheduler is None or not scheduler.running:
        return
    from apscheduler.triggers.interval import IntervalTrigger

    settings = load_health_settings()
    job = scheduler.get_job(system_health_task._network_job_id())
    if job is not None:
        job.reschedule(trigger=IntervalTrigger(minutes=settings.get("network_interval_minutes", 1)))


def _install_scheduler_hooks() -> None:
    if getattr(system_health_task, "_network_interval_ui_installed", False):
        return

    original_start = system_health_task.start_scheduler
    original_restart = system_health_task.restart_scheduler

    def wrapped_start(*args, **kwargs):
        result = original_start(*args, **kwargs)
        _reschedule_network_job()
        return result

    def wrapped_restart(*args, **kwargs):
        result = original_restart(*args, **kwargs)
        _reschedule_network_job()
        return result

    system_health_task.start_scheduler = wrapped_start
    system_health_task.restart_scheduler = wrapped_restart
    system_health_task._network_interval_ui_installed = True


def install_ui_hooks() -> None:
    from app.bot.routers.admin_tools import system_health_handler
    if getattr(system_health_handler, "_network_health_ui_installed", False):
        return

    original_keyboard = system_health_handler.keyboard

    def wrapped_keyboard() -> InlineKeyboardMarkup:
        markup = original_keyboard()
        button = InlineKeyboardButton(text="🌐 Network Health", callback_data=NETWORK)
        if not any(item.callback_data == NETWORK for row in markup.inline_keyboard for item in row):
            index = max(0, len(markup.inline_keyboard) - 1)
            markup.inline_keyboard.insert(index, [button])
        return markup

    system_health_handler.keyboard = wrapped_keyboard
    system_health_handler._network_health_ui_installed = True


_install_scheduler_hooks()
install_ui_hooks()


@router.callback_query(F.data == NETWORK, IsAdmin())
async def network_health(callback: CallbackQuery, services: ServicesContainer, config: Config, session) -> None:
    await callback.answer("در حال بررسی شبکه...")
    report = await collect_network_health(config, services.server_pool, session)
    state = _load_state()
    text = (
        f"🌐 <b>Network Health</b>\n\n"
        f"وضعیت آخرین نمونه: {_icon(state.get('current', 'unknown'))} <b>{state.get('current', 'unknown')}</b>\n"
        f"آخرین بررسی ثبت‌شده: <code>{_fmt_ts((state.get('last_report') or {}).get('timestamp'))}</code>\n"
        f"بررسی جاری: <code>{_fmt_ts(report.get('timestamp'))}</code>\n"
        f"تعداد نمونه‌های History: <b>{len(state.get('history', []))}</b>\n\n"
        f"{render_network_section(report)}"
    )
    for server in report.get("servers", []):
        text += f"\n\n🩺 <b>تشخیص {server.get('name', '-')}</b>\n{server.get('diagnosis', '-')}"
    await callback.message.edit_text(text, reply_markup=_network_keyboard())


@router.callback_query(F.data == NETWORK_RUN, IsAdmin())
async def network_run(callback: CallbackQuery) -> None:
    await callback.answer("بررسی شبکه آغاز شد...")
    await system_health_task.run_network_once()
    state = _load_state()
    await callback.message.edit_text(
        f"🌐 <b>نتیجه آخرین بررسی شبکه</b>\n\n"
        f"وضعیت: {_icon(state.get('current', 'unknown'))} <b>{state.get('current', 'unknown')}</b>\n"
        f"آخرین بررسی: <code>{_fmt_ts((state.get('last_report') or {}).get('timestamp'))}</code>\n"
        f"نمونه‌های History: {len(state.get('history', []))}",
        reply_markup=_network_keyboard(),
    )


@router.callback_query(F.data == NETWORK_HISTORY, IsAdmin())
async def network_history(callback: CallbackQuery) -> None:
    await callback.answer()
    state = _load_state()
    history = state.get("history") if isinstance(state.get("history"), list) else []
    history = history[-20:]
    lines = [
        "📈 <b>تاریخچه Network Health</b>",
        f"\nوضعیت فعلی: {_icon(state.get('current', 'unknown'))} {state.get('current', 'unknown')}",
        f"آخرین بررسی: <code>{_fmt_ts((state.get('last_report') or {}).get('timestamp'))}</code>",
        "",
    ]
    if not history:
        lines.append("⚪️ هنوز نمونه‌ای ثبت نشده است.")
    else:
        for sample in reversed(history):
            severity = sample.get("severity", "unknown")
            lines.append(f"{_icon(severity)} {_fmt_ts(sample.get('timestamp'))} — <b>{severity}</b>")
    await callback.message.edit_text("\n".join(lines), reply_markup=_network_keyboard())


@router.callback_query(F.data == NETWORK_SETTINGS, IsAdmin())
async def network_settings(callback: CallbackQuery) -> None:
    await callback.answer()
    settings = load_health_settings()
    await callback.message.edit_text(
        "⚙️ <b>تنظیمات Network Health</b>\n\n"
        "مانیتور شبکه مستقل از گزارش دوره‌ای سلامت سیستم اجرا می‌شود.\n"
        "تغییر فاصله، Scheduler را بدون Restart کانتینر به‌روزرسانی می‌کند.",
        reply_markup=_settings_keyboard(settings),
    )


@router.callback_query(F.data == NETWORK_TOGGLE, IsAdmin())
async def network_toggle(callback: CallbackQuery) -> None:
    settings = save_health_settings(network_monitor_enabled=not load_health_settings().get("network_monitor_enabled", True))
    _reschedule_network_job()
    await callback.answer("وضعیت مانیتور شبکه تغییر کرد")
    await callback.message.edit_reply_markup(reply_markup=_settings_keyboard(settings))


@router.callback_query(F.data == NETWORK_INTERVAL, IsAdmin())
async def network_interval_menu(callback: CallbackQuery) -> None:
    settings = load_health_settings()
    current = settings.get("network_interval_minutes", 1)
    rows = [
        [InlineKeyboardButton(text=f"{'✅ ' if current == minutes else ''}{minutes} دقیقه", callback_data=f"{NETWORK_INTERVAL}:{minutes}")]
        for minutes in NETWORK_INTERVALS
    ]
    rows.append([InlineKeyboardButton(text="🔙 تنظیمات Network Health", callback_data=NETWORK_SETTINGS)])
    await callback.answer()
    await callback.message.edit_text("⏱ <b>فاصله بررسی Network Health</b>\n\nفاصله اجرای مانیتور شبکه را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith(f"{NETWORK_INTERVAL}:"), IsAdmin())
async def set_network_interval(callback: CallbackQuery) -> None:
    minutes = int(callback.data.rsplit(":", 1)[1])
    if minutes not in NETWORK_INTERVALS:
        await callback.answer("فاصله انتخاب‌شده معتبر نیست", show_alert=True)
        return
    settings = save_health_settings(network_interval_minutes=minutes)
    _reschedule_network_job()
    await callback.answer(f"فاصله مانیتور روی {minutes} دقیقه تنظیم شد")
    await callback.message.edit_text("⚙️ <b>تنظیمات Network Health</b>", reply_markup=_settings_keyboard(settings))
