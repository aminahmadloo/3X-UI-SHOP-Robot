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


class PaymentGatewaySettingsState(StatesGroup):
    waiting_zarinpal_payment_base_url = State()
    waiting_nahanramz_api_key = State()
    waiting_nahanramz_webhook_secret = State()


def menu_markup(settings: PaymentGatewaySettings | None) -> InlineKeyboardMarkup:
    configured = bool(settings and settings.zarinpal_payment_base_url_configured)
    url = (settings.zarinpal_payment_base_url if settings else "").strip()
    rows = [
        [InlineKeyboardButton(text="✏️ ویرایش مسیر پرداخت زرین‌پال", callback_data="paymentgateway:edit_zarinpal_url")],
        [InlineKeyboardButton(text="🪙 تنظیمات نهان رمز", callback_data="paymentgateway:nahanramz")],
    ]
    if configured:
        rows.append([InlineKeyboardButton(text="🔴 استفاده مستقیم از زرین‌پال", callback_data="paymentgateway:disable_custom_url")])
        if url:
            rows.append([InlineKeyboardButton(text="♻️ بازگشت به مقدار .env", callback_data="paymentgateway:reset_env")])
    else:
        rows.append([InlineKeyboardButton(text="🟢 استفاده از مسیر .env", callback_data="paymentgateway:use_env")])
    rows.append([InlineKeyboardButton(text="👁️ مدیریت نمایش روش‌های پرداخت", callback_data="paymentgateway:methods")])
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def nahanramz_markup(configured: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🔑 تنظیم API Key", callback_data="paymentgateway:nahanramz_api_key")],
        [InlineKeyboardButton(text="🔐 تنظیم Webhook Secret", callback_data="paymentgateway:nahanramz_webhook_secret")],
    ]
    if configured:
        rows.append([InlineKeyboardButton(text="🧪 تست اتصال API", callback_data="paymentgateway:nahanramz_test")])
        rows.append([InlineKeyboardButton(text="🗑️ پاک کردن اطلاعات اتصال", callback_data="paymentgateway:nahanramz_clear")])
    rows.append([InlineKeyboardButton(text="🔙 تنظیمات درگاه‌ها", callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_methods_markup(methods: list[PaymentMethodSettings]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for method in methods:
        action = "🔴 مخفی کردن" if method.enabled else "🟢 نمایش دادن"
        rows.append([InlineKeyboardButton(text=f"{action} | {method.display_name}", callback_data=f"paymentmethod:toggle:{method.id}")])
    rows.append([InlineKeyboardButton(text="🔙 تنظیمات درگاه‌ها", callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS)])
    rows.append([InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavAdminTools.MAIN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_payment_methods(callback: CallbackQuery, session: AsyncSession, gateway_factory: GatewayFactory) -> None:
    methods = await PaymentMethodSettings.get_manageable(session, gateway_factory.get_gateways())
    lines = [
        "👁️ <b>نمایش روش‌های پرداخت برای مشتری</b>",
        "",
        "روش‌های فعال در این بخش در مرحله «انتخاب روش پرداخت» مشتری نمایش داده می‌شوند.",
        "",
    ]
    for method in methods:
        status = "🟢 نمایش داده می‌شود" if method.enabled else "🔴 مخفی است"
        lines.append(f"{method.display_name}: <b>{status}</b>")
    lines.extend([
        "",
        "ترتیب نمایش فعلی بر اساس اولویت ذخیره‌شده است؛ درگاه‌های جدید نیز خودکار قابل مدیریت می‌شوند.",
    ])
    await callback.message.edit_text("\n".join(lines), reply_markup=payment_methods_markup(methods))


async def show_menu(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await PaymentGatewaySettings.get(session)
    env_url = config.zarinpal.PAYMENT_BASE_URL or "تنظیم نشده"
    if settings and settings.zarinpal_payment_base_url_configured:
        custom_url = settings.zarinpal_payment_base_url.strip()
        if custom_url:
            payment_method = "🟢 مسیر اختصاصی"
            effective_url = custom_url
            custom_status = "🟢 فعال"
        else:
            payment_method = "🔵 مستقیم زرین‌پال"
            effective_url = config.zarinpal.DIRECT_PAYMENT_BASE_URL
            custom_status = "⚪ غیرفعال"
    else:
        if config.zarinpal.PAYMENT_BASE_URL:
            payment_method = "🟢 مسیر .env"
            effective_url = config.zarinpal.PAYMENT_BASE_URL
            custom_status = "⚪ استفاده نمی‌شود"
        else:
            payment_method = "🔵 مستقیم زرین‌پال"
            effective_url = config.zarinpal.DIRECT_PAYMENT_BASE_URL
            custom_status = "⚪ استفاده نمی‌شود"

    nahan_configured = bool(settings and settings.nahanramz_configured)
    nahan_status = "🟢 تنظیم شده" if nahan_configured else "🔴 تنظیم نشده"
    webhook_url = f"{config.bot.DOMAIN}/nahanramz"

    text = (
        "💳 <b>تنظیمات درگاه‌های پرداخت</b>\n\n"
        "🏦 <b>زرین‌پال</b>\n"
        "وضعیت درگاه: <b>🟢 فعال</b>\n"
        f"روش نمایش پرداخت: <b>{payment_method}</b>\n"
        f"مسیر پرداخت مؤثر: <code>{effective_url}</code>\n"
        f"مسیر سفارشی: <code>{env_url}</code>\n"
        f"وضعیت مسیر سفارشی: <b>{custom_status}</b>\n\n"
        "🪙 <b>نهان رمز</b>\n"
        f"وضعیت اتصال: <b>{nahan_status}</b>\n"
        f"Webhook: <code>{webhook_url}</code>\n"
        "مدل: <b>MANAGED_CUSTODIAL</b> | مبلغ ورودی: <b>IRT</b>"
    )
    await callback.message.edit_text(text, reply_markup=menu_markup(settings))


async def show_nahanramz_menu(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await PaymentGatewaySettings.get(session)
    configured = bool(settings and settings.nahanramz_configured)
    api_status = "🟢 تنظیم شده" if settings and settings.nahanramz_api_key.strip() else "🔴 تنظیم نشده"
    secret_status = "🟢 تنظیم شده" if settings and settings.nahanramz_webhook_secret.strip() else "🔴 تنظیم نشده"
    method = await PaymentMethodSettings.get_by_key(session, "pay_nahanramz")
    enabled = bool(method and method.enabled)
    webhook_url = f"{config.bot.DOMAIN}/nahanramz"
    text = (
        "🪙 <b>تنظیمات نهان رمز</b>\n\n"
        f"API Key: <b>{api_status}</b>\n"
        f"Webhook Secret: <b>{secret_status}</b>\n"
        f"اتصال کامل: <b>{'🟢 آماده' if configured else '🔴 ناقص'}</b>\n"
        f"نمایش برای مشتری: <b>{'🟢 فعال' if enabled else '🔴 مخفی'}</b>\n\n"
        f"Webhook URL:\n<code>{webhook_url}</code>\n\n"
        "پس از دریافت کلیدها از نهان رمز، آنها را اینجا وارد کنید. "
        "کلیدها فقط در backend نگهداری می‌شوند و به مشتری نمایش داده نمی‌شوند."
    )
    await callback.message.edit_text(text, reply_markup=nahanramz_markup(configured))


@router.callback_query(F.data == NavAdminTools.PAYMENT_GATEWAY_SETTINGS, IsAdmin())
async def payment_gateway_settings_menu(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    await callback.answer()
    await show_menu(callback, session, config)


@router.callback_query(F.data == "paymentgateway:nahanramz", IsAdmin())
async def nahanramz_menu(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    await callback.answer()
    await show_nahanramz_menu(callback, session, config)


@router.callback_query(F.data == "paymentgateway:nahanramz_api_key", IsAdmin())
async def nahanramz_api_key_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(PaymentGatewaySettingsState.waiting_nahanramz_api_key)
    await callback.message.edit_text(
        "🔑 <b>API Key نهان رمز</b>\n\nکلید <code>ck_test_...</code> یا <code>ck_live_...</code> را ارسال کنید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 انصراف", callback_data="paymentgateway:nahanramz")]]),
    )


@router.message(PaymentGatewaySettingsState.waiting_nahanramz_api_key, IsAdmin())
async def nahanramz_api_key_received(message: Message, state: FSMContext, session: AsyncSession, config: Config) -> None:
    value = (message.text or "").strip()
    if not value or not (value.startswith("ck_test_") or value.startswith("ck_live_")):
        await message.answer("❌ API Key معتبر نیست. باید با <code>ck_test_</code> یا <code>ck_live_</code> شروع شود.")
        return
    settings = await PaymentGatewaySettings.get(session)
    if settings is None:
        settings = PaymentGatewaySettings(id=1)
        session.add(settings)
    settings.nahanramz_api_key = value
    await session.commit()
    await state.clear()
    await message.answer("✅ API Key نهان رمز ذخیره شد.")


@router.callback_query(F.data == "paymentgateway:nahanramz_webhook_secret", IsAdmin())
async def nahanramz_webhook_secret_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(PaymentGatewaySettingsState.waiting_nahanramz_webhook_secret)
    await callback.message.edit_text(
        "🔐 <b>Webhook Secret نهان رمز</b>\n\nSecret را ارسال کنید. این مقدار در پیام‌های مشتری نمایش داده نمی‌شود.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 انصراف", callback_data="paymentgateway:nahanramz")]]),
    )


@router.message(PaymentGatewaySettingsState.waiting_nahanramz_webhook_secret, IsAdmin())
async def nahanramz_webhook_secret_received(message: Message, state: FSMContext, session: AsyncSession, config: Config) -> None:
    value = (message.text or "").strip()
    if len(value) < 16:
        await message.answer("❌ Webhook Secret خیلی کوتاه است.")
        return
    settings = await PaymentGatewaySettings.get(session)
    if settings is None:
        settings = PaymentGatewaySettings(id=1)
        session.add(settings)
    settings.nahanramz_webhook_secret = value
    await session.commit()
    await state.clear()
    await message.answer("✅ Webhook Secret نهان رمز ذخیره شد.")


@router.callback_query(F.data == "paymentgateway:nahanramz_test", IsAdmin())
async def nahanramz_test_connection(callback: CallbackQuery, gateway_factory: GatewayFactory) -> None:
    await callback.answer("در حال تست اتصال...", show_alert=False)
    try:
        gateway = gateway_factory.get_gateway("pay_nahanramz")
        result = await gateway.test_connection()
        rate_count = len(result.get("rates") or result.get("data") or []) if isinstance(result, dict) else 0
        await callback.message.edit_text(
            "✅ <b>اتصال نهان رمز موفق است.</b>\n\n"
            f"پاسخ API دریافت شد. تعداد نرخ‌های دریافتی: <b>{rate_count}</b>\n\n"
            "اکنون می‌توانید روش پرداخت نهان رمز را از بخش «نمایش روش‌های پرداخت» برای مشتری فعال کنید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 تنظیمات نهان رمز", callback_data="paymentgateway:nahanramz")]]),
        )
    except Exception as exc:
        await callback.message.edit_text(
            "❌ <b>تست اتصال نهان رمز ناموفق بود.</b>\n\n"
            f"<code>{str(exc)[:700]}</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 تنظیمات نهان رمز", callback_data="paymentgateway:nahanramz")]]),
        )


