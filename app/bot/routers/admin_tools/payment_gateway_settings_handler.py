from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.payment_gateways import GatewayFactory
from app.bot.utils.navigation import NavAdminTools
from app.config import Config
from app.db.models import PaymentGatewaySettings, PaymentMethodSettings

router = Router(name=__name__)


class PaymentGatewaySettingsState(StatesGroup):
    waiting_zarinpal_payment_base_url = State()


def menu_markup(settings: PaymentGatewaySettings | None) -> InlineKeyboardMarkup:
    configured = bool(settings and settings.zarinpal_payment_base_url_configured)
    url = (settings.zarinpal_payment_base_url if settings else "").strip()
    rows = [
        [InlineKeyboardButton(text="✏️ ویرایش مسیر پرداخت زرین‌پال", callback_data="paymentgateway:edit_zarinpal_url")],
    ]
    if configured:
        rows.append([
            InlineKeyboardButton(text="🔴 استفاده مستقیم از زرین‌پال", callback_data="paymentgateway:disable_custom_url")
        ])
        if url:
            rows.append([
                InlineKeyboardButton(text="♻️ بازگشت به مقدار .env", callback_data="paymentgateway:reset_env")
            ])
    else:
        rows.append([
            InlineKeyboardButton(text="🟢 استفاده از مسیر .env", callback_data="paymentgateway:use_env")
        ])
    rows.append([
        InlineKeyboardButton(
            text="👁️ مدیریت نمایش روش‌های پرداخت",
            callback_data="paymentgateway:methods",
        )
    ])
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_methods_markup(methods: list[PaymentMethodSettings]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    for method in methods:
        action = "🔴 مخفی کردن" if method.enabled else "🟢 نمایش دادن"
        rows.append([
            InlineKeyboardButton(
                text=f"{action} | {method.display_name}",
                callback_data=f"paymentmethod:toggle:{method.id}",
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text="🔙 تنظیمات درگاه‌ها",
            callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS,
        )
    ])
    rows.append([InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavAdminTools.MAIN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_payment_methods(
    callback: CallbackQuery,
    session: AsyncSession,
    gateway_factory: GatewayFactory,
) -> None:
    methods = await PaymentMethodSettings.get_manageable(
        session,
        gateway_factory.get_gateways(),
    )

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
        "ترتیب فعلی مشتری:",
        "1️⃣ زرین‌پال",
        "2️⃣ کارت به کارت",
        "3️⃣ کیف پول",
        "",
        "درگاه‌های جدیدی که در آینده به سیستم اضافه شوند نیز به‌صورت خودکار در این فهرست قابل مدیریت خواهند بود.",
    ])

    await callback.message.edit_text(
        "\n".join(lines),
        reply_markup=payment_methods_markup(methods),
    )


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

    text = (
        "💳 <b>تنظیمات درگاه‌های پرداخت</b>\n\n"
        "🏦 <b>زرین‌پال</b>\n"
        "وضعیت درگاه: <b>🟢 فعال</b>\n"
        f"روش نمایش پرداخت: <b>{payment_method}</b>\n"
        f"مسیر پرداخت مؤثر: <code>{effective_url}</code>\n"
        f"مسیر سفارشی: <code>{env_url}</code>\n"
        f"وضعیت مسیر سفارشی: <b>{custom_status}</b>\n\n"
        "در حالت مستقیم، مشتری مستقیماً به صفحه پرداخت زرین‌پال هدایت می‌شود."
    )
    await callback.message.edit_text(text, reply_markup=menu_markup(settings))


@router.callback_query(F.data == NavAdminTools.PAYMENT_GATEWAY_SETTINGS, IsAdmin())
async def payment_gateway_settings_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    config: Config,
) -> None:
    await callback.answer()
    await show_menu(callback, session, config)


@router.callback_query(F.data == "paymentgateway:methods", IsAdmin())
async def payment_methods_menu(
    callback: CallbackQuery,
    session: AsyncSession,
    gateway_factory: GatewayFactory,
) -> None:
    await callback.answer()
    await show_payment_methods(callback, session, gateway_factory)


@router.callback_query(F.data.regexp(r"^paymentmethod:toggle:\d+$"), IsAdmin())
async def toggle_payment_method(
    callback: CallbackQuery,
    session: AsyncSession,
    gateway_factory: GatewayFactory,
) -> None:
    method_id = int(callback.data.rsplit(":", 1)[1])
    methods = await PaymentMethodSettings.get_manageable(
        session,
        gateway_factory.get_gateways(),
    )
    method = next((item for item in methods if item.id == method_id), None)

    if method is None:
        await callback.answer("❌ روش پرداخت پیدا نشد.", show_alert=True)
        return

    if method.enabled:
        enabled_count = sum(1 for item in methods if item.enabled)
        if enabled_count <= 1:
            await callback.answer(
                "❌ حداقل یک روش پرداخت باید برای مشتری فعال باشد.",
                show_alert=True,
            )
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
        "آدرس پایه را وارد کنید. مثال:\n"
        "<code>https://payment.yashginartgallery.com</code>\n\n"
        "یا برای نمایش مستقیم صفحه پرداخت زرین‌پال، گزینه زیر را انتخاب کنید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔴 استفاده مستقیم از زرین‌پال",
                    callback_data="paymentgateway:set_direct",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 انصراف",
                    callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS,
                )
            ],
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
    value = (message.text or "").strip().rstrip("/")
    if value:
        parsed = urlparse(value)
        if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            await message.answer(
                "❌ آدرس معتبر نیست. فقط یک URL پایه HTTPS وارد کنید، مثل:\n"
                "<code>https://payment.yashginartgallery.com</code>"
            )
            return

    settings = await PaymentGatewaySettings.get(session)
    if settings is None:
        settings = PaymentGatewaySettings(id=1)
        session.add(settings)

    settings.zarinpal_payment_base_url = value
    settings.zarinpal_payment_base_url_configured = True
    await session.commit()
    await state.clear()

    await message.answer(
        "✅ تنظیمات مسیر پرداخت زرین‌پال ذخیره شد.\n\n"
        + (f"مسیر سفارشی: <code>{value}</code>" if value else "حالت مستقیم: مشتری مستقیماً به زرین‌پال می‌رود.")
    )


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
