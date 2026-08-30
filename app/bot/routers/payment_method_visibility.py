from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.payment_gateways import GatewayFactory
from app.bot.routers.main_menu import renew_service_handler
from app.bot.routers.subscription import subscription_handler
from app.bot.routers.subscription.keyboard import _enabled_payment_methods
from app.bot.utils.navigation import NavSubscription



def _gateway_callback(gateway) -> str:
    callback = gateway.callback
    return str(getattr(callback, "value", callback) or "")


def build_main_renewal_payment_keyboard(
    subscription_id: int,
    plan_id: int,
    price: int,
    gateway_factory: GatewayFactory,
) -> InlineKeyboardMarkup:
    """Build the main-menu renewal payment keyboard using admin visibility."""
    builder = InlineKeyboardBuilder()
    enabled = _enabled_payment_methods()
    gateways = gateway_factory.get_gateways()
    gateway_map = {_gateway_callback(gateway): gateway for gateway in gateways}

    ordered_keys = ["pay_zarinpal", "mp_card", "mp_wallet"]
    ordered_keys.extend(key for key in gateway_map if key not in ordered_keys)

    for key in ordered_keys:
        if key not in enabled:
            continue

        if key == "mp_card":
            builder.row(InlineKeyboardButton(
                text=f"💳 کارت به کارت | {price:,} تومان",
                callback_data=f"{renew_service_handler.CARD_PREFIX}{subscription_id}:{plan_id}",
            ))
            continue

        if key == "mp_wallet":
            builder.row(InlineKeyboardButton(
                text=f"👛 پرداخت از کیف پول | {price:,} تومان",
                callback_data=f"main_renewal:wallet:{subscription_id}:{plan_id}",
            ))
            continue

        gateway = gateway_map.get(key)
        if gateway is None:
            continue

        builder.row(InlineKeyboardButton(
            text=f"{gateway.name} | {price:,} تومان",
            callback_data=(
                f"{renew_service_handler.GATEWAY_PREFIX}"
                f"{subscription_id}:{plan_id}:{key}"
            ),
        ))

    builder.row(InlineKeyboardButton(
        text="🔙 تغییر سرویس",
        callback_data=f"{renew_service_handler.SERVICE_CALLBACK_PREFIX}{subscription_id}",
    ))
    builder.row(renew_service_handler._home_button())
    return builder.as_markup()


def build_legacy_payment_method_keyboard(
    plan,
    callback_data,
    gateways,
    price_override=None,
) -> InlineKeyboardMarkup:
    """Preserve the legacy payment flow while applying visibility/order."""
    builder = InlineKeyboardBuilder()
    enabled = _enabled_payment_methods()
    gateway_map = {_gateway_callback(gateway): gateway for gateway in gateways}

    ordered_keys = ["pay_zarinpal"]
    ordered_keys.extend(key for key in gateway_map if key != "pay_zarinpal")

    for key in ordered_keys:
        if key not in enabled:
            continue
        gateway = gateway_map.get(key)
        if gateway is None:
            continue

        if price_override is None:
            if plan is None:
                continue
            price = plan.get_price(
                currency=gateway.currency,
                duration=callback_data.duration,
            )
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
    builder.row(InlineKeyboardButton(
        text="🔙 تغییر مدت",
        callback_data=callback_data.pack(),
    ))
    builder.row(InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="main_menu"))
    return builder.as_markup()


def install() -> None:
    """Apply the visibility policy to legacy and main-menu renewal keyboards."""
    renew_service_handler._payment_methods_keyboard = build_main_renewal_payment_keyboard
    subscription_handler.payment_method_keyboard = build_legacy_payment_method_keyboard


install()
