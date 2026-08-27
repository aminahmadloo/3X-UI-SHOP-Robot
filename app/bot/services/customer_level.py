from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.utils.constants import TransactionStatus
from app.db.models import Transaction


@dataclass(frozen=True)
class CustomerLevel:
    key: str
    title: str
    min_purchases: int
    max_purchases: int | None
    discount_percent: int


LEVELS = (
    CustomerLevel("bronze", "سطح پایه", 0, 4, 0),
    CustomerLevel("silver", "سطح برنزی", 5, 10, 10),
    CustomerLevel("gold", "سطح نقره‌ای", 11, 20, 15),
    CustomerLevel("platinum", "سطح طلایی", 21, None, 20),
)


async def successful_service_purchase_count(session: AsyncSession, tg_id: int) -> int:
    transactions = await Transaction.get_by_user(session, tg_id)
    count = 0
    for tx in transactions:
        if tx.status != TransactionStatus.COMPLETED:
            continue
        try:
            data = SubscriptionData.deserialize(tx.subscription)
        except Exception:
            continue
        if data.payment_kind == "wallet_topup":
            continue
        if data.duration <= 0:
            continue
        count += 1
    return count


def level_for_purchase_count(count: int) -> CustomerLevel:
    for level in reversed(LEVELS):
        if count >= level.min_purchases:
            return level
    return LEVELS[0]


def discounted_price(price: int | float, discount_percent: int) -> int:
    value = int(round(float(price)))
    if value <= 0 or discount_percent <= 0:
        return value
    return max(1, int(round(value * (100 - discount_percent) / 100)))


async def get_customer_level(session: AsyncSession, tg_id: int) -> tuple[CustomerLevel, int]:
    count = await successful_service_purchase_count(session, tg_id)
    return level_for_purchase_count(count), count


async def get_discounted_plan_price(session: AsyncSession, tg_id: int, price: int) -> tuple[CustomerLevel, int, int]:
    level, count = await get_customer_level(session, tg_id)
    return level, count, discounted_price(price, level.discount_percent)
