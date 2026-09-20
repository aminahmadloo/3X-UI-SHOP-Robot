from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.payment_gateways import GatewayFactory
from app.bot.payment_gateways._gateway import PaymentGateway
from app.bot.routers.admin_tools import payment_gateway_settings_handler as payment_gateway_admin
from app.bot.routers.main_menu import renew_service_handler
from app.bot.routers.subscription import keyboard as subscription_keyboard
from app.bot.routers.subscription import subscription_handler
from app.bot.routers.wallet import gateway_payment as wallet_gateway_payment
from app.bot.routers.wallet import handler as wallet_handler
from app.bot.routers.wallet.handler import has_pending_payment
from app.bot.utils.constants import Currency
from app.bot.utils.navigation import NavAdminTools, NavMain, NavSubscription
from app.db.models import PaymentMethodSettings, User


_ONLINE_GATEWAY_KEYS = {"pay_zarinpal", "pay_winapay"}


_DEFAULTS = {
    "pay_zarinpal": ("🏦 زرین‌پال", 10),
    "mp_card": ("💳 کارت به کارت", 20),
    "mp_wallet": ("💰 کیف پول", 30),
    "pay_aban": ("💳 پرداخت خودکار کارت به کارت", 40),
    "pay_winapay": ("💳 پرداخت در ویناپی", 60),
}


def _gateway_key(gateway: PaymentGateway) -> str:
    value = gateway.callback
    return str(getattr(value, "value", value) or "")


def _db_path() -> Path:
    name = os.getenv("DB_NAME", "bot_database").strip() or "bot_database"
    return Path("/app/data") / f"{name}.sqlite3"


def _method_rows() -> list[tuple[str, bool, int]]:
    try:
        with sqlite3.connect(_db_path(), timeout=2) as db:
            rows = db.execute(
                "SELECT method_key, enabled, sort_order "
                "FROM payment_method_settings ORDER BY sort_order, id"
            ).fetchall()
        if rows:
            return [(str(k), bool(e), int(o)) for k, e, o in rows]
    except (sqlite3.Error, OSError):
        pass
    return [(k, True, order) for k, (_, order) in _DEFAULTS.items()]


def _ordered_keys(gateways: list[PaymentGateway], enabled_only: bool = True) -> list[str]:
    gateway_keys = {_gateway_key(g) for g in gateways}
    known = set(_DEFAULTS) | gateway_keys
    rows = _method_rows()
    result: list[str] = []
    for key, enabled, _ in rows:
        if key in known and (not enabled_only or enabled) and key not in result:
            result.append(key)
    for key in gateway_keys:
        if key not in result and not any(row_key == key for row_key, _, _ in rows):
            result.append(key)
    return result


def _enabled(key: str) -> bool:
    for row_key, enabled, _ in _method_rows():
        if row_key == key:
            return enabled
    return True


def _admin_markup(methods: list[PaymentMethodSettings]) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for i, method in enumerate(methods):
        buttons = [InlineKeyboardButton(
            text=f"{'🟢 نمایش' if method.enabled else '🔴 مخفی'} | {method.display_name}",
            callback_data=f"paymentmethod:toggle:{method.id}",
        )]
        if i > 0:
            buttons.append(InlineKeyboardButton(text="⬆️", callback_data=f"paymentmethod:up:{method.id}"))
        if i < len(methods) - 1:
            buttons.append(InlineKeyboardButton(text="⬇️", callback_data=f"paymentmethod:down:{method.id}"))
        rows.append(buttons)
    rows += [
        [InlineKeyboardButton(text="🔄 تازه‌سازی", callback_data="paymentgateway:methods")],
        [InlineKeyboardButton(text="🔙 تنظیمات درگاه‌ها", callback_data=NavAdminTools.PAYMENT_GATEWAY_SETTINGS)],
        [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavAdminTools.MAIN)],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_methods(callback: CallbackQuery, session: AsyncSession, factory: GatewayFactory) -> None:
    methods = await PaymentMethodSettings.get_manageable(session, factory.get_gateways())
    lines = [
        "👁️ <b>مدیریت نمایش روش‌های پرداخت</b>",
        "",
        "روی خود دکمه هر روش بزنید تا نمایش/مخفی بودن آن تغییر کند.",
        "با دکمه‌های ⬆️ و ⬇️ ترتیب نمایش را مدیریت کنید.",
        "",
    ]
    for i, method in enumerate(methods, 1):
        status = "🟢 نمایش داده می‌شود" if method.enabled else "🔴 مخفی است"
        lines.append(f"{i}️⃣ {method.display_name} — <b>{status}</b>")
    lines += [
        "",
        "💡 درگاه‌های ثبت‌شده جدید به‌صورت خودکار به این فهرست اضافه می‌شوند.",
        "💡 درگاهِ تنظیم‌نشده برای مشتری نمایش داده نمی‌شود، حتی اگر وضعیت نمایش آن فعال باشد.",
    ]
    await callback.message.edit_text("\n".join(lines), reply_markup=_admin_markup(methods))


