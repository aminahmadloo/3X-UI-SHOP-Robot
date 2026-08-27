from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.utils.constants import TransactionStatus
from app.db.models import CustomerLevelSettings, Transaction


@dataclass(frozen=True)
class CustomerLevel:
    key: str
    title: str
    min_purchases: int
    max_purchases: int | None
    discount_percent: int


LEVEL_DEFINITIONS = (
    ("bronze", "سطح پایه", 0, 4, "base_discount_percent"),
    ("silver", "سطح برنزی", 5, 10, "bronze_discount_percent"),
    ("gold", "سطح نقره‌ای", 11, 20, "silver_discount_percent"),
    ("platinum", "سطح طلایی", 21, None, "gold_discount_percent"),
)

# Backward-compatible defaults for callers that only need the level definitions.
LEVELS = tuple(
    CustomerLevel(key, title, minimum, maximum, default)
    for key, title, minimum, maximum, field, default in (
        ("bronze", "سطح پایه", 0, 4, "base_discount_percent", 0),
        ("silver", "سطح برنزی", 5, 10, "bronze_discount_percent", 10),
        ("gold", "سطح نقره‌ای", 11, 20, "silver_discount_percent", 15),
        ("platinum", "سطح طلایی", 21, None, "gold_discount_percent", 20),
    )
)


async def get_customer_levels(session: AsyncSession) -> tuple[CustomerLevel, ...]:
    settings = await CustomerLevelSettings.get_or_create(session)
    return tuple(
        CustomerLevel(
            key,
            title,
            minimum,
            maximum,
            max(0, min(100, int(getattr(settings, field)))),
        )
        for key, title, minimum, maximum, field in LEVEL_DEFINITIONS
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


def level_for_purchase_count(count: int, levels: tuple[CustomerLevel, ...] = LEVELS) -> CustomerLevel:
    for level in reversed(levels):
        if count >= level.min_purchases:
            return level
    return levels[0]


def discounted_price(price: int | float, discount_percent: int) -> int:
    value = int(round(float(price)))
    discount_percent = max(0, min(100, int(discount_percent)))
    if value <= 0 or discount_percent <= 0:
        return value
    return max(1, int(round(value * (100 - discount_percent) / 100)))


async def get_customer_level(session: AsyncSession, tg_id: int) -> tuple[CustomerLevel, int]:
    count = await successful_service_purchase_count(session, tg_id)
    levels = await get_customer_levels(session)
    return level_for_purchase_count(count, levels), count


async def get_discounted_plan_price(session: AsyncSession, tg_id: int, price: int) -> tuple[CustomerLevel, int, int]:
    level, count = await get_customer_level(session, tg_id)
    return level, count, discounted_price(price, level.discount_percent)
