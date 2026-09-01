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


class KPaySettingsState(StatesGroup):
    waiting_api_key = State()
    waiting_shop_id = State()
    waiting_card_id = State()


def kpay_markup(configured: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🔑 تنظیم API Key", callback_data="paymentgateway:kpay_api_key")],
        [InlineKeyboardButton(text="🏪 تنظیم Shop ID", callback_data="paymentgateway:kpay_shop_id")],
        [InlineKeyboardButton(text="💳 تنظیم Card ID", callback_data="paymentgateway:kpay_card_id")],
    ]
    if configured:
        rows.append([InlineKeyboardButton(text="🧪 تست اتصال KPay", callback_data="paymentgateway:kpay_test")])
        rows.append([InlineKeyboardButton(text="🗑️ پاک کردن اطلاعات KPay", callback_data="paymentgateway:kpay_clear")])
    rows.extend([
        [InlineKeyboardButton(text="👁️ مدیریت نمایش روش‌های پرداخت", callback_data="paymentgateway:methods")],
        [InlineKeyboardButton(text="🔙 تنظیمات درگاه‌ها", callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS)],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_kpay_menu(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await PaymentGatewaySettings.get(session)
    configured = bool(settings and settings.kpay_configured)
    api_status = "🟢 تنظیم شده" if settings and settings.kpay_api_key.strip() else "🔴 تنظیم نشده"
    shop_status = "🟢 تنظیم شده" if settings and settings.kpay_shop_id.strip() else "🔴 تنظیم نشده"
    card_status = "🟢 تنظیم شده" if settings and settings.kpay_card_id.strip() else "🔴 تنظیم نشده"
    method = await PaymentMethodSettings.get_by_key(session, "pay_kpay")
    enabled = bool(method and method.enabled)
    callback_url = f"{config.bot.DOMAIN.rstrip('/')}/kpay/callback"

    text = (
        "💳 <b>کارت‌به‌کارت هوشمند — KPay</b>\n\n"
        f"API Key: <b>{api_status}</b>\n"
        f"Shop ID: <b>{shop_status}</b>\n"
        f"Card ID: <b>{card_status}</b>\n"
        f"اتصال کامل: <b>{'🟢 آماده' if configured else '🔴 ناقص'}</b>\n"
        f"نمایش برای مشتری: <b>{'🟢 فعال' if enabled else '🔴 مخفی'}</b>\n\n"
        f"Callback URL:\n<code>{callback_url}</code>\n\n"
        "کارت بانکی در خود KPay مدیریت می‌شود؛ ToonelVPN فقط API Key و شناسه Shop/Card را نگهداری می‌کند.\n"
        "مبلغ خرید از تومان به ریال تبدیل شده و فاکتور با مبلغ دقیق در KPay ساخته می‌شود."
    )
    await callback.message.edit_text(text, reply_markup=kpay_markup(configured))


async def _save_setting(session: AsyncSession, field: str, value: str) -> None:
    settings = await PaymentGatewaySettings.get(session)
    if settings is None:
        settings = PaymentGatewaySettings(id=1)
        session.add(settings)
    setattr(settings, field, value)
    await session.commit()


@router.callback_query(F.data == "paymentgateway:kpay", IsAdmin())
async def kpay_menu(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    await callback.answer()
    await show_kpay_menu(callback, session, config)


@router.callback_query(F.data == "paymentgateway:kpay_api_key", IsAdmin())
async def kpay_api_key_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(KPaySettingsState.waiting_api_key)
    await callback.message.edit_text(
        "🔑 <b>API Key KPay</b>\n\nAPI Key مربوط به Shop خود در KPay را ارسال کنید.\n\nاین کلید فقط در backend ذخیره می‌شود.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 انصراف", callback_data="paymentgateway:kpay")]]),
    )