async def _move(session: AsyncSession, methods: list[PaymentMethodSettings], method_id: int, step: int) -> str | None:
    index = next((i for i, item in enumerate(methods) if item.id == method_id), None)
    if index is None:
        return None
    target = index + step
    if target < 0 or target >= len(methods):
        return "edge"
    methods[index].sort_order, methods[target].sort_order = methods[target].sort_order, methods[index].sort_order
    await session.commit()
    return methods[index].display_name


@payment_gateway_admin.router.callback_query(F.data.regexp(r"^paymentmethod:up:\d+$"), payment_gateway_admin.IsAdmin())
async def payment_method_up(callback: CallbackQuery, session: AsyncSession, gateway_factory: GatewayFactory) -> None:
    methods = await PaymentMethodSettings.get_manageable(session, gateway_factory.get_gateways())
    result = await _move(session, methods, int(callback.data.rsplit(":", 1)[1]), -1)
    if result is None:
        await callback.answer("❌ روش پرداخت پیدا نشد.", show_alert=True); return
    if result == "edge":
        await callback.answer("این روش در بالاترین جایگاه قرار دارد.", show_alert=True); return
    await callback.answer("ترتیب به‌روزرسانی شد.")
    await _show_methods(callback, session, gateway_factory)


@payment_gateway_admin.router.callback_query(F.data.regexp(r"^paymentmethod:down:\d+$"), payment_gateway_admin.IsAdmin())
async def payment_method_down(callback: CallbackQuery, session: AsyncSession, gateway_factory: GatewayFactory) -> None:
    methods = await PaymentMethodSettings.get_manageable(session, gateway_factory.get_gateways())
    result = await _move(session, methods, int(callback.data.rsplit(":", 1)[1]), 1)
    if result is None:
        await callback.answer("❌ روش پرداخت پیدا نشد.", show_alert=True); return
    if result == "edge":
        await callback.answer("این روش در پایین‌ترین جایگاه قرار دارد.", show_alert=True); return
    await callback.answer("ترتیب به‌روزرسانی شد.")
    await _show_methods(callback, session, gateway_factory)


def _online_gateway_label(key: str, gateway: PaymentGateway) -> str:
    if key == "pay_zarinpal":
        return "🏦 درگاه پرداخت آنلاین زرین‌پال"
    if key == "pay_winapay":
        return "💳 درگاه پرداخت آنلاین ویناپی"
    return gateway.name


def _online_keys(gateways: list[PaymentGateway]) -> list[str]:
    return [
        key
        for key in _ordered_keys(gateways)
        if key in _ONLINE_GATEWAY_KEYS
    ]


def _online_button(
    gateways: list[PaymentGateway],
    callback_data: str,
    price: int,
) -> InlineKeyboardButton | None:
    if not _online_keys(gateways):
        return None
    return InlineKeyboardButton(
        text=f"🌐 درگاه پرداخت آنلاین | {price:,} تومان",
        callback_data=callback_data,
    )


