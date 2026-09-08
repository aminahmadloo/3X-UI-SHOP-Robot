import html
import os
import re
from pathlib import Path
from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.payment_gateways import GatewayFactory
from app.bot.utils.navigation import NavAdminTools
from app.config import Config
from app.db.models import PaymentGatewaySettings, PaymentMethodSettings

router = Router(name=__name__)

ENV_FILE = Path("/app/.env")
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ENV_LINE_RE = re.compile(r"^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*=\s*)(.*?)(\r?\n)?$")


class PaymentGatewaySettingsState(StatesGroup):
    waiting_zarinpal_payment_base_url = State()
    waiting_aban_token = State()
    waiting_aban_webhook_secret = State()


def _read_env_lines() -> list[str]:
    if not ENV_FILE.exists():
        return []
    return ENV_FILE.read_text(encoding="utf-8").splitlines(keepends=True)


def _read_env_value(name: str) -> str:
    for line in _read_env_lines():
        match = ENV_LINE_RE.match(line)
        if not match or match.group(2) != name:
            continue
        value = match.group(4).strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        return value
    return os.getenv(name, "").strip()


def _write_env_value(name: str, value: str) -> None:
    if not ENV_KEY_RE.fullmatch(name):
        raise ValueError("نام متغیر نامعتبر است.")
    if "\n" in value or "\r" in value:
        raise ValueError("مقدار نمی‌تواند شامل خط جدید باشد.")
    if not ENV_FILE.exists():
        raise FileNotFoundError(str(ENV_FILE))

    output: list[str] = []
    found = False
    for line in _read_env_lines():
        match = ENV_LINE_RE.match(line)
        if not match:
            output.append(line)
            continue
        indent, key, separator, _, newline = match.groups()
        if key == name:
            output.append(f"{indent}{key}{separator}{value}{newline or chr(10)}")
            found = True
        else:
            output.append(line)

    if not found:
        output.append(f"{name}={value}\n")

    ENV_FILE.write_text("".join(output), encoding="utf-8")


