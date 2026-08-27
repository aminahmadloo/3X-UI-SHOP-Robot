#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
export ROOT
cd "$ROOT"

sh "$ROOT/scripts/apply_referral_level_system.sh"
sh "$ROOT/scripts/fix_referral_level_support_button.sh"

python3 - <<'PY'
from pathlib import Path
import os
import re

root = Path(os.environ["ROOT"])

# 1) Wire the existing WalletService into ReferralService without touching
#    any other service registration.
path = root / "app/bot/services/__init__.py"
s = path.read_text(encoding="utf-8")
s = re.sub(
    r'\n    referral = ReferralService\(config=config, session_factory=session, vpn_service=vpn(?:, wallet_service=wallet)?\)\n',
    '\n    wallet = WalletService(session_factory=session)\n    referral = ReferralService(config=config, session_factory=session, vpn_service=vpn, wallet_service=wallet)\n',
    s,
    count=1,
)
lines = []
seen_wallet = False
for line in s.splitlines():
    if line.strip() == 'wallet = WalletService(session_factory=session)':
        if seen_wallet:
            continue
        seen_wallet = True
    lines.append(line)
s = '\n'.join(lines) + '\n'
if not seen_wallet or 'wallet_service=wallet' not in s:
    raise SystemExit('SAFE ABORT: WalletService/ReferralService wiring failed')
path.write_text(s, encoding='utf-8')

# 2) Enable the requested one-level money referral model. Correct the existing
#    environment-variable typo and keep all unrelated settings untouched.
path = root / "app/config.py"
s = path.read_text(encoding="utf-8")
s = s.replace('env.str("SHOP_REFERRED_REWARD_TYPE",', 'env.str("SHOP_REFERRER_REWARD_TYPE",', 1)
s = s.replace('DEFAULT_SHOP_REFERRER_REWARD_TYPE = ReferrerRewardType.DAYS.value', 'DEFAULT_SHOP_REFERRER_REWARD_TYPE = ReferrerRewardType.MONEY.value', 1)
s = s.replace('DEFAULT_SHOP_REFERRER_LEVEL_ONE_RATE = 50', 'DEFAULT_SHOP_REFERRER_LEVEL_ONE_RATE = 30', 1)
s = s.replace('DEFAULT_SHOP_REFERRER_LEVEL_TWO_RATE = 5', 'DEFAULT_SHOP_REFERRER_LEVEL_TWO_RATE = 0', 1)
old_guard = '''    if referrer_reward_type != ReferrerRewardType.DAYS.value:\n        logger.error(\n            "Only 'days' option is now available for SHOP_REFERRER_REWARD_TYPE. "\n            "Referrer reward disabled."\n        )\n        referrer_reward_enabled = False\n'''
s = s.replace(old_guard, '', 1)
s = s.replace(
    'validate=Range(min=1, max=100, error="SHOP_REFERRER_LEVEL_TWO_RATE must be between 1 and 100"),',
    'validate=Range(min=0, max=100, error="SHOP_REFERRER_LEVEL_TWO_RATE must be between 0 and 100"),',
    1,
)
path.write_text(s, encoding="utf-8")

