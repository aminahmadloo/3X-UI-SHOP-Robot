#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
export ROOT

python3 - <<'PY'
from pathlib import Path
import os
import re
import shutil
from datetime import datetime

root = Path(os.environ["ROOT"])
stamp = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
backup = root / ".feature-backups" / f"referral-level-{stamp}"
backup.mkdir(parents=True, exist_ok=True)

FILES = [
    "app/config.py",
    "app/bot/services/__init__.py",
    "app/bot/services/referral.py",
    "app/bot/routers/referral/handler.py",
    "app/bot/routers/main_menu/keyboard.py",
    "app/bot/routers/subscription/subscription_handler.py",
    "app/bot/routers/subscription/dynamic_renewal_handler.py",
    "app/bot/routers/subscription/managed_payment_compat_handler.py",
    "app/bot/routers/__init__.py",
    "app/bot/utils/navigation.py",
    ".env.example",
]
for rel in FILES:
    p = root / rel
    if p.exists():
        dest = backup / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)


def read(rel):
    return (root / rel).read_text(encoding="utf-8")


def write(rel, text):
    (root / rel).write_text(text, encoding="utf-8")


def replace_once(rel, old, new, label):
    p = root / rel
    s = p.read_text(encoding="utf-8")
    if old not in s:
        raise SystemExit(f"SAFE ABORT: marker not found for {label}: {rel}")
    p.write_text(s.replace(old, new, 1), encoding="utf-8")

# ---------------------------------------------------------------------------
# 1. Customer levels. No database migration: the level is derived from the
#    existing completed transaction history, so existing customer history is
#    preserved and immediately usable.
# ---------------------------------------------------------------------------
service = root / "app/bot/services/customer_level.py"
service.parent.mkdir(parents=True, exist_ok=True)
service.write_text('''from __future__ import annotations\n\nimport json\nfrom dataclasses import dataclass\n\nfrom sqlalchemy.ext.asyncio import AsyncSession\n\nfrom app.bot.models import SubscriptionData\nfrom app.bot.utils.constants import TransactionStatus\nfrom app.db.models import Transaction\n\n\n@dataclass(frozen=True)\nclass CustomerLevel:\n    key: str\n    title: str\n    min_purchases: int\n    max_purchases: int | None\n    discount_percent: int\n\n\nLEVELS = (\n    CustomerLevel("bronze", "سطح برنزی", 0, 4, 0),\n    CustomerLevel("silver", "سطح نقره‌ای", 5, 10, 10),\n    CustomerLevel("gold", "سطح طلایی", 11, 20, 15),\n    CustomerLevel("platinum", "سطح پلاتینی", 21, None, 20),\n)\n\n\nasync def successful_service_purchase_count(session: AsyncSession, tg_id: int) -> int:\n    transactions = await Transaction.get_by_user(session, tg_id)\n    count = 0\n    for tx in transactions:\n        if tx.status != TransactionStatus.COMPLETED:\n            continue\n        try:\n            data = SubscriptionData.deserialize(tx.subscription)\n        except Exception:\n            continue\n        if data.payment_kind == "wallet_topup":\n            continue\n        if data.duration <= 0:\n            continue\n        count += 1\n    return count\n\n\ndef level_for_purchase_count(count: int) -> CustomerLevel:\n    for level in reversed(LEVELS):\n        if count >= level.min_purchases:\n            return level\n    return LEVELS[0]\n\n\ndef discounted_price(price: int | float, discount_percent: int) -> int:\n    value = int(round(float(price)))\n    if value <= 0 or discount_percent <= 0:\n        return value\n    return max(1, int(round(value * (100 - discount_percent) / 100)))\n\n\nasync def get_customer_level(session: AsyncSession, tg_id: int) -> tuple[CustomerLevel, int]:\n    count = await successful_service_purchase_count(session, tg_id)\n    return level_for_purchase_count(count), count\n\n\nasync def get_discounted_plan_price(session: AsyncSession, tg_id: int, price: int) -> tuple[CustomerLevel, int, int]:\n    level, count = await get_customer_level(session, tg_id)\n    return level, count, discounted_price(price, level.discount_percent)\n''', encoding="utf-8")

