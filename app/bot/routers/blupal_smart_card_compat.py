from __future__ import annotations

import os
import sqlite3

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.bot.payment_gateways.blupal_gateway import BluPalGateway
from app.bot.routers import managed_card_payment
from app.bot.routers import blupal_smart_card_payment
from app.bot.routers.subscription import keyboard as subscription_keyboard
from app.bot.utils.navigation import NavMain


_ORIGINAL_BLUPAL_SUCCESS = BluPalGateway.handle_payment_succeeded


async def _blupal_success(self: BluPalGateway, payment_id: str) -> None:
    async with self.session() as db:
        from app.bot.models import SubscriptionData
        from app.db.models import Transaction

        transaction = await Transaction.get_by_id(session=db, payment_id=payment_id)
        if transaction is None:
            raise RuntimeError(f"BluPal transaction {payment_id} was not found")
        data = SubscriptionData.deserialize(transaction.subscription)

    if data.payment_kind == "wallet_topup":
        await self.credit_wallet(payment_id)
        return

    await _ORIGINAL_BLUPAL_SUCCESS(self, payment_id)


BluPalGateway.handle_payment_succeeded = _blupal_success


def _enabled(key: str) -> bool:
    name = os.getenv("DB_NAME", "bot_database").strip() or "bot_database"
    try:
        with sqlite3.connect(f"/app/data/{name}.sqlite3", timeout=2) as db:
            row = db.execute("SELECT enabled FROM payment_method_settings WHERE method_key = ?", (key,)).fetchone()
        return True if row is None else bool(row[0])
    except (sqlite3.Error, OSError):
        return True


def _smart_wallet_available() -> bool:
    aban_configured = bool(os.getenv("ABAN_GATEWAY_TOKEN", "").strip() and os.getenv("ABAN_GATEWAY_WEBHOOK_SECRET", "").strip())
    blupal_configured = bool(os.getenv("BLUPAL_API_KEY", "").strip())
    return (aban_configured and _enabled("pay_aban")) or (blupal_configured and _enabled("pay_blupal"))


def _traffic_keyboard(subscription_id: int, plan_id: int, price_toman: int, gateways) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    if _enabled("mp_card"):
        rows.append([InlineKeyboardButton(text=f"💳 کارت به کارت | {price_toman:,} تومان", callback_data=f"mp_card:{plan_id}")])
    if _enabled("mp_wallet"):
        rows.append([InlineKeyboardButton(text=f"💰 کیف پول | {price_toman:,} تومان", callback_data=f"mp_wallet:{plan_id}")])
    for gateway in gateways:
        key = str(getattr(getattr(gateway, "callback", ""), "value", getattr(gateway, "callback", "")))
        if key in {"pay_aban", "pay_blupal"} or not _enabled(key):
            continue
        rows.append([InlineKeyboardButton(
            text=f"{gateway.name} | {price_toman:,} {gateway.currency.symbol}",
            callback_data=f"mp:{key}:{plan_id}",
        )])
    rows.append([InlineKeyboardButton(text="🔙 تغییر حجم", callback_data=f"traffic:add:{subscription_id}")])
    rows.append([InlineKeyboardButton(text="🏠 منوی اصلی", callback_data=NavMain.MAIN_MENU)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


subscription_keyboard.managed_payment_method_keyboard_traffic = _traffic_keyboard
managed_card_payment.managed_payment_method_keyboard = subscription_keyboard.managed_payment_method_keyboard
managed_card_payment.managed_payment_method_keyboard_renewal = subscription_keyboard.managed_payment_method_keyboard_renewal
blupal_smart_card_payment._wallet_smart_configured_from_env = _smart_wallet_available
