from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from aiogram import F
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.payment_gateways import GatewayFactory
from app.bot.payment_gateways._gateway import PaymentGateway
from app.bot.routers.admin_tools import payment_gateway_settings_handler as payment_gateway_admin
from app.bot.routers.main_menu import renew_service_handler
from app.bot.routers.subscription import subscription_handler
from app.bot.routers.subscription import keyboard as subscription_keyboard
from app.bot.routers.wallet import gateway_payment as wallet_gateway_payment
from app.bot.routers.wallet import handler as wallet_handler
from app.bot.routers.wallet.handler import has_pending_payment
from app.bot.utils.navigation import NavMain, NavSubscription
from app.db.models import PaymentMethodSettings, User


_PAYMENT_METHOD_DEFAULTS = {
    "pay_zarinpal": ("🏦 زرین‌پال", 10),
    "mp_card": ("💳 کارت به کارت", 20),
    "mp_wallet": ("💰 کیف پول", 30),
    "pay_aban": ("💳 پرداخت خودکار کارت به کارت", 40),
}


def _gateway_callback(gateway: PaymentGateway) -> str:
    callback = gateway.callback
    return str(getattr(callback, "value", callback) or "")


def _payment_method_db_path() -> Path:
    db_name = os.getenv("DB_NAME", "bot_database").strip() or "bot_database"
    return Path("/app/data") / f"{db_name}.sqlite3"


def _load_method_rows() -> list[tuple[str, bool, int]]:
    path = _payment_method_db_path()
    try:
        with sqlite3.connect(path, timeout=2) as connection:
            rows = connection.execute(
                "SELECT method_key, enabled, sort_order "
                "FROM payment_method_settings ORDER BY sort_order, id"
            ).fetchall()
        if rows:
            return [(str(key), bool(enabled), int(sort_order)) for key, enabled, sort_order in rows]
    except (sqlite3.Error, OSError):
        pass
    return [(key, True, sort_order) for key, (_, sort_order) in _PAYMENT_METHOD_DEFAULTS.items()]


def _ordered_method_keys(gateways: list[PaymentGateway], enabled_only: bool = True) -> list[str]:
    gateway_keys = {_gateway_callback(gateway) for gateway in gateways}
    rows = _load_method_rows()
    known = set(_PAYMENT_METHOD_DEFAULTS) | gateway_keys
    ordered: list[str] = []

    for key, enabled, _ in rows:
        if key not in known:
            continue
        if enabled_only and not enabled:
            continue
        if key not in ordered:
            ordered.append(key)

    # Keep newly registered gateways manageable even before their row exists.
    for key in gateway_keys:
        if key not in ordered:
            if not enabled_only or key not in {row_key for row_key, _, _ in rows}:
                ordered.append(key)

    return ordered


def _is_method_enabled(method_key: str) -> bool:
    rows = _load_method_rows()
    for key, enabled, _ in rows:
        if key == method_key:
            return enabled
    return True