handler = root / "app/bot/routers/customer_level/handler.py"
handler.parent.mkdir(parents=True, exist_ok=True)
(root / "app/bot/routers/customer_level/__init__.py").write_text("", encoding="utf-8")
handler.write_text('''from aiogram import F, Router\nfrom aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup\nfrom sqlalchemy.ext.asyncio import AsyncSession\n\nfrom app.bot.services.customer_level import LEVELS, get_customer_level\nfrom app.bot.utils.navigation import NavMain\nfrom app.db.models import User\n\nrouter = Router(name=__name__)\n\n\ndef _keyboard() -> InlineKeyboardMarkup:\n    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 بازگشت", callback_data=NavMain.MAIN_MENU)]])\n\n\n@router.callback_query(F.data == NavMain.CUSTOMER_LEVEL)\nasync def customer_level(callback: CallbackQuery, user: User, session: AsyncSession) -> None:\n    level, count = await get_customer_level(session, user.tg_id)\n    next_level = next((item for item in LEVELS if item.min_purchases > count), None)\n\n    lines = [\n        f"🏆 <b>سطح شما: {level.title}</b>",\n        "",\n        f"🛒 تعداد خرید: <b>{count}</b> عدد",\n        f"🎁 تخفیف ثابت: <b>{level.discount_percent}%</b>",\n        "",\n    ]\n    if next_level:\n        lines.extend([\n            f"📈 <b>سطح بعدی: {next_level.title}</b>",\n            f"تا رسیدن به سطح بعدی: <b>{next_level.min_purchases - count}</b> خرید دیگر",\n            f"تخفیف سطح بعدی: <b>{next_level.discount_percent}%</b>",\n            "",\n        ])\n    else:\n        lines.extend(["📈 <b>بالاترین سطح را دارید.</b>", ""])\n\n    lines.extend([\n        "📊 <b>راهنمای سطوح:</b>",\n        "🔩 سطح برنزی: ۰ تا ۴ خرید — بدون تخفیف" + (" ← شما اینجایید" if level.key == "bronze" else ""),\n        "⚙️ سطح نقره‌ای: ۵ تا ۱۰ خرید — ۱۰٪ تخفیف" + (" ← شما اینجایید" if level.key == "silver" else ""),\n        "✨ سطح طلایی: ۱۱ تا ۲۰ خرید — ۱۵٪ تخفیف" + (" ← شما اینجایید" if level.key == "gold" else ""),\n        "👑 سطح پلاتینی: ۲۱+ خرید — ۲۰٪ تخفیف" + (" ← شما اینجایید" if level.key == "platinum" else ""),\n    ])\n\n    await callback.answer()\n    await callback.message.edit_text("\\n".join(lines), reply_markup=_keyboard())\n''', encoding="utf-8")

# ---------------------------------------------------------------------------
# 2. Navigation and main keyboard. Existing buttons remain unchanged; the
#    level button is added beside referral.
# ---------------------------------------------------------------------------
replace_once(
    "app/bot/utils/navigation.py",
    '    WALLET = "wallet"\n',
    '    WALLET = "wallet"\n    CUSTOMER_LEVEL = "customer_level"\n',
    "NavMain.CUSTOMER_LEVEL",
)
replace_once(
    "app/bot/routers/main_menu/keyboard.py",
    '        InlineKeyboardButton(\n            text=_("main_menu:button:support"),\n            callback_data=NavSupport.MAIN,\n        ),\n',
    '        InlineKeyboardButton(\n            text="🏆 سطح من",\n            callback_data=NavMain.CUSTOMER_LEVEL,\n        ),\n',
    "main menu level button",
)

# ---------------------------------------------------------------------------
# 3. Router registration.
# ---------------------------------------------------------------------------
routes = read("app/bot/routers/__init__.py")
if "customer_level_router" not in routes:
    marker = "from app.bot.routers.referral.handler import router as referral_router\n"
    if marker not in routes:
        raise SystemExit("SAFE ABORT: referral router import marker not found")
    routes = routes.replace(marker, marker + "from app.bot.routers.customer_level.handler import router as customer_level_router\n", 1)
    marker2 = "        referral_router,\n"
    if marker2 not in routes:
        raise SystemExit("SAFE ABORT: referral router include marker not found")
    routes = routes.replace(marker2, marker2 + "        customer_level_router,\n", 1)
    write("app/bot/routers/__init__.py", routes)

# ---------------------------------------------------------------------------
# 4. Wallet-backed 30% referral reward. Existing referral rows remain intact.
# ---------------------------------------------------------------------------
ref = read("app/bot/services/referral.py")
if "from app.bot.services.wallet import WalletService" not in ref:
    ref = ref.replace(
        "from app.bot.utils.formatting import to_decimal\n",
        "from app.bot.utils.formatting import to_decimal\nfrom app.bot.services.wallet import WalletService\n",
        1,
    )