def _managed_keyboard(
    plan_id: int,
    price: int,
    gateways: list[PaymentGateway],
    back_callback: str,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    gateway_map = {_gateway_key(g): g for g in gateways}

    online = _online_button(
        gateways,
        f"mp_online:subscription:{plan_id}",
        price,
    )
    if online is not None:
        builder.row(online)

    for key in _ordered_keys(gateways):
        if key in _ONLINE_GATEWAY_KEYS:
            continue
        if key == "mp_card":
            builder.row(
                InlineKeyboardButton(
                    text=f"💳 کارت به کارت | {price:,} تومان",
                    callback_data=f"mp_card:{plan_id}",
                )
            )
        elif key == "mp_wallet":
            builder.row(
                InlineKeyboardButton(
                    text=f"💰 کیف پول | {price:,} تومان",
                    callback_data=f"mp_wallet:{plan_id}",
                )
            )
        elif (gateway := gateway_map.get(key)) is not None:
            builder.row(
                InlineKeyboardButton(
                    text=f"{gateway.name} | {price:,} تومان",
                    callback_data=f"mp:{key}:{plan_id}",
                )
            )

    builder.row(
        InlineKeyboardButton(
            text="◀️ نام کانفیگ",
            callback_data=back_callback,
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🔙 بازگشت به منوی اصلی",
            callback_data=NavMain.MAIN_MENU,
            style="danger",
        )
    )
    return builder.as_markup()


def _payment_keyboard(plan, callback_data, gateways, price_override=None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    gateway_map = {_gateway_key(g): g for g in gateways}
    for key in _ordered_keys(gateways):
        if key in {"mp_card", "mp_wallet"}:
            price = price_override
            if price is None and plan is not None:
                price = plan.get_price(currency=Currency.TOMAN, duration=callback_data.duration)
            if price is None:
                continue
            callback_data.state = key
            label = "💳 کارت به کارت" if key == "mp_card" else "💰 کیف پول"
            builder.row(InlineKeyboardButton(text=f"{label} | {price} تومان", callback_data=f"{key}:{callback_data.plan_id or 0}"))
            continue
        gateway = gateway_map.get(key)
        if gateway is None:
            continue
        price = price_override if price_override is not None else (plan.get_price(currency=gateway.currency, duration=callback_data.duration) if plan else None)
        if price is None:
            continue
        callback_data.state = gateway.callback
        builder.row(InlineKeyboardButton(text=f"{gateway.name} | {price} {gateway.currency.symbol}", callback_data=callback_data.pack()))
    callback_data.state = NavSubscription.DEVICES
    builder.row(InlineKeyboardButton(text="🔙 تغییر مدت", callback_data=callback_data.pack()))
    builder.row(InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU))
    return builder.as_markup()


def _main_renewal(
    subscription_id: int,
    plan_id: int,
    price: int,
    factory: GatewayFactory,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    gateways = factory.get_gateways()
    gateway_map = {_gateway_key(g): g for g in gateways}

    online = _online_button(
        gateways,
        f"main_renewal:online:{subscription_id}:{plan_id}",
        price,
    )
    if online is not None:
        builder.row(online)

    for key in _ordered_keys(gateways):
        if key in _ONLINE_GATEWAY_KEYS:
            continue
        if key == "mp_card":
            builder.row(
                InlineKeyboardButton(
                    text=f"💳 کارت به کارت | {price:,} تومان",
                    callback_data=f"{renew_service_handler.CARD_PREFIX}{subscription_id}:{plan_id}",
                )
            )
        elif key == "mp_wallet":
            builder.row(
                InlineKeyboardButton(
                    text=f"👛 پرداخت از کیف پول | {price:,} تومان",
                    callback_data=f"main_renewal:wallet:{subscription_id}:{plan_id}",
                )
            )
        elif (gateway := gateway_map.get(key)) is not None:
            builder.row(
                InlineKeyboardButton(
                    text=f"{gateway.name} | {price:,} تومان",
                    callback_data=(
                        f"{renew_service_handler.GATEWAY_PREFIX}"
                        f"{subscription_id}:{plan_id}:{key}"
                    ),
                )
            )

    builder.row(
        InlineKeyboardButton(
            text="🔙 تغییر سرویس",
            callback_data=f"{renew_service_handler.SERVICE_CALLBACK_PREFIX}{subscription_id}",
        )
    )
    builder.row(renew_service_handler._home_button())
    return builder.as_markup()


def _renewal_payment_link_keyboard(pay_url: str, subscription_id: int, plan_id: int) -> InlineKeyboardMarkup:
    if "abangateway.ir" in (pay_url or "").lower():
        label = "💳 ادامه پرداخت خودکار کارت به کارت"
    else:
        label = "💳 پرداخت در زرین‌پال"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, url=pay_url)],
            [InlineKeyboardButton(text="🔙 تغییر روش پرداخت", callback_data=f"{renew_service_handler.PAYMENT_METHODS_PREFIX}{subscription_id}:{plan_id}")],
            [renew_service_handler._home_button()],
        ]
    )