def _admin_payment_methods_markup(methods: list[PaymentMethodSettings]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index, method in enumerate(methods):
        status = "🟢 نمایش" if method.enabled else "🔴 مخفی"
        toggle = InlineKeyboardButton(
            text=f"{status} | {method.display_name}",
            callback_data=f"paymentmethod:toggle:{method.id}",
        )
        controls: list[InlineKeyboardButton] = []
        if index > 0:
            controls.append(
                InlineKeyboardButton(
                    text="⬆️",
                    callback_data=f"paymentmethod:up:{method.id}",
                )
            )
        if index < len(methods) - 1:
            controls.append(
                InlineKeyboardButton(
                    text="⬇️",
                    callback_data=f"paymentmethod:down:{method.id}",
                )
            )
        if controls:
            rows.append([toggle, *controls])
        else:
            rows.append([toggle])

    rows.append([InlineKeyboardButton(text="🔄 تازه‌سازی", callback_data="paymentgateway:methods")])
    rows.append([InlineKeyboardButton(text="🔙 تنظیمات درگاه‌ها", callback_data="paymentgateway:settings")])
    rows.append([InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_payment_methods(callback: CallbackQuery, session: AsyncSession, gateway_factory: GatewayFactory) -> None:
    methods = await PaymentMethodSettings.get_manageable(session, gateway_factory.get_gateways())
    lines = [
        "👁️ <b>مدیریت نمایش روش‌های پرداخت</b>",
        "",
        "روی خود دکمه هر روش بزنید تا نمایش/مخفی بودن آن تغییر کند.",
        "برای تغییر ترتیب از دکمه‌های ⬆️ و ⬇️ کنار هر روش استفاده کنید.",
        "",
    ]
    for index, method in enumerate(methods, start=1):
        status = "🟢 نمایش داده می‌شود" if method.enabled else "🔴 مخفی است"
        lines.append(f"{index}️⃣ {method.display_name} — <b>{status}</b>")

    lines.extend([
        "",
        "💡 درگاه‌های ثبت‌شده جدید به‌صورت خودکار به این فهرست اضافه می‌شوند.",
        "💡 درگاهِ تنظیم‌نشده برای مشتری نمایش داده نمی‌شود، حتی اگر وضعیت نمایش آن فعال باشد.",
    ])
    await callback.message.edit_text("\n".join(lines), reply_markup=_admin_payment_methods_markup(methods))


async def _swap_method_order(session: AsyncSession, methods: list[PaymentMethodSettings], method_id: int, direction: int) -> str | None:
    index = next((i for i, item in enumerate(methods) if item.id == method_id), None)
    if index is None:
        return None
    target_index = index + direction
    if target_index < 0 or target_index >= len(methods):
        return "edge"

    current = methods[index]
    target = methods[target_index]
    current.sort_order, target.sort_order = target.sort_order, current.sort_order
    await session.commit()
    return current.display_name


async def _build_payment_method_keyboard(
    plan,
    callback_data,
    gateways,
    price_override=None,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    gateway_map = {_gateway_callback(gateway): gateway for gateway in gateways}
    ordered_keys = _ordered_method_keys(gateways)

    for key in ordered_keys:
        if key == "mp_card":
            price = price_override
            if price is None and plan is not None:
                price = plan.get_price(currency=subscription_keyboard.Currency.TOMAN, duration=callback_data.duration)
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
                price = plan.get_price(currency=subscription_keyboard.Currency.TOMAN, duration=callback_data.duration)
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
    builder.row(InlineKeyboardButton(text="🔙 تغییر مدت", callback_data=callback_data.pack()))
    builder.row(InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="main_menu"))
    return builder.as_markup()


def _build_managed_payment_keyboard(plan_id: int, price_toman: int, gateways: list[PaymentGateway], back_callback: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    gateway_map = {_gateway_callback(gateway): gateway for gateway in gateways}

    for key in _ordered_method_keys(gateways):
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

    builder.row(InlineKeyboardButton(text="🔙", callback_data=back_callback))
    builder.row(InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="main_menu"))
    return builder.as_markup()


def build_main_renewal_payment_keyboard(subscription_id: int, plan_id: int, price: int, gateway_factory: GatewayFactory) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    gateways = gateway_factory.get_gateways()
    gateway_map = {_gateway_callback(gateway): gateway for gateway in gateways}

    for key in _ordered_method_keys(gateways):
        if key == "mp_card":
            builder.row(InlineKeyboardButton(
                text=f"💳 کارت به کارت | {price:,} تومان",
                callback_data=f"{renew_service_handler.CARD_PREFIX}{subscription_id}:{plan_id}",
            ))
        elif key == "mp_wallet":
            builder.row(InlineKeyboardButton(
                text=f"👛 پرداخت از کیف پول | {price:,} تومان",
                callback_data=f"main_renewal:wallet:{subscription_id}:{plan_id}",
            ))
        else:
            gateway = gateway_map.get(key)
            if gateway is not None:
                builder.row(InlineKeyboardButton(
                    text=f"{gateway.name} | {price:,} تومان",
                    callback_data=f"{renew_service_handler.GATEWAY_PREFIX}{subscription_id}:{plan_id}:{key}",
                ))

    builder.row(InlineKeyboardButton(
        text="🔙 تغییر سرویس",
        callback_data=f"{renew_service_handler.SERVICE_CALLBACK_PREFIX}{subscription_id}",
    ))
    builder.row(renew_service_handler._home_button())
    return builder.as_markup()


def _build_wallet_payment_method_keyboard(language: str, amount: int) -> InlineKeyboardMarkup:
    labels = {
        "en": ("🏦 Bank gateway", "💳 Card-to-card", "🔙 Back"),
        "ru": ("🏦 Банковский шлюз", "💳 Перевод с карты на карту", "🔙 Назад"),
        "fa": ("🏦 درگاه بانکی", "💳 کارت به کارت", "🔙 بازگشت"),
    }
    gateway_label, card_label, back_label = labels.get(language, labels["fa"])
    rows: list[list[InlineKeyboardButton]] = []

    # Wallet top-up uses the exact same visibility/order policy as service payments.
    for key in _ordered_method_keys(wallet_gateway_payment._gateway_factory.get_gateways() if hasattr(wallet_gateway_payment, "_gateway_factory") else []):
        if key == "pay_zarinpal":
            rows.append([InlineKeyboardButton(text=gateway_label, callback_data=f"wallet:method:gateway:{amount}:pay_zarinpal")])
        elif key == "mp_card":
            rows.append([InlineKeyboardButton(text=card_label, callback_data=f"wallet:method:card:{amount}")])
        elif key == "pay_aban":
            rows.append([InlineKeyboardButton(text="💳 پرداخت خودکار کارت به کارت", callback_data=f"wallet:method:gateway:{amount}:pay_aban")])

    rows.append([InlineKeyboardButton(text=back_label, callback_data=NavMain.WALLET)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@payment_gateway_admin.router.callback_query(F.data.regexp(r"^paymentmethod:up:\d+$"), payment_gateway_admin.IsAdmin())
async def move_payment_method_up(callback: CallbackQuery, session: AsyncSession, gateway_factory: GatewayFactory) -> None:
    method_id = int(callback.data.rsplit(":", 1)[1])
    methods = await PaymentMethodSettings.get_manageable(session, gateway_factory.get_gateways())
    result = await _swap_method_order(session, methods, method_id, -1)
    if result is None:
        await callback.answer("❌ روش پرداخت پیدا نشد.", show_alert=True)
        return
    if result == "edge":
        await callback.answer("این روش در بالاترین جایگاه قرار دارد.", show_alert=True)
        return
    await callback.answer("ترتیب روش‌های پرداخت به‌روزرسانی شد.")
    await _show_payment_methods(callback, session, gateway_factory)


@payment_gateway_admin.router.callback_query(F.data.regexp(r"^paymentmethod:down:\d+$"), payment_gateway_admin.IsAdmin())
async def move_payment_method_down(callback: CallbackQuery, session: AsyncSession, gateway_factory: GatewayFactory) -> None:
    method_id = int(callback.data.rsplit(":", 1)[1])
    methods = await PaymentMethodSettings.get_manageable(session, gateway_factory.get_gateways())
    result = await _swap_method_order(session, methods, method_id, 1)
    if result is None:
        await callback.answer("❌ روش پرداخت پیدا نشد.", show_alert=True)
        return
    if result == "edge":
        await callback.answer("این روش در پایین‌ترین جایگاه قرار دارد.", show_alert=True)
        return
    await callback.answer("ترتیب روش‌های پرداخت به‌روزرسانی شد.")
    await _show_payment_methods(callback, session, gateway_factory)


async def _wallet_gateway_callback(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    state,
    gateway_factory: GatewayFactory,
) -> None:
    data = callback.data or ""
    parts = data.split(":")
    if len(parts) != 5:
        await callback.answer("❌ درخواست پرداخت نامعتبر است.", show_alert=True)
        return

    amount = int(parts[3])
    gateway_key = parts[4]
    if amount <= 0 or not _is_method_enabled(gateway_key):
        await callback.answer("❌ این روش پرداخت در حال حاضر فعال نیست.", show_alert=True)
        return
    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است. لطفاً ابتدا همان درخواست را تعیین تکلیف کنید.", show_alert=True)
        return

    try:
        gateway = gateway_factory.get_gateway(gateway_key)
        payment_data = SubscriptionData(
            state=NavSubscription.CONFIG_NAME,
            is_extend=False,
            is_change=False,
            user_id=user.tg_id,
            devices=0,
            duration=0,
            price=amount,
            plan_id=0,
            volume_gb=0,
            config_name="wallet_topup",
            payment_kind="wallet_topup",
        )
        pay_url = await gateway.create_payment(payment_data)
    except Exception:
        await callback.answer("❌ ایجاد لینک پرداخت شارژ کیف پول انجام نشد. لطفاً دوباره تلاش کنید.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        "🏦 <b>شارژ کیف پول</b>\n\n"
        f"💰 مبلغ شارژ: <b>{amount:,} تومان</b>\n\n"
        "برای تکمیل پرداخت روی دکمه زیر بزنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 {gateway.name}", url=pay_url)],
            [InlineKeyboardButton(text="🔙 تغییر روش پرداخت", callback_data=NavMain.WALLET)],
        ]),
    )


def install() -> None:
    """Apply one persistent visibility/order policy everywhere payment methods are shown."""
    # Admin: the method button itself toggles visibility; arrows manage order.
    payment_gateway_admin.payment_methods_markup = _admin_payment_methods_markup
    payment_gateway_admin.show_payment_methods = _show_payment_methods

    # Service/renewal keyboards use the persisted order rather than a hard-coded order.
    renew_service_handler._payment_methods_keyboard = build_main_renewal_payment_keyboard
    subscription_handler.payment_method_keyboard = _build_payment_method_keyboard
    subscription_keyboard.payment_method_keyboard = _build_payment_method_keyboard
    subscription_keyboard.managed_payment_method_keyboard = lambda plan_id, price_toman, gateways: _build_managed_payment_keyboard(plan_id, price_toman, gateways, f"subscription_back_plan:{plan_id}")
    subscription_keyboard.managed_payment_method_keyboard_traffic = lambda subscription_id, plan_id, price_toman, gateways: _build_managed_payment_keyboard(plan_id, price_toman, gateways, f"traffic:add:{subscription_id}")
    subscription_keyboard.managed_payment_method_keyboard_renewal = lambda plan_id, price_toman, gateways: _build_managed_payment_keyboard(plan_id, price_toman, gateways, f"renewal:service:{plan_id}")

    # Wallet top-up keyboard now respects the same visibility settings.
    wallet_handler.payment_method_keyboard = _build_wallet_payment_method_keyboard
    wallet_gateway_payment.router.callback_query(
        F.data.regexp(r"^wallet:method:gateway:\d+:(?:pay_zarinpal|pay_aban)$")
    )(_wallet_gateway_callback)


install()
