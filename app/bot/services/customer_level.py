from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.models import SubscriptionData
from app.bot.utils.constants import TransactionStatus
from app.db.models import CustomerLevelSettings, Referral, Transaction


@dataclass(frozen=True)
class CustomerLevel:
    key: str
    title: str
    min_points: int
    max_points: int | None
    discount_percent: int


LEVEL_DEFINITIONS = (
    ("base", "سطح پایه", "base_min_points", "base_max_points", "base_discount_percent"),
    ("bronze", "سطح برنزی", "bronze_min_points", "bronze_max_points", "bronze_discount_percent"),
    ("silver", "سطح نقره‌ای", "silver_min_points", "silver_max_points", "silver_discount_percent"),
    ("gold", "سطح طلایی", "gold_min_points", "gold_max_points", "gold_discount_percent"),
)


def _default_level(key: str, title: str, minimum: int, maximum: int | None, discount: int) -> CustomerLevel:
    return CustomerLevel(key, title, minimum, maximum, discount)


# Fallback values used only by pure helpers/tests when no DB settings are supplied.
LEVELS = (
    _default_level("base", "سطح پایه", 0, 4, 0),
    _default_level("bronze", "سطح برنزی", 5, 10, 10),
    _default_level("silver", "سطح نقره‌ای", 11, 20, 15),
    _default_level("gold", "سطح طلایی", 21, None, 20),
)


async def get_customer_levels(session: AsyncSession) -> tuple[CustomerLevel, ...]:
    settings = await CustomerLevelSettings.get_or_create(session)
    return tuple(
        CustomerLevel(
            key,
            title,
            int(getattr(settings, min_field)),
            getattr(settings, max_field),
            max(0, min(100, int(getattr(settings, discount_field)))),
        )
        for key, title, min_field, max_field, discount_field in LEVEL_DEFINITIONS
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


async def successful_referral_count(session: AsyncSession, tg_id: int) -> int:
    """Count referred users who have completed at least one successful service purchase."""
    result = await session.execute(
        select(Referral.referred_tg_id).where(Referral.referrer_tg_id == tg_id)
    )
    referred_ids = set(result.scalars().all())
    count = 0
    for referred_tg_id in referred_ids:
        if await successful_service_purchase_count(session, referred_tg_id) > 0:
            count += 1
    return count


async def get_customer_points(session: AsyncSession, tg_id: int) -> tuple[int, int, int]:
    """Return total points, successful purchase points and successful referral points."""
    purchases = await successful_service_purchase_count(session, tg_id)
    referrals = await successful_referral_count(session, tg_id)
    return purchases + referrals, purchases, referrals


def level_for_points(points: int, levels: tuple[CustomerLevel, ...] = LEVELS) -> CustomerLevel:
    for level in levels:
        if points < level.min_points:
            continue
        if level.max_points is None or points <= level.max_points:
            return level

    # Defensive fallback for an invalid/gapped configuration: use the highest
    # level whose lower bound has been reached.
    eligible = [level for level in levels if points >= level.min_points]
    return eligible[-1] if eligible else levels[0]


async def get_customer_level(session: AsyncSession, tg_id: int) -> tuple[CustomerLevel, int]:
    points, _, _ = await get_customer_points(session, tg_id)
    levels = await get_customer_levels(session)
    return level_for_points(points, levels), points


def discounted_price(price: int | float, discount_percent: int) -> int:
    value = int(round(float(price)))
    discount_percent = max(0, min(100, int(discount_percent)))
    if value <= 0 or discount_percent <= 0:
        return value
    return max(1, int(round(value * (100 - discount_percent) / 100)))


async def get_discounted_plan_price(session: AsyncSession, tg_id: int, price: int) -> tuple[CustomerLevel, int, int]:
    level, points = await get_customer_level(session, tg_id)
    return level, points, discounted_price(price, level.discount_percent)