def _wallet_gateway_keys() -> list[str]:
    keys = _ordered_keys([], enabled_only=True)
    zarinpal_enabled = os.getenv("SHOP_PAYMENT_ZARINPAL_ENABLED", "").strip().lower() in {"1", "true", "yes", "on"}
    aban_configured = bool(os.getenv("ABAN_GATEWAY_TOKEN", "").strip() and os.getenv("ABAN_GATEWAY_WEBHOOK_SECRET", "").strip())
    if not zarinpal_enabled:
        keys = [k for k in keys if k != "pay_zarinpal"]
    if not aban_configured:
        keys = [k for k in keys if k != "pay_aban"]
    winapay_configured = bool(os.getenv("WINAPAY_MERCHANT_ID", "").strip())
    if not winapay_configured:
        keys = [k for k in keys if k != "pay_winapay"]
    return keys


def _wallet_keyboard(language: str, amount: int) -> InlineKeyboardMarkup:
    if language == "en":
        online_label, card_label, back = "🌐 Online payment gateway", "💳 Card-to-card", "🔙 Back"
    elif language == "ru":
        online_label, card_label, back = "🌐 Онлайн-платёж", "💳 Перевод с карты на карту", "🔙 Назад"
    else:
        online_label, card_label, back = "🌐 درگاه پرداخت آنلاین", "💳 کارت به کارت", "🔙 بازگشت"

    rows: list[list[InlineKeyboardButton]] = []
    keys = _wallet_gateway_keys()
    online_keys = [key for key in keys if key in _ONLINE_GATEWAY_KEYS]

    if online_keys:
        rows.append([
            InlineKeyboardButton(
                text=online_label,
                callback_data=f"wallet:online:{amount}",
            )
        ])

    for key in keys:
        if key in _ONLINE_GATEWAY_KEYS:
            continue
        if key == "mp_card":
            rows.append([
                InlineKeyboardButton(
                    text=card_label,
                    callback_data=f"wallet:method:card:{amount}",
                )
            ])
        elif key == "pay_aban":
            rows.append([
                InlineKeyboardButton(
                    text="💳 پرداخت خودکار کارت به کارت",
                    callback_data=f"wallet:method:gateway:{amount}:pay_aban",
                )
            ])

    rows.append([InlineKeyboardButton(text=back, callback_data=NavMain.WALLET)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _wallet_gateway(callback: CallbackQuery, user: User, session: AsyncSession, state, gateway_factory: GatewayFactory) -> None:
    parts = (callback.data or "").split(":")
    if len(parts) != 5:
        await callback.answer("❌ درخواست پرداخت نامعتبر است.", show_alert=True); return
    amount, key = int(parts[3]), parts[4]
    if amount <= 0 or not _enabled(key):
        await callback.answer("❌ این روش پرداخت در حال حاضر فعال نیست.", show_alert=True); return
    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است.", show_alert=True); return
    try:
        gateway = gateway_factory.get_gateway(key)
        data = SubscriptionData(
            state=NavSubscription.CONFIG_NAME, is_extend=False, is_change=False,
            user_id=user.tg_id, devices=0, duration=0, price=amount, plan_id=0,
            volume_gb=0, config_name="wallet_topup", payment_kind="wallet_topup",
        )
        pay_url = await gateway.create_payment(data)
    except Exception:
        await callback.answer("❌ ایجاد لینک پرداخت شارژ کیف پول انجام نشد. لطفاً دوباره تلاش کنید.", show_alert=True); return
    await callback.answer()
    await callback.message.edit_text(
        "🏦 <b>شارژ کیف پول</b>\n\n"
        f"💰 مبلغ شارژ: <b>{amount:,} تومان</b>\n\nبرای تکمیل پرداخت روی دکمه زیر بزنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 {gateway.name}", url=pay_url)],
            [InlineKeyboardButton(text="🔙 تغییر روش پرداخت", callback_data=NavMain.WALLET)],
        ]),
    )