# 3) Make the referral page match the requested one-level model and count
#    purchases rather than wallet top-ups.
path = root / "app/bot/routers/referral/handler.py"
s = path.read_text(encoding="utf-8")
start = s.index('async def generate_referral_summary_text(')
end = s.index('\n\n@router.callback_query', start)
summary = '''async def generate_referral_summary_text(\n    session: AsyncSession,\n    user: User,\n    config: Config,\n    bot_username: str,\n) -> str:\n    from datetime import datetime, timedelta, timezone\n    from sqlalchemy import func, select\n\n    referral_link = f"https://t.me/{bot_username}?start=ref_{user.tg_id}"\n    referrals_count = await Referral.get_referral_count(\n        session=session, referrer_tg_id=user.tg_id\n    )\n\n    referred_ids = select(Referral.referred_tg_id).where(\n        Referral.referrer_tg_id == user.tg_id\n    )\n    from app.bot.models import SubscriptionData\n    from app.db.models import Transaction, WalletTransaction\n\n    result = await session.execute(\n        select(Transaction).where(\n            Transaction.tg_id.in_(referred_ids),\n            Transaction.status == "completed",\n        )\n    )\n    purchase_count = 0\n    for tx in result.scalars().all():\n        try:\n            data = SubscriptionData.deserialize(tx.subscription)\n        except Exception:\n            continue\n        if data.payment_kind == "wallet_topup":\n            continue\n        if data.duration > 0:\n            purchase_count += 1\n\n    since = datetime.now(timezone.utc) - timedelta(days=30)\n    income_30d = await session.scalar(\n        select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(\n            WalletTransaction.user_tg_id == user.tg_id,\n            WalletTransaction.transaction_type == "referral_reward",\n            WalletTransaction.created_at >= since,\n        )\n    ) or 0\n\n    return (\n        "🎁 <b>معرفی به دوستان</b>\\n\\n"\n        f"🔗 لینک دعوت اختصاصی شما:\\n<code>{referral_link}</code>\\n\\n"\n        "🎁 با هر نفر که با لینک تو ثبت‌نام کنه:\\n"\n        "• <b>۳۰٪</b> از مبلغ هر خرید موفقش به کیف پولت واریز می‌شود (مادام‌العمر).\\n\\n"\n        "📊 <b>آمار دعوت شما</b>\\n"\n        f"├ 👥 افراد دعوت شده: <b>{referrals_count}</b>\\n"\n        f"├ 🛒 تعداد خریدها: <b>{purchase_count}</b>\\n"\n        f"└ 💰 درآمد ۳۰ روز اخیر: <b>{int(income_30d):,}</b> تومان"\n    )\n'''
s = s[:start] + summary + s[end:]
path.write_text(s, encoding="utf-8")

# 4) Update only referral-related keys in the real .env, if it exists.
#    Every other line, including admin and payment-gateway values, remains.
env = root / ".env"
if env.exists():
    text = env.read_text(encoding="utf-8")
    values = {
        "SHOP_REFERRER_REWARD_ENABLED": "true",
        "SHOP_REFERRER_REWARD_TYPE": "money",
        "SHOP_REFERRER_LEVEL_ONE_RATE": "30",
        "SHOP_REFERRER_LEVEL_TWO_RATE": "0",
    }
    for key, value in values.items():
        pattern = re.compile(rf'(?m)^{re.escape(key)}=.*$')
        replacement = f"{key}={value}"
        if pattern.search(text):
            text = pattern.sub(replacement, text, count=1)
        else:
            text = text.rstrip() + f"\n{replacement}\n"
    env.write_text(text, encoding="utf-8")
    print("Updated only referral keys in .env")
else:
    print("No .env in repo root; no environment file changed")
PY

python3 -m py_compile \
  "$ROOT/app/config.py" \
  "$ROOT/app/bot/services/customer_level.py" \
  "$ROOT/app/bot/services/referral.py" \
  "$ROOT/app/bot/services/__init__.py" \
  "$ROOT/app/bot/routers/customer_level/handler.py" \
  "$ROOT/app/bot/routers/referral/handler.py" \
  "$ROOT/app/bot/routers/main_menu/keyboard.py" \
  "$ROOT/app/bot/routers/subscription/subscription_handler.py" \
  "$ROOT/app/bot/routers/subscription/dynamic_renewal_handler.py" \
  "$ROOT/app/bot/routers/__init__.py"

echo "=================================================="
echo "REFERRAL + CUSTOMER LEVEL PATCH: READY"
echo "=================================================="
echo "No database migration is required."
echo "Existing database rows are preserved."
echo "Existing admin/payment-gateway code is not replaced."
echo "Only referral-related .env keys are changed."