def menu_markup(settings: PaymentGatewaySettings | None) -> InlineKeyboardMarkup:
    configured = bool(settings and settings.zarinpal_payment_base_url_configured)
    url = (settings.zarinpal_payment_base_url if settings else "").strip()
    rows = [
        [InlineKeyboardButton(text="✏️ ویرایش مسیر پرداخت زرین‌پال", callback_data="paymentgateway:edit_zarinpal_url")],
    ]
    if configured:
        rows.append([InlineKeyboardButton(text="🔴 استفاده مستقیم از زرین‌پال", callback_data="paymentgateway:disable_custom_url")])
        if url:
            rows.append([InlineKeyboardButton(text="♻️ بازگشت به مقدار .env", callback_data="paymentgateway:reset_env")])
    else:
        rows.append([InlineKeyboardButton(text="🟢 استفاده از مسیر .env", callback_data="paymentgateway:use_env")])

    rows.append([InlineKeyboardButton(
        text="💳 تنظیمات کارت به کارت آبان گیت",
        callback_data="paymentgateway:aban",
    )])
    rows.append([InlineKeyboardButton(text="👁️ مدیریت نمایش روش‌های پرداخت", callback_data="paymentgateway:methods")])
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_methods_markup(methods: list[PaymentMethodSettings]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for method in methods:
        status = "🟢 نمایش" if method.enabled else "🔴 مخفی"
        action = "مخفی کردن" if method.enabled else "نمایش دادن"
        rows.append([
            InlineKeyboardButton(
                text=f"{status} | {method.display_name}",
                callback_data=f"paymentmethod:toggle:{method.id}",
            )
        ])
        rows.append([
            InlineKeyboardButton(
                text=f"⚙️ {action}",
                callback_data=f"paymentmethod:toggle:{method.id}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🔄 تازه‌سازی", callback_data="paymentgateway:methods")])
    rows.append([InlineKeyboardButton(text="🔙 تنظیمات درگاه‌ها", callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS)])
    rows.append([InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavAdminTools.MAIN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_payment_methods(callback: CallbackQuery, session: AsyncSession, gateway_factory: GatewayFactory) -> None:
    methods = await PaymentMethodSettings.get_manageable(session, gateway_factory.get_gateways())
    lines = [
        "👁️ <b>مدیریت نمایش روش‌های پرداخت</b>",
        "",
        "از این بخش تعیین می‌کنید کدام روش‌ها در مرحله انتخاب پرداخت مشتری دیده شوند.",
        "",
    ]
    for index, method in enumerate(methods, start=1):
        status = "🟢 نمایش داده می‌شود" if method.enabled else "🔴 مخفی است"
        lines.append(f"{index}️⃣ {method.display_name} — <b>{status}</b>")

    lines.extend([
        "",
        "💡 درگاه‌های ثبت‌شده جدید به‌صورت خودکار به این فهرست اضافه می‌شوند.",
        "💡 درگاهِ تنظیم‌نشده برای مشتری نمایش داده نمی‌شود، حتی اگر وضعیت نمایش آن فعال باشد.",
    ])
    await callback.message.edit_text("\n".join(lines), reply_markup=payment_methods_markup(methods))


async def show_menu(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await PaymentGatewaySettings.get(session)
    env_url = config.zarinpal.PAYMENT_BASE_URL or "تنظیم نشده"
    if settings and settings.zarinpal_payment_base_url_configured:
        custom_url = settings.zarinpal_payment_base_url.strip()
        if custom_url:
            payment_method, effective_url, custom_status = "🟢 مسیر اختصاصی", custom_url, "🟢 فعال"
        else:
            payment_method, effective_url, custom_status = "🔵 مستقیم زرین‌پال", config.zarinpal.DIRECT_PAYMENT_BASE_URL, "⚪ غیرفعال"
    elif config.zarinpal.PAYMENT_BASE_URL:
        payment_method, effective_url, custom_status = "🟢 مسیر .env", config.zarinpal.PAYMENT_BASE_URL, "⚪ استفاده نمی‌شود"
    else:
        payment_method, effective_url, custom_status = "🔵 مستقیم زرین‌پال", config.zarinpal.DIRECT_PAYMENT_BASE_URL, "⚪ استفاده نمی‌شود"

    token = _read_env_value("ABAN_GATEWAY_TOKEN")
    secret = _read_env_value("ABAN_GATEWAY_WEBHOOK_SECRET")
    aban_status = "🟢 آماده اتصال" if token and secret else "🔴 نیازمند تنظیمات"

    text = (
        "💳 <b>تنظیمات درگاه‌های پرداخت</b>\n\n"
        "🏦 <b>زرین‌پال</b>\n"
        "وضعیت درگاه: <b>🟢 فعال</b>\n"
        f"روش نمایش پرداخت: <b>{payment_method}</b>\n"
        f"مسیر پرداخت مؤثر: <code>{html.escape(effective_url)}</code>\n"
        f"مسیر .env: <code>{html.escape(env_url)}</code>\n"
        f"وضعیت مسیر سفارشی: <b>{custom_status}</b>\n\n"
        "💳 <b>پرداخت خودکار کارت به کارت</b>\n"
        f"وضعیت اتصال آبان گیت: <b>{aban_status}</b>\n"
        "تنظیمات آبان گیت از مسیر مستقل مدیریت می‌شود."
    )
    await callback.message.edit_text(text, reply_markup=menu_markup(settings))


@router.callback_query(F.data == NavAdminTools.PAYMENT_GATEWAY_SETTINGS, IsAdmin())
async def payment_gateway_settings_menu(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    await callback.answer()
    await show_menu(callback, session, config)


@router.callback_query(F.data == "paymentgateway:aban", IsAdmin())
async def aban_settings_menu(callback: CallbackQuery, config: Config) -> None:
    token = _read_env_value("ABAN_GATEWAY_TOKEN")
    secret = _read_env_value("ABAN_GATEWAY_WEBHOOK_SECRET")
    token_status = "🟢 تنظیم شده" if token else "🔴 تنظیم نشده"
    secret_status = "🟢 تنظیم شده" if secret else "🔴 تنظیم نشده"
    configured = bool(token and secret)
    api_url = _read_env_value("ABAN_GATEWAY_API_BASE_URL") or "https://abangateway.ir/api/v1"

    text = (
        "💳 <b>تنظیمات کارت به کارت آبان گیت</b>\n\n"
        f"🔑 توکن: <b>{token_status}</b>\n"
        f"🔐 Webhook Secret: <b>{secret_status}</b>\n"
        f"📡 وضعیت سرویس: <b>{'🟢 آماده استفاده' if configured else '🔴 ناقص'}</b>\n\n"
        "⏱️ مهلت فاکتور: <b>طبق تنظیمات حساب AbanGateway</b>\n"
        f"🌐 API: <code>{html.escape(api_url)}</code>\n"
        f"🔗 Webhook: <code>{html.escape(config.bot.DOMAIN.rstrip('/') + '/webhooks/aban-gateway')}</code>\n\n"
        "برای فعال‌سازی، Token و Webhook Secret را از همین صفحه تنظیم کنید.\n"
        "مقدارهای حساس هرگز در این صفحه نمایش داده نمی‌شوند."
    )

    await callback.answer()
    await callback.message.edit_text(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔑 تنظیم / تغییر Token", callback_data="paymentgateway:aban_token")],
        [InlineKeyboardButton(text="🔐 تنظیم / تغییر Webhook Secret", callback_data="paymentgateway:aban_secret")],
        [InlineKeyboardButton(text="⚙️ مدیریت سایر متغیرهای .env", callback_data=NavAdminTools.ENV_SETTINGS)],
        [InlineKeyboardButton(text="🔄 تازه‌سازی وضعیت", callback_data="paymentgateway:aban")],
        [InlineKeyboardButton(text="🔙 تنظیمات درگاه‌ها", callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS)],
    ]))


@router.callback_query(F.data == "paymentgateway:aban_token", IsAdmin())
async def aban_token_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(PaymentGatewaySettingsState.waiting_aban_token)
    await callback.answer()
    await callback.message.edit_text(
        "🔑 <b>تنظیم Token آبان گیت‌وی</b>\n\n"
        "Token جدید را در یک پیام ارسال کنید.\n\n"
        "فرمت معتبر باید با <code>live_</code> یا <code>test_</code> شروع شود.\n"
        "مقدار پس از ذخیره هرگز در پنل نمایش داده نمی‌شود.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 انصراف", callback_data="paymentgateway:aban")],
        ]),
    )


