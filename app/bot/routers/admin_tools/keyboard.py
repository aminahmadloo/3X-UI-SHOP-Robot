from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.routers.misc.keyboard import back_button, back_to_main_menu_button, cancel_button
from app.bot.utils.navigation import NavAdminTools
from app.db.models import Server, ServicePurchasePlan
from app.db.models.invite import Invite


def admin_tools_keyboard(is_dev: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_dev:
        builder.row(InlineKeyboardButton(text=_("admin_tools:button:server_management"), callback_data=NavAdminTools.SERVER_MANAGEMENT))
        builder.row(InlineKeyboardButton(text="🎯 مدیریت اینباندهای سرویس", callback_data=NavAdminTools.INBOUND_MANAGEMENT))
    builder.row(InlineKeyboardButton(text=_("admin_tools:button:statistics"), callback_data=NavAdminTools.STATISTICS), InlineKeyboardButton(text=_("admin_tools:button:user_editor"), callback_data=NavAdminTools.USER_EDITOR))
    builder.row(InlineKeyboardButton(text=_("admin_tools:button:invite_editor"), callback_data=NavAdminTools.INVITE_EDITOR), InlineKeyboardButton(text=_("admin_tools:button:promocode_editor"), callback_data=NavAdminTools.PROMOCODE_EDITOR))
    builder.row(InlineKeyboardButton(text=_("admin_tools:button:notification"), callback_data=NavAdminTools.NOTIFICATION), InlineKeyboardButton(text="💳 مدیریت کارت به کارت", callback_data=NavAdminTools.CARD_SETTINGS))
    builder.row(InlineKeyboardButton(text="⚙️ تنظیمات خرید سرویس ها با مشخصات دلخواه", callback_data=NavAdminTools.CUSTOM_SERVICE_PRICING))
    builder.row(InlineKeyboardButton(text="💳 تنظیمات درگاه‌های پرداخت", callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS))
    builder.row(InlineKeyboardButton(text="⚙️ تنظیمات .env", callback_data=NavAdminTools.ENV_SETTINGS))
    builder.row(InlineKeyboardButton(text="🛒 تنظیمات خرید سرویس|حجم سرویس|زمان سرویس", callback_data=NavAdminTools.SERVICE_PURCHASE_MANAGEMENT))
    builder.row(InlineKeyboardButton(text="⚙️ مدیریت تنظیمات سابسکریپشن", callback_data=NavAdminTools.SUBSCRIPTION_SETTINGS))
    builder.row(InlineKeyboardButton(text=_("admin_tools:button:test_button"), callback_data=NavAdminTools.TEST_ACCOUNT_SETTINGS), InlineKeyboardButton(text=_("admin_tools:button:create_backup"), callback_data=NavAdminTools.CREATE_BACKUP))
    if is_dev:
        builder.row(InlineKeyboardButton(text="💾 Backup کامل ربات", callback_data="full_backup:menu"))
    builder.row(InlineKeyboardButton(text=_("admin_tools:button:maintenance_mode"), callback_data=NavAdminTools.MAINTENANCE_MODE), InlineKeyboardButton(text=_("admin_tools:button:restart_bot"), callback_data=NavAdminTools.RESTART_BOT))
    builder.row(InlineKeyboardButton(text="💳 پرداخت‌های کارت به کارت", callback_data="cardpay:menu"))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def _plan_button_text(plan: ServicePurchasePlan) -> str:
    if plan.price_toman % 1000 == 0:
        price = f"{plan.price_toman // 1000:,} هزار تومان"
    else:
        price = f"{plan.price_toman:,} تومان"
    return f"{plan.volume_gb} گیگ / {plan.duration_days} روزه / {price}"


def service_purchase_management_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.row(InlineKeyboardButton(text="📅 مدیریت دوره‌های سرویس", callback_data="service_purchase:periods"))
    builder.row(InlineKeyboardButton(text="📈 مدیریت افزایش حجم", callback_data="traffic_admin:management"))
    builder.row(InlineKeyboardButton(text="⏳ تنظیمات افزایش زمان سرویس", callback_data="service_purchase:renewal"))
    builder.row(InlineKeyboardButton(text="📱 مدیریت تعداد دستگاه", callback_data=NavAdminTools.SERVICE_PURCHASE_DEVICES))
    builder.row(InlineKeyboardButton(text="🎁 مدیریت محصولات ویژه", callback_data="service_purchase:special_products"))
    builder.row(InlineKeyboardButton(text="⚙️ تنظیمات خرید سرویس", callback_data="service_purchase:settings"))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def connected_device_settings_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✏️ ویرایش تعداد دستگاه", callback_data="connected_device_settings:edit"))
    builder.row(back_button(NavAdminTools.SERVICE_PURCHASE_MANAGEMENT))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def service_purchase_plan_list_keyboard(plans: list[ServicePurchasePlan], service_type: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        builder.row(InlineKeyboardButton(text=_plan_button_text(plan), callback_data=f"{NavAdminTools.SERVICE_PURCHASE_PLAN}:{plan.id}"))
    create_callback = NavAdminTools.SERVICE_PURCHASE_CREATE_ONE_MONTH if service_type == "one_month" else NavAdminTools.SERVICE_PURCHASE_CREATE_THREE_MONTH
    builder.row(InlineKeyboardButton(text=("➕ ساخت سرویس جدید یک ماهه" if service_type == "one_month" else "➕ ساخت سرویس جدید سه ماهه"), callback_data=create_callback))
    builder.row(back_button(NavAdminTools.SERVICE_PURCHASE_MANAGEMENT))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def service_purchase_plan_details_keyboard(plan_id: int, service_type: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✏️ ویرایش", callback_data=f"{NavAdminTools.SERVICE_PURCHASE_EDIT}:{plan_id}"))
    builder.row(InlineKeyboardButton(text="🗑 حذف", callback_data=f"{NavAdminTools.SERVICE_PURCHASE_DELETE}:{plan_id}"))
    builder.row(back_button(NavAdminTools.SERVICE_PURCHASE_ONE_MONTH if service_type == "one_month" else NavAdminTools.SERVICE_PURCHASE_THREE_MONTH))
    return builder.as_markup()


def custom_service_pricing_keyboard(show_button: bool = True) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🚫 پنهان کردن دکمه خرید سرویس اختصاصی" if show_button else "👁️ نمایش دکمه خرید سرویس اختصاصی", callback_data="custom_service_pricing:toggle_button"))
    builder.row(InlineKeyboardButton(text="✏️ ویرایش مبالغ", callback_data="custom_service_pricing:edit"))
    builder.row(InlineKeyboardButton(text="🔄 بازخوانی مقادیر", callback_data=NavAdminTools.CUSTOM_SERVICE_PRICING))
    builder.row(back_button(NavAdminTools.MAIN))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def custom_service_pricing_edit_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💾 ذخیره", callback_data="custom_service_pricing:save"))
    builder.row(InlineKeyboardButton(text="❌ انصراف", callback_data=NavAdminTools.CUSTOM_SERVICE_PRICING))
    return builder.as_markup()


def promocode_editor_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=_("promocode_editor:button:create"), callback_data=NavAdminTools.CREATE_PROMOCODE))
    builder.row(InlineKeyboardButton(text=_("promocode_editor:button:delete"), callback_data=NavAdminTools.DELETE_PROMOCODE))
    builder.row(InlineKeyboardButton(text=_("promocode_editor:button:edit"), callback_data=NavAdminTools.EDIT_PROMOCODE))
    builder.adjust(3)
    builder.row(back_button(NavAdminTools.PROMOCODE_EDITOR))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def promocode_duration_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for duration in [1, 7, 30, 90, 365]:
        duration_text = _("1 day", "{} days", duration).format(duration)
        builder.row(InlineKeyboardButton(text=duration_text, callback_data=f"{duration}"))
    builder.adjust(2)
    builder.row(back_button(NavAdminTools.PROMOCODE_EDITOR))
    return builder.as_markup()


def maintenance_mode_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    from app.bot.middlewares import MaintenanceMiddleware
    if MaintenanceMiddleware.active:
        builder.row(InlineKeyboardButton(text=_("maintenance_mode:button:disable"), callback_data=NavAdminTools.MAINTENANCE_MODE_DISABLE))
    else:
        builder.row(InlineKeyboardButton(text=_("maintenance_mode:button:enable"), callback_data=NavAdminTools.MAINTENANCE_MODE_ENABLE))
    builder.adjust(2)
    builder.row(back_button(NavAdminTools.MAIN))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()
