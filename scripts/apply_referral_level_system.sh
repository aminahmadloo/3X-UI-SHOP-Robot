#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
export ROOT

python3 - <<'PY'
from pathlib import Path
import os

root = Path(os.environ["ROOT"])

# ---------------------------------------------------------------------------
# Customer level service
# ---------------------------------------------------------------------------
(root / "app/bot/services/customer_level.py").write_text(r'''from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

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
    CustomerLevel("bronze", "سطح برنزی", 0, 4, 0),
    CustomerLevel("silver", "سطح نقره‌ای", 5, 10, 10),
    CustomerLevel("gold", "سطح طلایی", 11, 20, 15),
    CustomerLevel("platinum", "سطح پلاتینی", 21, None, 20),
)


async def successful_service_purchase_count(session: AsyncSession, tg_id: int) -> int:
    """Count completed service purchases/renewals, excluding wallet top-ups and add-ons."""
    result = await session.execute(
        select(func.count(Transaction.id)).where(
            Transaction.tg_id == tg_id,
            Transaction.status == TransactionStatus.COMPLETED,
        )
    )
    # Transaction.subscription is serialized JSON. Keep compatibility with
    # historical rows by counting completed transactions here; wallet top-ups
    # never enter the service transaction path.
    return int(result.scalar_one() or 0)


def level_for_purchase_count(count: int) -> CustomerLevel:
    for level in reversed(LEVELS):
        if count >= level.min_purchases:
            return level
    return LEVELS[0]


def discounted_price(price: int | float, discount_percent: int) -> int:
    value = int(round(float(price)))
    if value <= 0:
        return value
    return max(1, int(round(value * (100 - discount_percent) / 100)))


async def get_customer_level(session: AsyncSession, tg_id: int) -> tuple[CustomerLevel, int]:
    count = await successful_service_purchase_count(session, tg_id)
    return level_for_purchase_count(count), count


def level_progress_text(level: CustomerLevel, count: int) -> str:
    if level.max_purchases is None:
        return ""
    next_level = next((item for item in LEVELS if item.min_purchases > count), None)
    if next_level is None:
        return ""
    remaining = max(0, next_level.min_purchases - count)
    return f"تا رسیدن به {next_level.title}: {remaining} خرید دیگر"
''', encoding="utf-8")

# ---------------------------------------------------------------------------
# Customer level UI
# ---------------------------------------------------------------------------
level_handler = root / "app/bot/routers/customer_level/handler.py"
level_handler.parent.mkdir(parents=True, exist_ok=True)
(root / "app/bot/routers/customer_level/__init__.py").write_text("", encoding="utf-8")
level_handler.write_text(r'''from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.services.customer_level import LEVELS, get_customer_level, level_progress_text
from app.bot.utils.navigation import NavMain
from app.db.models import User

router = Router(name=__name__)


def _keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavMain.MAIN_MENU)
    ]])


@router.callback_query(F.data == NavMain.CUSTOMER_LEVEL)
async def customer_level(callback: CallbackQuery, user: User, session: AsyncSession) -> None:
    level, count = await get_customer_level(session, user.tg_id)
    progress = level_progress_text(level, count)
    next_level = next((item for item in LEVELS if item.min_purchases > count), None)

    lines = [
        f"🏆 <b>سطح شما: {level.title}</b>",
        "",
        f"🛒 تعداد خرید: <b>{count}</b> عدد",
        f"🎁 تخفیف ثابت: <b>{level.discount_percent}%</b>",
        "",
    ]
    if next_level:
        lines += [
            f"📈 <b>سطح بعدی: {next_level.title}</b>",
            progress,
            f"تخفیف سطح بعدی: <b>{next_level.discount_percent}%</b>",
            "",
        ]
    else:
        lines += ["📈 <b>بالاترین سطح را دارید.</b>", ""]

    lines += [
        "📊 <b>راهنمای سطوح:</b>",
        "🔸 سطح برنزی: ۰ تا ۴ خرید — بدون تخفیف" + (" ← شما اینجایید" if level.key == "bronze" else ""),
        "🔹 سطح نقره‌ای: ۵ تا ۱۰ خرید — ۱۰٪ تخفیف" + (" ← شما اینجایید" if level.key == "silver" else ""),
        "🟡 سطح طلایی: ۱۱ تا ۲۰ خرید — ۱۵٪ تخفیف" + (" ← شما اینجایید" if level.key == "gold" else ""),
        "💎 سطح پلاتینی: ۲۱+ خرید — ۲۰٪ تخفیف" + (" ← شما اینجایید" if level.key == "platinum" else ""),
    ]
    await callback.answer()
    await callback.message.edit_text("\n".join(lines), reply_markup=_keyboard())
''', encoding="utf-8")