@router.message(KPaySettingsState.waiting_api_key, IsAdmin())
async def kpay_api_key_received(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = (message.text or "").strip()
    if len(value) < 12:
        await message.answer("❌ API Key معتبر نیست.")
        return
    await _save_setting(session, "kpay_api_key", value)
    await state.clear()
    await message.answer("✅ API Key KPay ذخیره شد.")


@router.callback_query(F.data == "paymentgateway:kpay_shop_id", IsAdmin())
async def kpay_shop_id_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(KPaySettingsState.waiting_shop_id)
    await callback.message.edit_text(
        "🏪 <b>Shop ID KPay</b>\n\nشناسه Shop را از پنل KPay کپی و ارسال کنید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 انصراف", callback_data="paymentgateway:kpay")]]),
    )


@router.message(KPaySettingsState.waiting_shop_id, IsAdmin())
async def kpay_shop_id_received(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = (message.text or "").strip()
    if len(value) < 8:
        await message.answer("❌ Shop ID معتبر نیست.")
        return
    await _save_setting(session, "kpay_shop_id", value)
    await state.clear()
    await message.answer("✅ Shop ID KPay ذخیره شد.")


@router.callback_query(F.data == "paymentgateway:kpay_card_id", IsAdmin())
async def kpay_card_id_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(KPaySettingsState.waiting_card_id)
    await callback.message.edit_text(
        "💳 <b>Card ID KPay</b>\n\nشناسه کارتی که در KPay برای دریافت وجه فعال کرده‌اید را ارسال کنید.\n\nشماره کامل کارت را اینجا وارد نکنید.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 انصراف", callback_data="paymentgateway:kpay")]]),
    )


@router.message(KPaySettingsState.waiting_card_id, IsAdmin())
async def kpay_card_id_received(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = (message.text or "").strip()
    if len(value) < 8:
        await message.answer("❌ Card ID معتبر نیست.")
        return
    await _save_setting(session, "kpay_card_id", value)
    await state.clear()
    await message.answer("✅ Card ID KPay ذخیره شد.")


@router.callback_query(F.data == "paymentgateway:kpay_test", IsAdmin())
async def kpay_test_connection(callback: CallbackQuery, gateway_factory: GatewayFactory, config: Config) -> None:
    await callback.answer("در حال تست اتصال KPay...", show_alert=False)
    try:
        gateway = gateway_factory.get_gateway("pay_kpay")
        result = await gateway.test_connection()
        shop = result.get("shop") or {}
        card = result.get("card") or {}
        masked_card = str(card.get("card_number") or "ثبت‌شده در KPay")
        await callback.message.edit_text(
            "✅ <b>اتصال KPay موفق است.</b>\n\n"
            f"Shop: <b>{shop.get('name') or 'OK'}</b>\n"
            f"Card: <code>{masked_card}</code>\n"
            f"Callback: <code>{result.get('callback_url')}</code>\n\n"
            "اکنون می‌توانید روش «کارت‌به‌کارت هوشمند» را از بخش مدیریت نمایش روش‌های پرداخت برای مشتری فعال کنید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 تنظیمات KPay", callback_data="paymentgateway:kpay")]]),
        )
    except Exception as exc:
        await callback.message.edit_text(
            "❌ <b>تست اتصال KPay ناموفق بود.</b>\n\n"
            f"<code>{str(exc)[:700]}</code>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 تنظیمات KPay", callback_data="paymentgateway:kpay")]]),
        )


@router.callback_query(F.data == "paymentgateway:kpay_clear", IsAdmin())
async def kpay_clear(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await PaymentGatewaySettings.get(session)
    if settings is not None:
        settings.kpay_api_key = ""
        settings.kpay_shop_id = ""
        settings.kpay_card_id = ""
    method = await PaymentMethodSettings.get_by_key(session, "pay_kpay")
    if method is not None:
        method.enabled = False
    await session.commit()
    await callback.answer("اطلاعات KPay پاک شد و روش پرداخت مخفی شد.", show_alert=True)
    await show_kpay_menu(callback, session, config)