@subscription_handler.router.callback_query(
    F.data.regexp(r"^mp_online:subscription:\d+$")
)
async def subscription_online_gateway_menu(
    callback: CallbackQuery,
    state: FSMContext,
    gateway_factory: GatewayFactory,
) -> None:
    packed = (await state.get_data()).get("subscription_data")
    if not isinstance(packed, dict):
        await callback.answer("اطلاعات سفارش منقضی شده است. لطفاً دوباره پلن را انتخاب کنید.", show_alert=True)
        return

    details = (
        "🌐 <b>درگاه پرداخت آنلاین</b>\n\n"
        f"📝 نام کانفیگ: <code>{packed.get('config_name', '')}</code>\n"
        f"💾 پلن: <b>{packed.get('volume_gb', 0)}GB | {packed.get('duration', 0)} روز</b>\n"
        f"💰 مبلغ پلن انتخابی: <b>{int(packed.get('original_price', packed.get('price', 0))):,}</b> تومان\n"
        f"🎁 تخفیف {packed.get('discount_level_title') or 'سطح پایه'}: <b>{int(packed.get('discount_percent', 0))}%</b>\n"
        f"💳 مبلغ قابل پرداخت: <b>{int(packed.get('price', 0)):,}</b> تومان\n\n"
        "درگاه پرداخت آنلاین را انتخاب کنید:"
    ).replace(",", ".")

    keys = _online_keys(gateway_factory.get_gateways())
    rows = []
    for key in keys:
        gateway = next((g for g in gateway_factory.get_gateways() if _gateway_key(g) == key), None)
        if gateway is None or not _enabled(key):
            continue
        rows.append([
            InlineKeyboardButton(
                text=f"{_online_gateway_label(key, gateway)} | {int(packed.get('price', 0)):,} تومان".replace(",", "."),
                callback_data=f"mp_online_select:subscription:{key}:{int(packed.get('plan_id', 0))}",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="🔙 تغییر روش پرداخت",
            callback_data=f"mp_back:{int(packed.get('plan_id', 0))}",
        )
    ])
    await callback.answer()
    await callback.message.edit_text(
        details,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@subscription_handler.router.callback_query(
    F.data.regexp(r"^mp_online_select:subscription:pay_[^:]+:\d+$")
)
async def subscription_online_gateway_selected(
    callback: CallbackQuery,
    user: User,
    state: FSMContext,
    gateway_factory: GatewayFactory,
) -> None:
    parts = (callback.data or "").split(":")
    key = parts[2]
    plan_id = int(parts[3])
    packed = (await state.get_data()).get("subscription_data")
    if not isinstance(packed, dict):
        await callback.answer("اطلاعات سفارش منقضی شده است. لطفاً دوباره پلن را انتخاب کنید.", show_alert=True)
        return

    data = SubscriptionData(
        state=NavSubscription.CONFIG_NAME,
        is_extend=packed.get("is_extend", False),
        is_change=packed.get("is_change", False),
        user_id=packed.get("user_id", user.tg_id),
        devices=packed.get("devices", 0),
        duration=packed.get("duration", 0),
        price=packed.get("price", 0),
        original_price=packed.get("original_price", 0),
        discount_percent=packed.get("discount_percent", 0),
        discount_level_title=packed.get("discount_level_title", ""),
        plan_id=plan_id,
        volume_gb=packed.get("volume_gb", 0),
        config_name=packed.get("config_name", ""),
    )

    if data.user_id != user.tg_id:
        await callback.answer("خطا در اطلاعات سفارش.", show_alert=True)
        return

    try:
        gateway = gateway_factory.get_gateway(key)
        pay_url = await gateway.create_payment(data)
    except Exception:
        await callback.answer("❌ ایجاد لینک پرداخت آنلاین انجام نشد. لطفاً دوباره تلاش کنید.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        "🧾 <b>سفارش شما</b>\n\n"
        f"📝 نام کانفیگ: <code>{data.config_name}</code>\n"
        f"💾 حجم: <b>{data.volume_gb} گیگ</b>\n"
        f"📅 مدت: <b>{data.duration} روز</b>\n"
        f"💰 مبلغ قابل پرداخت: <b>{int(data.price):,}</b> تومان".replace(",", ".") +
        "\n\nبرای تکمیل پرداخت روی دکمه زیر بزنید:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 {gateway.name}", url=pay_url)],
            [InlineKeyboardButton(text="🔙 تغییر روش پرداخت", callback_data=f"mp_online:subscription:{plan_id}")],
            [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)],
        ]),
    )