@router.callback_query(F.data == "paymentgateway:nahanramz_clear", IsAdmin())
async def nahanramz_clear(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await PaymentGatewaySettings.get(session)
    if settings is not None:
        settings.nahanramz_api_key = ""
        settings.nahanramz_webhook_secret = ""
    method = await PaymentMethodSettings.get_by_key(session, "pay_nahanramz")
    if method is not None:
        method.enabled = False
    await session.commit()
    await callback.answer("اطلاعات اتصال نهان رمز پاک شد و روش پرداخت مخفی شد.", show_alert=True)
    await show_nahanramz_menu(callback, session, config)


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

    if not method.enabled and method.method_key == "pay_nahanramz":
        settings = await PaymentGatewaySettings.get(session)
        if not settings or not settings.nahanramz_configured:
            await callback.answer("❌ ابتدا API Key و Webhook Secret نهان رمز را تنظیم کنید.", show_alert=True)
            return

    if method.enabled:
        enabled_count = sum(1 for item in methods if item.enabled)
        if enabled_count <= 1:
            await callback.answer("❌ حداقل یک روش پرداخت باید برای مشتری فعال باشد.", show_alert=True)
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
    await callback.answer()
    await state.set_state(PaymentGatewaySettingsState.waiting_zarinpal_payment_base_url)
    await callback.message.edit_text(
        "✏️ <b>مسیر پرداخت اختصاصی زرین‌پال</b>\n\n"
        "آدرس پایه را وارد کنید. مثال:\n<code>https://payment.yashginartgallery.com</code>\n\n"
        "یا برای نمایش مستقیم صفحه پرداخت زرین‌پال، گزینه زیر را انتخاب کنید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔴 استفاده مستقیم از زرین‌پال", callback_data="paymentgateway:set_direct")],
            [InlineKeyboardButton(text="🔙 انصراف", callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS)],
        ]),
    )


