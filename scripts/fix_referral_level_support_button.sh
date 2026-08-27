#!/bin/sh
set -eu

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
python3 - <<'PY'
from pathlib import Path
p = Path("app/bot/routers/main_menu/keyboard.py")
s = p.read_text(encoding="utf-8")
needle = '''        InlineKeyboardButton(\n            text="🏆 سطح من",\n            callback_data=NavMain.CUSTOMER_LEVEL,\n        ),\n    )\n\n    # 6. مدیریت — فقط برای ادمین\n'''
replacement = '''        InlineKeyboardButton(\n            text="🏆 سطح من",\n            callback_data=NavMain.CUSTOMER_LEVEL,\n        ),\n    )\n\n    # 6. پشتیبانی\n    builder.row(\n        InlineKeyboardButton(\n            text=_("main_menu:button:support"),\n            callback_data=NavSupport.MAIN,\n        )\n    )\n\n    # 7. مدیریت — فقط برای ادمین\n'''
if needle in s and 'callback_data=NavSupport.MAIN' not in s[s.index('text="🏆 سطح من"'):]:
    s = s.replace(needle, replacement, 1)
elif 'callback_data=NavSupport.MAIN' not in s:
    raise SystemExit("SAFE ABORT: could not restore support button")
p.write_text(s, encoding="utf-8")
PY
python3 -m py_compile app/bot/routers/main_menu/keyboard.py