@renew_service_handler.router.callback_query(
    F.data.regexp(r"^main_renewal:online:\d+:\d+$")
)
async def renewal_online_gateway_menu(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services,
    state: FSMContext,
    gateway_factory: GatewayFactory,
) -> None:
    parts = (callback.data or "").split(":")
    subscription_id, plan_id = int(parts[2]), int(parts[3])
    resolved = await renew_service_handler._resolve_renewal_payment_data(
        session, user, subscription_id, plan_id, services
    )
    if resolved is None:
        await callback.answer("❌ سرویس یا پلن اصلی دیگر معتبر نیست.", show_alert=True)
        return
    subscription, plan, data = resolved
    await state.update_data(subscription_data=data.serialize())

    rows = []
    gateway_map = {_gateway_key(g): g for g in gateway_factory.get_gateways()}
    for key in _online_keys(gateway_factory.get_gateways()):
        gateway = gateway_map.get(key)
        if gateway is None or not _enabled(key):
            continue
        rows.append([
            InlineKeyboardButton(
                text=f"{_online_gateway_label(key, gateway)} | {int(data.price):,} تومان".replace(",", "."),
                callback_data=f"main_renewal:online_select:{subscription.id}:{plan.id}:{key}",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="🔙 تغییر روش پرداخت",
            callback_data=f"{renew_service_handler.PAYMENT_METHODS_PREFIX}{subscription.id}:{plan.id}",
        )
    ])
    await callback.answer()
    await callback.message.edit_text(
        "🌐 <b>درگاه پرداخت آنلاین</b>\n\n"
        f"🟢 <b>سرویس:</b> <code>{subscription.config_name}</code>\n"
        f"📦 حجم افزوده: <b>{plan.volume_gb} GB</b>\n"
        f"📅 زمان افزوده: <b>{plan.duration_days} روز</b>\n"
        f"💰 مبلغ پلن: <b>{int(data.original_price):,}</b> تومان\n"
        f"🎁 تخفیف {data.discount_level_title or 'سطح پایه'}: <b>{data.discount_percent}%</b>\n"
        f"💳 مبلغ قابل پرداخت: <b>{int(data.price):,}</b> تومان\n\n"
        "درگاه پرداخت آنلاین را انتخاب کنید:".replace(",", "."),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@renew_service_handler.router.callback_query(
    F.data.regexp(r"^main_renewal:online_select:\d+:\d+:pay_[^:]+$")
)
async def renewal_online_gateway_selected(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    services,
    state: FSMContext,
    gateway_factory: GatewayFactory,
) -> None:
    parts = (callback.data or "").split(":")
    subscription_id, plan_id, key = int(parts[2]), int(parts[3]), parts[4]
    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است.", show_alert=True)
        return
    resolved = await renew_service_handler._resolve_renewal_payment_data(
        session, user, subscription_id, plan_id, services
    )
    if resolved is None:
        await callback.answer("❌ سرویس یا پلن اصلی دیگر معتبر نیست.", show_alert=True)
        return
    subscription, plan, data = resolved
    await state.update_data(subscription_data=data.serialize())
    try:
        gateway = gateway_factory.get_gateway(key)
        pay_url = await gateway.create_payment(data)
    except Exception:
        await callback.answer("❌ ایجاد لینک پرداخت آنلاین تمدید انجام نشد. لطفاً دوباره تلاش کنید.", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "🧾 <b>پرداخت تمدید سرویس</b>\n\n"
        f"🟢 <b>سرویس:</b> <code>{subscription.config_name}</code>\n"
        f"📦 حجم افزوده: <b>{plan.volume_gb} GB</b>\n"
        f"📅 زمان افزوده: <b>{plan.duration_days} روز</b>\n"
        f"💰 مبلغ پلن: <b>{int(data.original_price):,}</b> تومان\n"
        f"🎁 تخفیف {data.discount_level_title or 'سطح پایه'}: <b>{data.discount_percent}%</b>\n"
        f"💳 مبلغ قابل پرداخت: <b>{int(data.price):,}</b> تومان\n\n"
        "برای تکمیل پرداخت روی دکمه زیر بزنید:".replace(",", "."),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 {gateway.name}", url=pay_url)],
            [InlineKeyboardButton(
                text="🔙 تغییر روش پرداخت",
                callback_data=f"main_renewal:online:{subscription.id}:{plan.id}",
            )],
            [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=renew_service_handler.ENTRY_CALLBACK)],
        ]),
    )


