from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.bot.services import PlanService

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.i18n import gettext as _
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.models import SubscriptionData
from app.bot.models.plan import Plan
from app.bot.payment_gateways import PaymentGateway
from app.bot.routers.misc.keyboard import back_button, back_to_main_menu_button, close_notification_button
from app.bot.utils.constants import Currency
from app.bot.utils.formatting import format_device_count, format_subscription_period
from app.bot.utils.navigation import NavDownload, NavMain, NavSubscription


_PAYMENT_METHOD_DEFAULTS = {
    "pay_zarinpal": ("🏦 زرین‌پال", 10),
    "mp_card": ("💳 کارت به کارت", 20),
    "mp_wallet": ("💰 کیف پول", 30),
}


def _payment_method_db_path() -> Path:
    db_name = os.getenv("DB_NAME", "bot_database").strip() or "bot_database"
    return Path("/app/data") / f"{db_name}.sqlite3"


def _enabled_payment_methods() -> set[str]:
    """Read payment visibility synchronously for the existing sync keyboard API.

    The payment keyboards are intentionally kept synchronous because they are
    used by many routers. The settings table is tiny and this read is only used
    while constructing a Telegram keyboard. On any read error we fail open to
    the three historical payment methods rather than breaking purchases.
    """
    defaults = set(_PAYMENT_METHOD_DEFAULTS)
    path = _payment_method_db_path()

    try:
        with sqlite3.connect(path, timeout=2) as connection:
            rows = connection.execute(
                "SELECT method_key FROM payment_method_settings WHERE enabled = 1"
            ).fetchall()
        return {str(row[0]) for row in rows} or defaults
    except (sqlite3.Error, OSError):
        return defaults


def _gateway_callback(gateway: PaymentGateway) -> str:
    callback = gateway.callback
    return str(getattr(callback, "value", callback) or "")


def _payment_method_buttons(
    builder: InlineKeyboardBuilder,
    price_toman: int,
    gateways: list[PaymentGateway],
) -> None:
    enabled = _enabled_payment_methods()
    gateway_map = {_gateway_callback(gateway): gateway for gateway in gateways}

    # Fixed order for the current methods. Newly registered gateways are
    # rendered afterwards according to their gateway callback/order setting.
    ordered_keys = ["pay_zarinpal", "mp_card", "mp_wallet"]
    ordered_keys.extend(
        key for key in gateway_map
        if key not in ordered_keys
    )

    for key in ordered_keys:
        if key not in enabled:
            continue

        if key == "mp_card":
            builder.row(
                InlineKeyboardButton(
                    text=f"💳 کارت به کارت | {price_toman:,} تومان",
                    callback_data=f"mp_card:{{plan_id}}",
                )
            )
            continue

        if key == "mp_wallet":
            builder.row(
                InlineKeyboardButton(
                    text=f"💰 کیف پول | {price_toman:,} تومان",
                    callback_data=f"mp_wallet:{{plan_id}}",
                )
            )
            continue

        gateway = gateway_map.get(key)
        if gateway is None:
            continue

        builder.row(
            InlineKeyboardButton(
                text=f"{gateway.name} | {price_toman:,} تومان",
                callback_data=f"mp:{key}:{{plan_id}}",
            )
        )


def change_subscription_button() -> InlineKeyboardButton:
    return InlineKeyboardButton(text=_("subscription:button:change"), callback_data=NavSubscription.CHANGE)