@router.callback_query(F.data == "paymentgateway:set_direct", IsAdmin())
async def set_direct_payment(callback: CallbackQuery, state: FSMContext, session: AsyncSession, config: Config) -> None:
    settings = await PaymentGatewaySettings.get(session)
    if settings is None:
        settings = PaymentGatewaySettings(id=1)
        session.add(settings)
    settings.zarinpal_payment_base_url = ""
    settings.zarinpal_payment_base_url_configured = True
    await session.commit()
    await state.clear()
    await callback.answer("پرداخت مستقیم زرین‌پال فعال شد.", show_alert=True)
    await show_menu(callback, session, config)


@router.message(PaymentGatewaySettingsState.waiting_zarinpal_payment_base_url, IsAdmin())
async def receive_zarinpal_url(message: Message, state: FSMContext, session: AsyncSession, config: Config) -> None:
    from urllib.parse import urlparse
    value = (message.text or "").strip().rstrip("/")
    if value:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            await message.answer("❌ آدرس معتبر نیست. فقط یک URL پایه HTTPS وارد کنید.")
            return
    settings = await PaymentGatewaySettings.get(session)
    if settings is None:
        settings = PaymentGatewaySettings(id=1)
        session.add(settings)
    settings.zarinpal_payment_base_url = value
    settings.zarinpal_payment_base_url_configured = True
    await session.commit()
    await state.clear()
    await message.answer("✅ تنظیمات مسیر پرداخت زرین‌پال ذخیره شد.")


@router.callback_query(F.data == "paymentgateway:disable_custom_url", IsAdmin())
async def disable_custom_url(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await PaymentGatewaySettings.get(session)
    if settings is None:
        settings = PaymentGatewaySettings(id=1)
        session.add(settings)
    settings.zarinpal_payment_base_url = ""
    settings.zarinpal_payment_base_url_configured = True
    await session.commit()
    await callback.answer("پرداخت مستقیم زرین‌پال فعال شد.", show_alert=True)
    await show_menu(callback, session, config)


@router.callback_query(F.data == "paymentgateway:reset_env", IsAdmin())
async def reset_to_env(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await PaymentGatewaySettings.get(session)
    if settings is None:
        await callback.answer("در حال حاضر از .env استفاده می‌شود.", show_alert=True)
        return
    settings.zarinpal_payment_base_url = ""
    settings.zarinpal_payment_base_url_configured = False
    await session.commit()
    await callback.answer("مقدار .env دوباره فعال شد.", show_alert=True)
    await show_menu(callback, session, config)


@router.callback_query(F.data == "paymentgateway:use_env", IsAdmin())
async def use_env(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    await reset_to_env(callback, session, config)