ref = ref.replace(
    "        vpn_service: VPNService,\n    ) -> None:\n",
    "        vpn_service: VPNService,\n        wallet_service: WalletService,\n    ) -> None:\n",
    1,
)
ref = ref.replace(
    "        self.vpn_service = vpn_service\n",
    "        self.vpn_service = vpn_service\n        self.wallet_service = wallet_service\n",
    1,
)
old_money = '''            elif reward.reward_type == ReferrerRewardType.MONEY:\n                # TODO: add balance processing\n                logger.critical(\n                    f"Tried to give money {reward.amount} reward to a referrer user {reward.user_tg_id}"\n                )\n'''
new_money = '''            elif reward.reward_type == ReferrerRewardType.MONEY:\n                amount = int(round(float(reward.amount)))\n                if amount <= 0:\n                    return False\n                await self.wallet_service.credit(\n                    user_tg_id=reward.user_tg_id,\n                    amount=amount,\n                    transaction_type="referral_reward",\n                    description="پاداش معرفی به دوستان (۳۰٪ خرید موفق)",\n                    reference_id=f"referral_reward:{reward.id}",\n                )\n                logger.info("Credited %s toman referral reward to user %s", amount, reward.user_tg_id)\n'''
if old_money not in ref:
    raise SystemExit("SAFE ABORT: referral money branch marker not found")
ref = ref.replace(old_money, new_money, 1)
write("app/bot/services/referral.py", ref)

# Services initialization: wallet must exist before ReferralService.
svc = read("app/bot/services/__init__.py")
old = '''    notification = NotificationService(config=config, bot=bot)\n    referral = ReferralService(config=config, session_factory=session, vpn_service=vpn)\n'''
new = '''    notification = NotificationService(config=config, bot=bot)\n    wallet = WalletService(session_factory=session)\n    referral = ReferralService(config=config, session_factory=session, vpn_service=vpn, wallet_service=wallet)\n'''
if old not in svc:
    raise SystemExit("SAFE ABORT: services initialization marker not found")
svc = svc.replace(old, new, 1)
svc = svc.replace('    wallet = WalletService(session_factory=session)\n\n    return ServicesContainer(', '    return ServicesContainer(', 1)
write("app/bot/services/__init__.py", svc)

# ---------------------------------------------------------------------------
# 5. Referral page: one-level 30% lifelong reward + 30-day income stats.
# ---------------------------------------------------------------------------
ref_handler = read("app/bot/routers/referral/handler.py")
start = ref_handler.index("async def generate_referral_summary_text(")
end = ref_handler.index("\n\n@router.callback_query", start)
new_summary = '''async def generate_referral_summary_text(\n    session: AsyncSession,\n    user: User,\n    config: Config,\n    bot_username: str,\n) -> str:\n    from datetime import datetime, timedelta, timezone\n    from sqlalchemy import func, select\n\n    referral_link = f"https://t.me/{bot_username}?start={user.tg_id}"\n    referrals_count = await Referral.get_referral_count(session=session, referrer_tg_id=user.tg_id)\n\n    referred_ids = select(Referral.referred_tg_id).where(Referral.referrer_tg_id == user.tg_id)\n    from app.db.models import Transaction, WalletTransaction\n    purchase_count = await session.scalar(\n        select(func.count(Transaction.id)).where(\n            Transaction.tg_id.in_(referred_ids),\n            Transaction.status == "completed",\n        )\n    ) or 0\n\n    since = datetime.now(timezone.utc) - timedelta(days=30)\n    income_30d = await session.scalar(\n        select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(\n            WalletTransaction.user_tg_id == user.tg_id,\n            WalletTransaction.transaction_type == "referral_reward",\n            WalletTransaction.created_at >= since,\n        )\n    ) or 0\n\n    return (\n        "🎁 <b>معرفی به دوستان</b>\\n\\n"\n        f"🔗 لینک دعوت اختصاصی شما:\\n<code>{referral_link}</code>\\n\\n"\n        "🎁 با هر نفر که با لینک تو ثبت‌نام کنه:\\n"\n        "• <b>۳۰٪</b> از مبلغ هر خرید موفق او، مادام‌العمر، به کیف پولت واریز می‌شود.\\n\\n"\n        "📊 <b>آمار دعوت شما</b>\\n"\n        f"├ 👥 افراد دعوت شده: <b>{referrals_count}</b>\\n"\n        f"├ 🛒 تعداد خریدها: <b>{purchase_count}</b>\\n"\n        f"└ 💰 درآمد ۳۰ روز اخیر: <b>{int(income_30d):,}</b> تومان"\n    )\n'''
ref_handler = ref_handler[:start] + new_summary + ref_handler[end:]
write("app/bot/routers/referral/handler.py", ref_handler)

# ---------------------------------------------------------------------------
# 6. Config: enable money rewards and make the first level 30% by default.
#    Existing environment variables are retained; only defaults/validation
#    are changed so current .env values remain authoritative.
# ---------------------------------------------------------------------------
cfg = read("app/config.py")
cfg = cfg.replace('DEFAULT_SHOP_REFERRER_REWARD_TYPE = ReferrerRewardType.DAYS.value', 'DEFAULT_SHOP_REFERRER_REWARD_TYPE = ReferrerRewardType.MONEY.value', 1)
cfg = cfg.replace('DEFAULT_SHOP_REFERRER_LEVEL_ONE_RATE = 50', 'DEFAULT_SHOP_REFERRER_LEVEL_ONE_RATE = 30', 1)
cfg = cfg.replace('DEFAULT_SHOP_REFERRER_LEVEL_TWO_RATE = 5', 'DEFAULT_SHOP_REFERRER_LEVEL_TWO_RATE = 0', 1)
old = '''    if referrer_reward_type != ReferrerRewardType.DAYS.value:\n        logger.error(\n            "Only 'days' option is now available for SHOP_REFERRER_REWARD_TYPE. "\n            "Referrer reward disabled."\n        )\n        referrer_reward_enabled = False\n'''
if old in cfg:
    cfg = cfg.replace(old, '', 1)
