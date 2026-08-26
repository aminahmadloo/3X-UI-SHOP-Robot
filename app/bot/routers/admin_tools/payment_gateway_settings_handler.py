from urllib.parse import urlparse

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools
from app.config import Config
from app.db.models import PaymentGatewaySettings

router = Router(name=__name__)


class PaymentGatewaySettingsState(StatesGroup):
    waiting_zarinpal_payment_base_url = State()


def menu_markup(settings: PaymentGatewaySettings | None) -> InlineKeyboardMarkup:
    configured = bool(settings and settings.zarinpal_payment_base_url_configured)
    rows = [
        [InlineKeyboardButton(text="✏️ ویرایش مسیر پرداخت زرین‌پال", callback_data="paymentgateway:edit_zarinpal_url")],
    ]
    if configured:
        rows.append([
            InlineKeyboardButton(
                text="🔴 استفاده مستقیم از زرین‌پال",
                callback_data="paymentgateway:disable_custom_url",
            )
        ])
        rows.append([
            InlineKeyboardButton(
                text="♻️ بازگشت به مقدار .env",
                callback_data="paymentgateway:reset_env",
            )
        ])
    rows.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_menu(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await PaymentGatewaySettings.get(session)
    env_url = config.zarinpal.PAYMENT_BASE_URL or "تنظیم نشده"

    if settings and settings.zarinpal_payment_base_url_configured:
        custom_url = settings.zarinpal_payment_base_url.strip()
        if custom_url:
            status = "🟢 فعال (تنظیم مدیریت)"
            effective_url = custom_url
        else:
            status = "🔵 مستقیم زرین‌پال (تنظیم مدیریت)"
            effective_url = config.zarinpal.DIRECT_PAYMENT_BASE_URL
    else:
        status = "🟢 فعال از .env" if config.zarinpal.PAYMENT_BASE_URL else "🔵 مستقیم زرین‌پال"
        effective_url = config.zarinpal.PAYMENT_BASE_URL or config.zarinpal.DIRECT_PAYMENT_BASE_URL

    text = (
        "💳 <b>تنظیمات درگاه‌های پرداخت</b>\n\n"
        "🏦 <b>زرین‌پال</b>\n"
        f"وضعیت مسیر پرداخت: <b>{status}</b>\n"
        f"مسیر مؤثر: <code>{effective_url}</code>\n\n"
        f"مقدار .env: <code>{env_url}</code>\n\n"
        "اگر مسیر پرداخت اختصاصی خالی باشد یا حالت مستقیم انتخاب شود، مشتری مستقیماً به صفحه پرداخت زرین‌پال هدایت می‌شود."
    )
    await callback.message.edit_text(text, reply_markup=menu_markup(settings))


@router.callback_query(F.data == NavAdminTools.PAYMENT_GATEWAY_SETTINGS, IsAdmin())
async def payment_gateway_settings_menu(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    await callback.answer()
    await show_menu(callback, session, config)


@router.callback_query(F.data == "paymentgateway:edit_zarinpal_url", IsAdmin())
async def edit_zarinpal_url_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(PaymentGatewaySettingsState.waiting_zarinpal_payment_base_url)
    await callback.message.edit_text(
        "✏️ <b>مسیر پرداخت اختصاصی زرین‌پال</b>\n\n"
        "آدرس پایه را وارد کنید. مثال:\n"
        "<code>https://payment.yashginartgallery.com</code>\n\n"
        "برای استفاده مستقیم از زرین‌پال، مقدار خالی را ذخیره کنید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 انصراف", callback_data="paymentgateway:cancel_edit")]
        ]),
    )


@router.callback_query(F.data == "paymentgateway:cancel_edit", IsAdmin())
async def cancel_edit(callback: CallbackQuery, state: FSMContext, session: AsyncSession, config: Config) -> None:
    await state.clear()
    await callback.answer()
    await show_menu(callback, session, config)


@router.message(PaymentGatewaySettingsState.waiting_zarinpal_payment_base_url, IsAdmin())
async def receive_zarinpal_url(message: Message, state: FSMContext, session: AsyncSession) -> None:
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
        + (
            f"مسیر سفارشی: <code>{value}</code>"
            if value
            else "حالت مستقیم: مشتری مستقیماً به زرین‌پال می‌رود."
        )
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
