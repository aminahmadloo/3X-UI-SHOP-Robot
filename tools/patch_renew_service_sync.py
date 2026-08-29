#!/usr/bin/env python3
"""Safely remove the artificial 8-service limit from Main Menu -> Renew Service.

The renew entry point already calls _sync_subscriptions_with_xui(), which is the
same live 3X-UI synchronization used by My Services. The remaining mismatch is
only the keyboard builder truncating the synchronized list with subscriptions[:8].

This patch is deliberately narrow and idempotent: it changes exactly one
occurrence in the expected function and refuses to modify an unexpected file.
"""

from pathlib import Path

TARGET = Path("app/bot/routers/main_menu/renew_service_handler.py")
OLD = "    for subscription in subscriptions[:8]:\n"
NEW = "    for subscription in subscriptions:\n"


def main() -> None:
    if not TARGET.is_file():
        raise SystemExit(f"ERROR: target file not found: {TARGET}")

    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD)

    if count == 0:
        if "subscriptions[:8]" not in text:
            print("Already patched: no subscriptions[:8] limit found.")
            return
        raise SystemExit(
            "ERROR: subscriptions[:8] exists, but the expected exact line was not found; refusing to patch."
        )

    if count != 1:
        raise SystemExit(
            f"ERROR: expected exactly 1 renew keyboard limit, found {count}; refusing to patch."
        )

    updated = text.replace(OLD, NEW, 1)
    TARGET.write_text(updated, encoding="utf-8")
    print(f"Patched {TARGET}: removed the 8-service Renew Service limit.")


if __name__ == "__main__":
    main()