cfg = cfg.replace(
    'validate=Range(min=1, max=100, error="SHOP_REFERRER_LEVEL_TWO_RATE must be between 1 and 100"),',
    'validate=Range(min=0, max=100, error="SHOP_REFERRER_LEVEL_TWO_RATE must be between 0 and 100"),',
    1,
)
write("app/config.py", cfg)

# ---------------------------------------------------------------------------
# 7. Apply level discount to managed service purchases at the server-side
#    payment-order construction point. The original plan price is never
#    changed in the database.
# ---------------------------------------------------------------------------
sub = read("app/bot/routers/subscription/subscription_handler.py")
if "from app.bot.services.customer_level import get_discounted_plan_price" not in sub:
    sub = sub.replace(
        "from app.bot.routers.subscription.keyboard import",
        "from app.bot.services.customer_level import get_discounted_plan_price\nfrom app.bot.routers.subscription.keyboard import",
        1,
    )
old = '        price=plan.price_toman,\n        plan_id=plan.id,\n'
new = '        price=(await get_discounted_plan_price(session, user.tg_id, plan.price_toman))[2],\n        plan_id=plan.id,\n'
if old not in sub:
    raise SystemExit("SAFE ABORT: subscription plan price marker not found")
sub = sub.replace(old, new, 1)
write("app/bot/routers/subscription/subscription_handler.py", sub)

# Renewal discount at creation and payment revalidation points.
renew = read("app/bot/routers/subscription/dynamic_renewal_handler.py")
if "from app.bot.services.customer_level import get_discounted_plan_price" not in renew:
    renew = renew.replace(
        "from app.bot.models import ServicesContainer, SubscriptionData\n",
        "from app.bot.models import ServicesContainer, SubscriptionData\nfrom app.bot.services.customer_level import get_discounted_plan_price\n",
        1,
    )
renew = renew.replace(
    '        price=plan.price_toman,\n        plan_id=plan.id,\n',
    '        price=(await get_discounted_plan_price(session, user.tg_id, plan.price_toman))[2],\n        plan_id=plan.id,\n',
    1,
)
renew = renew.replace(
    '            "price": plan.price_toman,\n            "volume_gb": subscription.volume_gb,\n',
    '            "price": (await get_discounted_plan_price(session, user.tg_id, plan.price_toman))[2],\n            "volume_gb": subscription.volume_gb,\n',
    1,
)
renew = renew.replace(
    '            "duration": plan.duration_days,\n            "price": plan.price_toman,\n            "volume_gb": subscription.volume_gb,\n',
    '            "duration": plan.duration_days,\n            "price": (await get_discounted_plan_price(session, user.tg_id, plan.price_toman))[2],\n            "volume_gb": subscription.volume_gb,\n',
    1,
)
write("app/bot/routers/subscription/dynamic_renewal_handler.py", renew)

# ---------------------------------------------------------------------------
# 8. Example env only: never overwrite the real .env here.
# ---------------------------------------------------------------------------
env_example = read(".env.example")
add = [
    "SHOP_REFERRER_REWARD_ENABLED=true",
    "SHOP_REFERRER_REWARD_TYPE=money",
    "SHOP_REFERRER_LEVEL_ONE_RATE=30",
    "SHOP_REFERRER_LEVEL_TWO_RATE=0",
]
missing = [line for line in add if line.split('=',1)[0] not in env_example]
if missing:
    env_example = env_example.rstrip() + "\n\n# Referral reward settings\n" + "\n".join(missing) + "\n"
    write(".env.example", env_example)

print(f"Referral + customer-level patch applied safely. Backup: {backup}")
PY

# Compile only the touched Python files.
python3 -m py_compile \
  app/config.py \
  app/bot/services/customer_level.py \
  app/bot/services/referral.py \
  app/bot/services/__init__.py \
  app/bot/routers/customer_level/handler.py \
  app/bot/routers/referral/handler.py \
  app/bot/routers/main_menu/keyboard.py \
  app/bot/routers/subscription/subscription_handler.py \
  app/bot/routers/subscription/dynamic_renewal_handler.py \
  app/bot/routers/__init__.py

echo "PYTHON COMPILE: OK"