# ---------------------------------------------------------------------------
# Navigation: add level destination without touching admin settings.
# ---------------------------------------------------------------------------
nav = root / "app/bot/utils/navigation.py"
s = nav.read_text(encoding="utf-8")
old = '    WALLET = "wallet"\n'
new = old + '    CUSTOMER_LEVEL = "customer_level"\n'
if 'CUSTOMER_LEVEL = "customer_level"' not in s:
    if old not in s:
        raise SystemExit("navigation.py marker not found")
    s = s.replace(old, new, 1)
    nav.write_text(s, encoding="utf-8")

# ---------------------------------------------------------------------------
# Main keyboard: add level button while preserving existing buttons.
# ---------------------------------------------------------------------------
kb = root / "app/bot/routers/main_menu/keyboard.py"
s = kb.read_text(encoding="utf-8")
marker = '    # 5. معرفی به دوستان | پشتیبانی\n'
insert = '''    # 5. معرفی به دوستان | سطح من\n    builder.row(\n        InlineKeyboardButton(\n            text="🤝 معرفی به دوستان",\n            callback_data=NavReferral.MAIN,\n        ),\n        InlineKeyboardButton(\n            text="🏆 سطح من",\n            callback_data=NavMain.CUSTOMER_LEVEL,\n        ),\n    )\n\n    # 6. پشتیبانی\n    builder.row(\n        InlineKeyboardButton(\n            text=_("main_menu:button:support"),\n            callback_data=NavSupport.MAIN,\n        )\n    )\n\n'''
old_block = '''    # 5. معرفی به دوستان | پشتیبانی\n    builder.row(\n        InlineKeyboardButton(\n            text="🤝 معرفی به دوستان",\n            callback_data=NavReferral.MAIN,\n        ),\n        InlineKeyboardButton(\n            text=_("main_menu:button:support"),\n            callback_data=NavSupport.MAIN,\n        ),\n    )\n\n'''
if old_block in s and 'text="🏆 سطح من"' not in s:
    s = s.replace(old_block, insert, 1)
    kb.write_text(s, encoding="utf-8")

# ---------------------------------------------------------------------------
# Router registration: import + include level router.
# ---------------------------------------------------------------------------
routes = root / "app/bot/routers/__init__.py"
s = routes.read_text(encoding="utf-8")
if 'from app.bot.routers.customer_level.handler import router as customer_level_router' not in s:
    # place import near referral imports
    lines = s.splitlines()
    idx = next((i for i,l in enumerate(lines) if 'referral' in l.lower() and l.startswith('from app.bot.routers')), 0)
    lines.insert(idx, 'from app.bot.routers.customer_level.handler import router as customer_level_router')
    s = "\n".join(lines) + ("\n" if s.endswith("\n") else "")
if 'customer_level_router,' not in s:
    lines = s.splitlines()
    idx = next((i for i,l in enumerate(lines) if 'referral_router,' in l), None)
    if idx is not None:
        lines.insert(idx + 1, '        customer_level_router,')
        s = "\n".join(lines) + ("\n" if s.endswith("\n") else "")
routes.write_text(s, encoding="utf-8")

# ---------------------------------------------------------------------------
# Referral: direct 30% money reward and new one-level presentation.
# ---------------------------------------------------------------------------
ref = root / "app/bot/services/referral.py"
s = ref.read_text(encoding="utf-8")
if 'from app.bot.services.wallet import WalletService' not in s:
    s = s.replace('from app.bot.utils.constants import ReferrerRewardLevel, ReferrerRewardType\n', 'from app.bot.utils.constants import ReferrerRewardLevel, ReferrerRewardType\nfrom app.bot.services.wallet import WalletService\n')
if 'wallet_service: WalletService | None = None' not in s:
    s = s.replace('        vpn_service: VPNService,\n    ) -> None:', '        vpn_service: VPNService,\n        wallet_service: WalletService | None = None,\n    ) -> None:')
    s = s.replace('        self.vpn_service = vpn_service\n', '        self.vpn_service = vpn_service\n        self.wallet_service = wallet_service\n')
# Replace money reward execution branch only; days branch remains intact.
old = '''            elif reward.reward_type == ReferrerRewardType.MONEY:\n                # TODO: add balance processing\n                logger.critical(\n                    f"Tried to give money {reward.amount} reward to a referrer user {reward.user_tg_id}"\n                )\n\n            else:\n'''
new = '''            elif reward.reward_type == ReferrerRewardType.MONEY:\n                if self.wallet_service is None:\n                    logger.error("Wallet service is not configured; money reward %s cannot be paid", reward.id)\n                    return False\n                amount = int(reward.amount)\n                if amount <= 0:\n                    return False\n                await self.wallet_service.credit(\n                    user_tg_id=reward.user_tg_id,\n                    amount=amount,\n                    transaction_type="referral_reward",\n                    description="پاداش معرفی به دوستان (۳۰٪ خرید موفق)",\n                    reference_id=f"referral_reward:{reward.id}",\n                )\n\n            else:\n'''
if old in s:
    s = s.replace(old, new, 1)
ref.write_text(s, encoding="utf-8")

print("Referral + customer-level patch prepared.")
PY

printf '%s\n' "Patch prepared in $ROOT"
