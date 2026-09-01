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
    waiting_access_token = State()


def kpay_markup(configured: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="🔐 تنظیم Access Token حساب KPay", callback_data="paymentgateway:kpay_access_token")],
        [InlineKeyboardButton(text="🔄 دریافت خودکار Shop و Card", callback_data="paymentgateway:kpay_sync")],
    ]
    if configured:
        rows.append([InlineKeyboardButton(text="🧪 تست و همگام‌سازی KPay", callback_data="paymentgateway:kpay_test")])
        rows.append([InlineKeyboardButton(text="🗑️ پاک کردن اطلاعات KPay", callback_data="paymentgateway:kpay_clear")])
    rows.extend([
        [InlineKeyboardButton(text="👁️ مدیریت نمایش روش‌های پرداخت", callback_data="paymentgateway:methods")],
        [InlineKeyboardButton(text="🔙 تنظیمات درگاه‌ها", callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS)],
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_kpay_menu(callback: CallbackQuery, session: AsyncSession, config: Config) -> None:
    settings = await PaymentGatewaySettings.get(session)
    configured = bool(settings and settings.kpay_api_key.strip())
    token_status = "🟢 تنظیم شده" if settings and settings.kpay_api_key.strip() else "🔴 تنظیم نشده"
    shop_status = "🟢 دریافت شده" if settings and settings.kpay_shop_id.strip() else "🟡 هنوز دریافت نشده"
    card_status = "🟢 دریافت شده" if settings and settings.kpay_card_id.strip() else "🟡 هنوز دریافت نشده"
    method = await PaymentMethodSettings.get_by_key(session, "pay_kpay")
    enabled = bool(method and method.enabled)
    callback_url = f"{config.bot.DOMAIN.rstrip('/')}/kpay/callback"

    text = (
        "💳 <b>کارت‌به‌کارت هوشمند — KPay</b>\n\n"
        f"Access Token حساب: <b>{token_status}</b>\n"
        f"Shop ID: <b>{shop_status}</b>\n"
        f"Card ID: <b>{card_status}</b>\n"
        f"اتصال کامل: <b>{'🟢 آماده' if configured and settings and settings.kpay_shop_id.strip() and settings.kpay_card_id.strip() else '🟡 نیازمند همگام‌سازی' if configured else '🔴 ناقص'}</b>\n"
        f"نمایش برای مشتری: <b>{'🟢 فعال' if enabled else '🔴 مخفی'}</b>\n\n"
        f"Callback URL:\n<code>{callback_url}</code>\n\n"
        "Shop ID و Card ID از API رسمی KPay به‌صورت خودکار دریافت می‌شوند؛ نیازی به ورود دستی UUID نیست.\n"
        "کارت بانکی در خود KPay مدیریت می‌شود و شماره کامل کارت در ToonelVPN ذخیره نمی‌شود.\n"
        "برای احراز هویت API، Access Token حساب KPay استفاده می‌شود."
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


@router.callback_query(F.data == "paymentgateway:kpay_access_token", IsAdmin())
async def kpay_access_token_start(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.set_state(KPaySettingsState.waiting_access_token)
    await callback.message.edit_text(
        "🔐 <b>Access Token حساب KPay</b>\n\n"
        "این همان access_token است که KPay در پاسخ <code>/auth/login</code> یا <code>/auth/register</code> برمی‌گرداند.\n\n"
        "⚠️ شماره موبایل، رمز عبور یا شماره کارت را ارسال نکنید؛ فقط Access Token را در این مرحله وارد کنید.\n\n"
        "کلید API نمایشی Shop با Access Token حساب متفاوت است.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 انصراف", callback_data="paymentgateway:kpay")]]),
    )


@router.message(KPaySettingsState.waiting_access_token, IsAdmin())
async def kpay_access_token_received(message: Message, state: FSMContext, session: AsyncSession) -> None:
    value = (message.text or "").strip()
    if len(value) < 20:
        await message.answer("❌ Access Token معتبر نیست یا ناقص ارسال شده است.")
        return
    await _save_setting(session, "kpay_api_key", value)
    settings = await PaymentGatewaySettings.get(session)
    if settings is not None:
        settings.kpay_shop_id = ""
        settings.kpay_card_id = ""
        await session.commit()
    await state.clear()
    await message.answer("✅ Access Token حساب KPay ذخیره شد. اکنون از «🔄 دریافت خودکار Shop و Card» استفاده کنید.")


async def _sync_and_show(callback: CallbackQuery, gateway_factory: GatewayFactory) -> None:
    gateway = gateway_factory.get_gateway("pay_kpay")
    result = await gateway.test_connection()
    shop = result.get("shop") or {}
    card = result.get("card") or {}
    card_number = str(card.get("card_number") or "")
    masked_card = f"****{card_number[-4:]}" if len(card_number) >= 4 else "ثبت‌شده در KPay"
    await callback.message.edit_text(
        "✅ <b>Shop و Card با موفقیت از KPay دریافت و ذخیره شدند.</b>\n\n"
        f"Shop: <b>{shop.get('name') or 'OK'}</b>\n"
        f"Card: <code>{masked_card}</code>\n"
        f"Callback: <code>{result.get('callback_url')}</code>\n\n"
        "اکنون دیگر نیازی به ورود دستی Shop ID یا Card ID نیست.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 تنظیمات KPay", callback_data="paymentgateway:kpay")]]),
    )


@router.callback_query(F.data == "paymentgateway:kpay_sync", IsAdmin())
async def kpay_sync(callback: CallbackQuery, gateway_factory: GatewayFactory) -> None:
    await callback.answer("در حال دریافت Shop و Card از KPay...", show_alert=False)
    try:
        await _sync_and_show(callback, gateway_factory)
    except Exception as exc:
        await callback.message.edit_text(
            "❌ <b>همگام‌سازی KPay ناموفق بود.</b>\n\n"
            f"<code>{str(exc)[:700]}</code>\n\n"
            "ابتدا Access Token حساب KPay را تنظیم کنید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 تنظیمات KPay", callback_data="paymentgateway:kpay")]]),
        )


@router.callback_query(F.data == "paymentgateway:kpay_test", IsAdmin())
async def kpay_test_connection(callback: CallbackQuery, gateway_factory: GatewayFactory) -> None:
    await callback.answer("در حال تست و همگام‌سازی KPay...", show_alert=False)
    try:
        await _sync_and_show(callback, gateway_factory)
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