@router.message(PaymentGatewaySettingsState.waiting_aban_token, IsAdmin())
async def aban_token_save(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value.startswith(("live_", "test_")) or len(value) <= 5:
        await message.answer("❌ Token معتبر نیست. باید با <code>live_</code> یا <code>test_</code> شروع شود.")
        return
    try:
        _write_env_value("ABAN_GATEWAY_TOKEN", value)
    except Exception as exc:
        await state.clear()
        await message.answer(f"❌ ذخیره Token انجام نشد.\n<code>{html.escape(str(exc))}</code>")
        return
    await state.clear()
    await message.answer(
        "✅ <b>Token با موفقیت ذخیره شد.</b>\n\n"
        "🔐 مقدار Token در پنل نمایش داده نمی‌شود.\n"
        "⚠️ برای اعمال آن در محیط اجرای Bot، کانتینر باید دوباره ایجاد/راه‌اندازی شود.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 تنظیمات آبان گیت", callback_data="paymentgateway:aban")],
            [InlineKeyboardButton(text="🔙 تنظیمات درگاه‌ها", callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS)],
        ]),
    )


@router.callback_query(F.data == "paymentgateway:aban_secret", IsAdmin())
async def aban_secret_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(PaymentGatewaySettingsState.waiting_aban_webhook_secret)
    await callback.answer()
    await callback.message.edit_text(
        "🔐 <b>تنظیم Webhook Secret آبان گیت‌وی</b>\n\n"
        "Webhook Secret جدید را در یک پیام ارسال کنید.\n\n"
        "مقدار پس از ذخیره هرگز در پنل نمایش داده نمی‌شود.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 انصراف", callback_data="paymentgateway:aban")],
        ]),
    )


@router.message(PaymentGatewaySettingsState.waiting_aban_webhook_secret, IsAdmin())
async def aban_secret_save(message: Message, state: FSMContext) -> None:
    value = (message.text or "").strip()
    if not value:
        await message.answer("❌ Webhook Secret نمی‌تواند خالی باشد.")
        return
    try:
        _write_env_value("ABAN_GATEWAY_WEBHOOK_SECRET", value)
    except Exception as exc:
        await state.clear()
        await message.answer(f"❌ ذخیره Webhook Secret انجام نشد.\n<code>{html.escape(str(exc))}</code>")
        return
    await state.clear()
    await message.answer(
        "✅ <b>Webhook Secret با موفقیت ذخیره شد.</b>\n\n"
        "🔐 مقدار Secret در پنل نمایش داده نمی‌شود.\n"
        "⚠️ برای اعمال آن در محیط اجرای Bot، کانتینر باید دوباره ایجاد/راه‌اندازی شود.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 تنظیمات آبان گیت", callback_data="paymentgateway:aban")],
            [InlineKeyboardButton(text="🔙 تنظیمات درگاه‌ها", callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS)],
        ]),
    )


