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
    builder.row(InlineKeyboardButton(text="💳 تنظیمات درگاه‌های پرداخت", callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS))
    builder.row(InlineKeyboardButton(text="⚙️ تنظیمات خرید سرویس ها با مشخصات دلخواه", callback_data=NavAdminTools.CUSTOM_SERVICE_PRICING))
    builder.row(InlineKeyboardButton(text="🛒 تنظیمات خرید سرویس|حجم سرویس|زمان سرویس", callback_data=NavAdminTools.SERVICE_PURCHASE_MANAGEMENT))
    builder.row(InlineKeyboardButton(text="⚙️ مدیریت تنظیمات سابسکریپشن", callback_data=NavAdminTools.SUBSCRIPTION_SETTINGS))
    builder.row(InlineKeyboardButton(text=_("admin_tools:button:test_button"), callback_data=NavAdminTools.TEST), InlineKeyboardButton(text=_("admin_tools:button:create_backup"), callback_data=NavAdminTools.CREATE_BACKUP))
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

    builder.row(
        InlineKeyboardButton(
            text="📅 مدیریت دوره‌های سرویس",
            callback_data="service_purchase:periods",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="📈 مدیریت افزایش حجم",
            callback_data="traffic_admin:management",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="⏳ تنظیمات افزایش زمان سرویس",
            callback_data="service_purchase:renewal",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="📱 مدیریت تعداد دستگاه",
            callback_data=NavAdminTools.SERVICE_PURCHASE_DEVICES,
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="🎁 مدیریت محصولات ویژه",
            callback_data="service_purchase:special_products",
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="⚙️ تنظیمات خرید سرویس",
            callback_data="service_purchase:settings",
        )
    )

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


def custom_service_pricing_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
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


def servers_keyboard(servers: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    for server in servers:
        status = "🟢" if server.online else "🔴"
        builder.row(InlineKeyboardButton(text=f"{status} {server.name}", callback_data=NavAdminTools.SHOW_SERVER + f"_{server.name}"))

    builder.row(InlineKeyboardButton(text=_("server_management:button:sync"), callback_data=NavAdminTools.SYNC_SERVERS))
    builder.row(InlineKeyboardButton(text=_("server_management:button:add"), callback_data=NavAdminTools.ADD_SERVER))

    builder.row(back_button(NavAdminTools.MAIN))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def server_keyboard(server_name: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="✏️ ویرایش", callback_data=NavAdminTools.EDIT_SERVER + f"_{server_name}"))
    builder.row(InlineKeyboardButton(text=_("server_management:button:ping"), callback_data=NavAdminTools.PING_SERVER + f"_{server_name}"))
    builder.row(InlineKeyboardButton(text=_("server_management:button:delete"), callback_data=NavAdminTools.DELETE_SERVER + f"_{server_name}"))
    builder.adjust(2)
    builder.row(back_button(NavAdminTools.SERVER_MANAGEMENT))
    return builder.as_markup()


def confirm_add_server_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=_("server_management:button:confirm"), callback_data=NavAdminTools.СONFIRM_ADD_SERVER))
    builder.adjust(2)
    builder.row(back_button(NavAdminTools.ADD_SERVER_BACK))
    return builder.as_markup()


def confirm_edit_server_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💾 ذخیره تغییرات", callback_data=NavAdminTools.CONFIRM_EDIT_SERVER))
    builder.row(back_button(NavAdminTools.EDIT_SERVER_BACK))
    return builder.as_markup()


def notification_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=_("notification:button:send_to_user"), callback_data=NavAdminTools.SEND_NOTIFICATION_USER), InlineKeyboardButton(text=_("notification:button:send_to_all"), callback_data=NavAdminTools.SEND_NOTIFICATION_ALL))
    builder.row(InlineKeyboardButton(text=_("notification:button:last_notification"), callback_data=NavAdminTools.LAST_NOTIFICATION))
    builder.row(back_button(NavAdminTools.MAIN))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def last_notification_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text=_("notification:button:edit"), callback_data=NavAdminTools.EDIT_NOTIFICATION))
    builder.add(InlineKeyboardButton(text=_("notification:button:delete"), callback_data=NavAdminTools.DELETE_NOTIFICATION))
    builder.row(back_button(NavAdminTools.NOTIFICATION))
    return builder.as_markup()


def confirm_send_notification_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=_("notification:button:confirm"), callback_data=NavAdminTools.CONFIRM_SEND_NOTIFICATION))
    builder.row(cancel_button(NavAdminTools.NOTIFICATION))
    return builder.as_markup()


