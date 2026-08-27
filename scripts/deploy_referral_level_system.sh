#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

sh "$ROOT/scripts/apply_referral_level_system.sh"
sh "$ROOT/scripts/fix_referral_level_support_button.sh"

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
echo "Existing .env values are not overwritten."
echo "Existing admin/payment-gateway settings are not touched."