@router.callback_query(F.data == "paymentgateway:methods", IsAdmin())
async def payment_methods_menu(callback: CallbackQuery, session: AsyncSession, gateway_factory: GatewayFactory) -> None:
    await callback.answer()
    await show_payment_methods(callback, session, gateway_factory)


@router.callback_query(F.data.regexp(r"^paymentmethod:toggle:\d+$"), IsAdmin())
async def toggle_payment_method(callback: CallbackQuery, session: AsyncSession, gateway_factory: GatewayFactory) -> None:
    method_id = int(callback.data.rsplit(":", 1)[1])
    methods = await PaymentMethodSettings.get_manageable(session, gateway_factory.get_gateways())
    method = next((item for item in methods if item.id == method_id), None)
    if method is None:
        await callback.answer("❌ روش پرداخت پیدا نشد.", show_alert=True)
        return
    if method.enabled:
        if sum(1 for item in methods if item.enabled) <= 1:
            await callback.answer("❌ حداقل یک روش پرداخت باید فعال باشد.", show_alert=True)
            return
        method.enabled = False
        message = f"{method.display_name} برای مشتری مخفی شد."
    else:
        method.enabled = True
        message = f"{method.display_name} برای مشتری نمایش داده شد."
    await session.commit()
    await callback.answer(message, show_alert=True)
    await show_payment_methods(callback, session, gateway_factory)


@router.callback_query(F.data == "paymentgateway:edit_zarinpal_url", IsAdmin())
async def edit_zarinpal_url_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(PaymentGatewaySettingsState.waiting_zarinpal_payment_base_url)
    await callback.answer()
    await callback.message.edit_text(
        "✏️ <b>ویرایش مسیر پرداخت زرین‌پال</b>\n\n"
        "URL جدید را ارسال کنید.\nمثال: <code>https://example.com/pay</code>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 انصراف", callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS)],
        ]),
    )


@router.message(PaymentGatewaySettingsState.waiting_zarinpal_payment_base_url, IsAdmin())
async def edit_zarinpal_url_save(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = (message.text or "").strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        await message.answer("❌ URL معتبر نیست.")
        return
    settings = await PaymentGatewaySettings.get(session)
    if settings is None:
        settings = PaymentGatewaySettings(zarinpal_payment_base_url=value, zarinpal_payment_base_url_configured=True)
        session.add(settings)
    else:
        settings.zarinpal_payment_base_url = value
        settings.zarinpal_payment_base_url_configured = True
    await session.commit()
    await state.clear()
    await message.answer("✅ مسیر پرداخت زرین‌پال ذخیره شد.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 تنظیمات درگاه‌ها", callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS)],
    ]))


@router.callback_query(F.data == "paymentgateway:disable_custom_url", IsAdmin())
async def disable_custom_url(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await PaymentGatewaySettings.get(session)
    if settings:
        settings.zarinpal_payment_base_url = ""
        settings.zarinpal_payment_base_url_configured = True
        await session.commit()
    await callback.answer("🔴 مسیر اختصاصی غیرفعال شد.")
    await show_menu(callback, session, config)


@router.callback_query(F.data == "paymentgateway:reset_env", IsAdmin())
async def reset_to_env(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await PaymentGatewaySettings.get(session)
    if settings:
        settings.zarinpal_payment_base_url = ""
        settings.zarinpal_payment_base_url_configured = False
        await session.commit()
    await callback.answer("♻️ مقدار اختصاصی حذف و مسیر .env فعال شد.")
    await show_menu(callback, session, config)


@router.callback_query(F.data == "paymentgateway:use_env", IsAdmin())
async def use_env(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await PaymentGatewaySettings.get(session)
    if settings:
        settings.zarinpal_payment_base_url_configured = False
        settings.zarinpal_payment_base_url = ""
        await session.commit()
    await callback.answer("🟢 مسیر .env فعال شد.")
    await show_menu(callback, session, config)