def invite_editor_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=_("invite_editor:button:create_invite"), callback_data=NavAdminTools.CREATE_INVITE))
    builder.row(InlineKeyboardButton(text=_("invite_editor:button:list_invites"), callback_data=NavAdminTools.LIST_INVITES))
    builder.row(back_button(NavAdminTools.MAIN))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def invite_list_keyboard(invites: list[Invite], page: int = 0, limit: int = 5) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    total_invites = len(invites)
    start_idx = page * limit
    end_idx = min(start_idx + limit, total_invites)
    for i in range(start_idx, end_idx):
        invite = invites[i]
        builder.row(InlineKeyboardButton(text=f"{invite.name} ({invite.clicks} clicks)", callback_data=NavAdminTools.SHOW_INVITE_DETAILS + f"_{invite.id}"))
    row = []
    if page > 0:
        row.append(InlineKeyboardButton(text=_("invite_editor:button:previous_page"), callback_data=NavAdminTools.SHOW_INVITE_PAGE + f"_{page-1}"))
    if (page + 1) * limit < total_invites:
        row.append(InlineKeyboardButton(text=_("invite_editor:button:next_page"), callback_data=NavAdminTools.SHOW_INVITE_PAGE + f"_{page+1}"))
    if row:
        builder.row(*row)
    builder.row(back_button(NavAdminTools.INVITE_EDITOR))
    return builder.as_markup()


def invite_details_keyboard(invite: Invite) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if invite.is_active:
        builder.row(InlineKeyboardButton(text=_("invite_editor:button:disable"), callback_data=NavAdminTools.TOGGLE_INVITE_STATUS + f"_{invite.id}"))
    else:
        builder.row(InlineKeyboardButton(text=_("invite_editor:button:enable"), callback_data=NavAdminTools.TOGGLE_INVITE_STATUS + f"_{invite.id}"))
    builder.row(InlineKeyboardButton(text=_("invite_editor:button:delete"), callback_data=NavAdminTools.CONFIRM_DELETE_INVITE + f"_{invite.id}"))
    builder.row(back_button(NavAdminTools.LIST_INVITES))
    return builder.as_markup()


def confirm_delete_invite_keyboard(invite_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=_("invite_editor:button:confirm_delete"), callback_data=NavAdminTools.DELETE_INVITE + f"_{invite_id}"))
    builder.row(cancel_button(NavAdminTools.SHOW_INVITE_DETAILS + f"_{invite_id}"))
    return builder.as_markup()


def inbound_management_keyboard(servers: list[Server]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for server in servers:
        status = "🟢" if server.online else "🔴"
        selected = len(server.configured_inbound_ids)
        builder.row(InlineKeyboardButton(text=f"{status} {server.name} ({selected} انتخاب)", callback_data=f"{NavAdminTools.INBOUND_MANAGEMENT}:server:{server.id}"))
    builder.row(back_button(NavAdminTools.MAIN))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def inbound_selection_keyboard(server: Server, inbounds: list) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    selected = set(server.configured_inbound_ids)
    for inbound in inbounds:
        inbound_id = int(inbound.id)
        checked = "☑️" if inbound_id in selected else "⬜️"
        remark = getattr(inbound, "remark", None) or getattr(inbound, "tag", None) or f"Inbound {inbound_id}"
        protocol = getattr(inbound, "protocol", "")
        port = getattr(inbound, "port", "")
        suffix = f" | {protocol}" if protocol else ""
        if port:
            suffix += f":{port}"
        builder.row(InlineKeyboardButton(text=f"{checked} {remark}{suffix} [#{inbound_id}]", callback_data=f"{NavAdminTools.INBOUND_MANAGEMENT}:toggle:{server.id}:{inbound_id}"))
    builder.row(InlineKeyboardButton(text="🔄 بازخوانی اینباندها", callback_data=f"{NavAdminTools.INBOUND_MANAGEMENT}:refresh:{server.id}"))
    builder.row(back_button(NavAdminTools.INBOUND_MANAGEMENT))
    return builder.as_markup()


def subscription_settings_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.row(
        InlineKeyboardButton(
            text="🌐 ویرایش دامنه",
            callback_data="subscription_settings:domain"
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="🔢 ویرایش پورت",
            callback_data="subscription_settings:port"
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="📁 ویرایش مسیر",
            callback_data="subscription_settings:path"
        )
    )

    builder.row(
        InlineKeyboardButton(
            text="🔄 بازخوانی مقادیر",
            callback_data=NavAdminTools.SUBSCRIPTION_SETTINGS
        )
    )

    builder.row(
        back_button(NavAdminTools.MAIN)
    )

    builder.row(
        back_to_main_menu_button()
    )

    return builder.as_markup()
