from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.filters import IsAdmin
from app.bot.utils.navigation import NavAdminTools

router = Router(name=__name__)


def _keyboard() -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    b.row(
        InlineKeyboardButton(
            text="📅 مدیریت دوره‌های سرویس",
            callback_data="sp:management",
        )
    )
    b.row(
        InlineKeyboardButton(
            text="📈 مدیریت افزایش حجم",
            callback_data="traffic_admin:management",
        )
    )
    b.row(
        InlineKeyboardButton(
            text="🔄 مدیریت تمدید زمانی سرویس",
            callback_data=NavAdminTools.SERVICE_PURCHASE_RENEWAL_MANAGEMENT,
        )
    )
    b.row(
        InlineKeyboardButton(
            text="📱 مدیریت تعداد دستگاه",
            callback_data=NavAdminTools.SERVICE_PURCHASE_DEVICES,
        )
    )
    b.row(
        InlineKeyboardButton(
            text="🎁 مدیریت محصولات ویژه",
            callback_data="service_purchase:special_products",
        )
    )
    b.row(
        InlineKeyboardButton(
            text="⚙️ تنظیمات خرید سرویس",
            callback_data="service_purchase:settings",
        )
    )
    b.row(InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavAdminTools.MAIN))
    return b.as_markup()


@router.callback_query(F.data == NavAdminTools.SERVICE_PURCHASE_MANAGEMENT, IsAdmin())
async def entry(callback: CallbackQuery) -> None:
    await callback.answer()
    await callback.message.edit_text(
        "🛒 <b>مدیریت خرید سرویس</b>\n\n"
        "بخش موردنظر را انتخاب کنید:",
        reply_markup=_keyboard(),
    )


@router.callback_query(F.data.in_({"service_purchase:special_products", "service_purchase:settings"}), IsAdmin())
async def reserved_sections(callback: CallbackQuery) -> None:
    await callback.answer("🚧 این بخش در مرحله بعدی تکمیل می‌شود.", show_alert=True)