@wallet_gateway_payment.router.callback_query(
    F.data.regexp(r"^wallet:online:\d+$")
)
async def wallet_online_gateway_menu(
    callback: CallbackQuery,
    gateway_factory: GatewayFactory,
) -> None:
    # amount is parsed below from callback data to keep the handler independent
    # of FSM state and persistent wallet UI.
    try:
        amount = int((callback.data or "").split(":")[2])
    except (TypeError, ValueError, IndexError):
        await callback.answer("❌ مبلغ شارژ نامعتبر است.", show_alert=True)
        return

    rows = []
    gateway_map = {_gateway_key(g): g for g in gateway_factory.get_gateways()}
    for key in _wallet_gateway_keys():
        if key not in _ONLINE_GATEWAY_KEYS:
            continue
        gateway = gateway_map.get(key)
        if gateway is None or not _enabled(key):
            continue
        rows.append([
            InlineKeyboardButton(
                text=f"{_online_gateway_label(key, gateway)} | {amount:,} تومان".replace(",", "."),
                callback_data=f"wallet:online_select:{amount}:{key}",
            )
        ])
    rows.append([
        InlineKeyboardButton(
            text="🔙 تغییر روش پرداخت",
            callback_data=NavMain.WALLET,
        )
    ])
    await callback.answer()
    await callback.message.edit_text(
        "🌐 <b>درگاه پرداخت آنلاین</b>\n\n"
        f"💰 مبلغ شارژ کیف پول: <b>{amount:,}</b> تومان\n\n"
        "درگاه پرداخت آنلاین را انتخاب کنید:".replace(",", "."),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@wallet_gateway_payment.router.callback_query(
    F.data.regexp(r"^wallet:online_select:\d+:pay_[^:]+$")
)
async def wallet_online_gateway_selected(
    callback: CallbackQuery,
    user: User,
    session: AsyncSession,
    gateway_factory: GatewayFactory,
) -> None:
    parts = (callback.data or "").split(":")
    amount, key = int(parts[2]), parts[3]
    if amount <= 0 or not _enabled(key):
        await callback.answer("❌ این روش پرداخت در حال حاضر فعال نیست.", show_alert=True)
        return
    if await has_pending_payment(session, user.tg_id):
        await callback.answer("⏳ یک درخواست پرداخت شما در حال بررسی است.", show_alert=True)
        return

    try:
        gateway = gateway_factory.get_gateway(key)
        data = SubscriptionData(
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
        pay_url = await gateway.create_payment(data)
    except Exception:
        await callback.answer("❌ ایجاد لینک پرداخت آنلاین شارژ کیف پول انجام نشد. لطفاً دوباره تلاش کنید.", show_alert=True)
        return

    await callback.answer()
    await callback.message.edit_text(
        "🏦 <b>شارژ کیف پول</b>\n\n"
        f"💰 مبلغ شارژ: <b>{amount:,}</b> تومان\n\n"
        "برای تکمیل پرداخت روی دکمه زیر بزنید:".replace(",", "."),
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"💳 {gateway.name}", url=pay_url)],
            [InlineKeyboardButton(text="🔙 تغییر روش پرداخت", callback_data=f"wallet:online:{amount}")],
            [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)],
        ]),
    )


def install() -> None:
    payment_gateway_admin.payment_methods_markup = _admin_markup
    payment_gateway_admin.show_payment_methods = _show_methods
    renew_service_handler._payment_methods_keyboard = _main_renewal
    renew_service_handler._payment_link_keyboard = _renewal_payment_link_keyboard
    subscription_handler.payment_method_keyboard = _payment_keyboard
    subscription_handler.managed_payment_method_keyboard = lambda p, price, gateways: _managed_keyboard(p, price, gateways, f"subscription_back_config_name:{p}")
    subscription_keyboard.payment_method_keyboard = _payment_keyboard
    subscription_keyboard.managed_payment_method_keyboard = lambda p, price, gateways: _managed_keyboard(p, price, gateways, f"subscription_back_config_name:{p}")
    subscription_keyboard.managed_payment_method_keyboard_traffic = lambda sid, p, price, gateways: _managed_keyboard(p, price, gateways, f"traffic:add:{sid}")
    subscription_keyboard.managed_payment_method_keyboard_renewal = lambda p, price, gateways: _managed_keyboard(p, price, gateways, f"renewal:service:{p}")
    wallet_handler.payment_method_keyboard = _wallet_keyboard
    wallet_gateway_payment.router.callback_query(F.data.regexp(r"^wallet:method:gateway:\d+:(?:pay_aban)$"))(_wallet_gateway)


install()