def subscription_keyboard(has_subscription: bool, callback_data: SubscriptionData) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if not has_subscription:
        builder.button(text=_("subscription:button:buy"), callback_data=callback_data)
    else:
        callback_data.state = NavSubscription.EXTEND
        builder.button(text=_("subscription:button:extend"), callback_data=callback_data)
        callback_data.state = NavSubscription.CHANGE
        builder.button(text=_("subscription:button:change"), callback_data=callback_data)
    builder.button(text=_("subscription:button:activate_promocode"), callback_data=NavSubscription.PROMOCODE)
    builder.adjust(1)
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def purchase_duration_keyboard(devices: int, callback_data: SubscriptionData) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    callback_data.devices = devices

    user_text = "کاربر نامحدود" if devices == 0 else f"{devices} کاربره"

    callback_data.state = NavSubscription.PLAN_ONE_MONTH
    builder.button(text=f"🚀 یک ماهه | {user_text}", callback_data=callback_data.pack())

    callback_data.state = NavSubscription.PLAN_THREE_MONTH
    builder.button(text=f"🚀 سه ماهه | {user_text}", callback_data=callback_data.pack())

    builder.adjust(1)
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def service_purchase_plan_keyboard(plans: list, callback_data: SubscriptionData, custom_period_id: int | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        volume = f"{plan.volume_gb:,}".translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"))
        duration = f"{plan.duration_days:,}".translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"))
        price = f"{plan.price_toman:,}".translate(str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬"))

        button_text = f"🌟 {volume} گیگ | {duration} روزه | {price} تومان"

        builder.button(
            text=button_text,
            callback_data=f"subscription_plan:{plan.id}",
        )
    builder.adjust(1)
    if custom_period_id is not None:
        builder.row(InlineKeyboardButton(text="📦 حجم دلخواه", callback_data=f"subscription_custom:{custom_period_id}"))
    builder.row(back_button(NavSubscription.BUY, text="🔙 تغییر نوع سرویس"))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def managed_payment_method_keyboard(plan_id: int, price_toman: int, gateways: list[PaymentGateway]) -> InlineKeyboardMarkup:
    """Build the managed payment keyboard in the configured customer order."""
    builder = InlineKeyboardBuilder()
    enabled = _enabled_payment_methods()
    gateway_map = {_gateway_callback(gateway): gateway for gateway in gateways}

    # Required customer order: ZarinPal -> card-to-card -> wallet.
    ordered_keys = ["pay_zarinpal", "mp_card", "mp_wallet"]
    ordered_keys.extend(key for key in gateway_map if key not in ordered_keys)

    for key in ordered_keys:
        if key not in enabled:
            continue

        if key == "mp_card":
            builder.row(InlineKeyboardButton(
                text=f"💳 کارت به کارت | {price_toman:,} تومان",
                callback_data=f"mp_card:{plan_id}",
            ))
            continue

        if key == "mp_wallet":
            builder.row(InlineKeyboardButton(
                text=f"💰 کیف پول | {price_toman:,} تومان",
                callback_data=f"mp_wallet:{plan_id}",
            ))
            continue

        gateway = gateway_map.get(key)
        if gateway is None:
            continue

        builder.row(InlineKeyboardButton(
            text=f"{gateway.name} | {price_toman:,} تومان",
            callback_data=f"mp:{key}:{plan_id}",
        ))

    builder.row(InlineKeyboardButton(text="🔙 تغییر سرویس", callback_data=f"subscription_back_plan:{plan_id}"))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def managed_payment_method_keyboard_traffic(
    subscription_id: int,
    plan_id: int,
    price_toman: int,
    gateways: list[PaymentGateway],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    enabled = _enabled_payment_methods()
    gateway_map = {_gateway_callback(gateway): gateway for gateway in gateways}
    ordered_keys = ["pay_zarinpal", "mp_card", "mp_wallet"]
    ordered_keys.extend(key for key in gateway_map if key not in ordered_keys)

    for key in ordered_keys:
        if key not in enabled:
            continue
        if key == "mp_card":
            builder.row(InlineKeyboardButton(
                text=f"💳 کارت به کارت | {price_toman:,} تومان",
                callback_data=f"mp_card:{plan_id}",
            ))
        elif key == "mp_wallet":
            builder.row(InlineKeyboardButton(
                text=f"💰 کیف پول | {price_toman:,} تومان",
                callback_data=f"mp_wallet:{plan_id}",
            ))
        else:
            gateway = gateway_map.get(key)
            if gateway is not None:
                builder.row(InlineKeyboardButton(
                    text=f"{gateway.name} | {price_toman:,} تومان",
                    callback_data=f"mp:{key}:{plan_id}",
                ))

    builder.row(InlineKeyboardButton(text="🔙 تغییر حجم", callback_data=f"traffic:add:{subscription_id}"))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def managed_payment_method_keyboard_renewal(
    plan_id: int,
    price_toman: int,
    gateways: list[PaymentGateway],
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    enabled = _enabled_payment_methods()
    gateway_map = {_gateway_callback(gateway): gateway for gateway in gateways}
    ordered_keys = ["pay_zarinpal", "mp_card", "mp_wallet"]
    ordered_keys.extend(key for key in gateway_map if key not in ordered_keys)

    for key in ordered_keys:
        if key not in enabled:
            continue
        if key == "mp_card":
            builder.row(InlineKeyboardButton(
                text=f"💳 کارت به کارت | {price_toman:,} تومان",
                callback_data=f"mp_card:{plan_id}",
            ))
        elif key == "mp_wallet":
            builder.row(InlineKeyboardButton(
                text=f"💰 کیف پول | {price_toman:,} تومان",
                callback_data=f"mp_wallet:{plan_id}",
            ))
        else:
            gateway = gateway_map.get(key)
            if gateway is not None:
                builder.row(InlineKeyboardButton(
                    text=f"{gateway.name} | {price_toman:,} تومان",
                    callback_data=f"mp:{key}:{plan_id}",
                ))

    builder.row(InlineKeyboardButton(text="🔙 تغییر سرویس", callback_data=f"renewal:service:{plan_id}"))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def devices_keyboard(plans: list[Plan], callback_data: SubscriptionData) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for plan in plans:
        callback_data.devices = plan.devices
        builder.button(text=format_device_count(plan.devices), callback_data=callback_data)
    builder.adjust(2)
    builder.row(back_button(NavSubscription.MAIN))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def duration_keyboard(plan_service: PlanService, callback_data: SubscriptionData, currency: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    durations = plan_service.get_durations()
    currency: Currency = Currency.from_code(currency)
    for duration in durations:
        callback_data.duration = duration
        period = format_subscription_period(duration)
        plan = plan_service.get_plan(callback_data.devices)
        price = plan.get_price(currency=currency, duration=duration)
        builder.button(text=f"{period} | {price} {currency.symbol}", callback_data=callback_data)
    builder.adjust(2)
    if callback_data.is_extend:
        builder.row(back_button(NavSubscription.MAIN))
    else:
        callback_data.state = NavSubscription.PROCESS
        builder.row(back_button(callback_data.pack(), text=_("subscription:button:change_devices")))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def config_name_keyboard(callback_data: SubscriptionData) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()

    builder.button(text="✅ استفاده از نام خودکار", callback_data="subscription_config_name:auto")
    builder.button(text="✏️ وارد کردن نام دلخواه", callback_data="subscription_config_name:custom")

    builder.adjust(1)
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def pay_keyboard(pay_url: str, callback_data: SubscriptionData) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=_("subscription:button:pay"), url=pay_url))
    if callback_data.plan_id:
        builder.row(InlineKeyboardButton(text="🔙 تغییر روش پرداخت", callback_data=f"mp_back:{callback_data.plan_id}"))
    else:
        callback_data.state = NavSubscription.DURATION
        builder.row(back_button(callback_data.pack(), text=_("subscription:button:change_payment_method")))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def payment_method_keyboard(plan: Plan | None, callback_data: SubscriptionData, gateways: list[PaymentGateway], price_override: float | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    enabled = _enabled_payment_methods()
    gateway_map = {_gateway_callback(gateway): gateway for gateway in gateways}
    ordered_keys = ["pay_zarinpal", "mp_card", "mp_wallet"]
    ordered_keys.extend(key for key in gateway_map if key not in ordered_keys)

    for key in ordered_keys:
        if key not in enabled:
            continue

        if key == "mp_card":
            price = price_override
            if price is None and plan is not None:
                price = plan.get_price(currency=Currency.TOMAN, duration=callback_data.duration)
            if price is None:
                continue
            callback_data.state = "mp_card"
            builder.row(InlineKeyboardButton(
                text=f"💳 کارت به کارت | {price} تومان",
                callback_data=f"mp_card:{callback_data.plan_id or 0}",
            ))
            continue

        if key == "mp_wallet":
            price = price_override
            if price is None and plan is not None:
                price = plan.get_price(currency=Currency.TOMAN, duration=callback_data.duration)
            if price is None:
                continue
            callback_data.state = "mp_wallet"
            builder.row(InlineKeyboardButton(
                text=f"💰 کیف پول | {price} تومان",
                callback_data=f"mp_wallet:{callback_data.plan_id or 0}",
            ))
            continue

        gateway = gateway_map.get(key)
        if gateway is None:
            continue
        if price_override is None:
            if plan is None:
                continue
            price = plan.get_price(currency=gateway.currency, duration=callback_data.duration)
        else:
            price = price_override
        if price is None:
            continue
        callback_data.state = gateway.callback
        builder.row(InlineKeyboardButton(
            text=f"{gateway.name} | {price} {gateway.currency.symbol}",
            callback_data=callback_data.pack(),
        ))

    callback_data.state = NavSubscription.DEVICES
    builder.row(back_button(callback_data.pack(), text=_("subscription:button:change_duration")))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def payment_success_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=_("subscription:button:download_app"), callback_data=NavMain.REDIRECT_TO_DOWNLOAD))
    builder.row(close_notification_button())
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def trial_success_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=_("subscription:button:connect"), callback_data=NavDownload.MAIN))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()


def promocode_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(back_button(NavSubscription.MAIN))
    builder.row(back_to_main_menu_button())
    return builder.as_markup()
