from __future__ import annotations

from pathlib import Path


PATH = Path("app/bot/routers/my_services/handler.py")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    if not PATH.exists():
        raise SystemExit(f"Missing {PATH}")

    text = PATH.read_text(encoding="utf-8")
    original = text

    text = replace_once(
        text,
        "from sqlalchemy import select\n",
        "from sqlalchemy import delete, select\n",
        "SQLAlchemy import",
    )

    text = replace_once(
        text,
        "    discovered: dict[tuple[int, str], object] = {}\n    changed = False\n",
        "    discovered: dict[tuple[int, str], object] = {}\n"
        "    live_identities_by_server: dict[int, set[str]] = {}\n"
        "    changed = False\n",
        "discovery state",
    )

    text = replace_once(
        text,
        "        logger.info(\n"
        "            \"MY_SERVICES LIVE DISCOVERY | Checking XUI server %s for user tg_id=%s.\",\n"
        "            server.name,\n"
        "            user.tg_id,\n"
        "        )\n\n"
        "        for inbound in inbounds:\n",
        "        logger.info(\n"
        "            \"MY_SERVICES LIVE DISCOVERY | Checking XUI server %s for user tg_id=%s.\",\n"
        "            server.name,\n"
        "            user.tg_id,\n"
        "        )\n\n"
        "        # A successful XUI read is authoritative for this server.\n"
        "        # Track every live client identity for safe orphan cleanup.\n"
        "        live_identities = live_identities_by_server.setdefault(server.id, set())\n\n"
        "        for inbound in inbounds:\n",
        "live identity tracking",
    )

    text = replace_once(
        text,
        "                client_id = str(getattr(client, \"id\", \"\") or \"\").strip()\n"
        "                identity = client_id or client_sub_id or client_email\n",
        "                client_id = str(getattr(client, \"id\", \"\") or \"\").strip()\n"
        "                live_identities.update(\n"
        "                    value\n"
        "                    for value in (client_id, client_sub_id, client_email)\n"
        "                    if value\n"
        "                )\n"
        "                identity = client_id or client_sub_id or client_email\n",
        "live client identities",
    )

    cleanup_old = (
        "    if changed:\n"
        "        await session.commit()\n\n"
        "    result = await session.execute(\n"
        "        select(Subscription)\n"
    )
    cleanup_new = (
        "    # Remove stale DB subscriptions only for servers whose XUI read\n"
        "    # succeeded. An API/connection failure never causes deletion.\n"
        "    for server_id, live_identities in live_identities_by_server.items():\n"
        "        result = await session.execute(\n"
        "            select(Subscription).where(\n"
        "                Subscription.user_id == user.id,\n"
        "                Subscription.server_id == server_id,\n"
        "            )\n"
        "        )\n"
        "        server_subscriptions = list(result.scalars().all())\n"
        "        for subscription in server_subscriptions:\n"
        "            stored_client_id = str(subscription.client_id or \"\").strip()\n"
        "            stored_name = str(subscription.config_name or \"\").strip()\n"
        "            if stored_client_id in live_identities or stored_name in live_identities:\n"
        "                continue\n\n"
        "            logger.warning(\n"
        "                \"MY_SERVICES LIVE DISCOVERY | Removing orphan DB subscription=%s \"\n"
        "                \"client_id=%s name=%s from server_id=%s: client is absent from live XUI.\",\n"
        "                subscription.id,\n"
        "                stored_client_id or \"unknown\",\n"
        "                stored_name or \"unknown\",\n"
        "                server_id,\n"
        "            )\n"
        "            await session.execute(\n"
        "                delete(Subscription).where(Subscription.id == subscription.id)\n"
        "            )\n"
        "            changed = True\n\n"
        "    if changed:\n"
        "        await session.commit()\n\n"
        "    result = await session.execute(\n"
        "        select(Subscription)\n"
    )
    text = replace_once(text, cleanup_old, cleanup_new, "orphan cleanup")

    missing_old = (
        "            client = live_clients.get(stored_client_id)\n"
        "            if client is None:\n"
        "                # Do not delete the DB record when an administrator removes a\n"
        "                # client from 3X-UI. Preserve the purchase/history record and\n"
        "                # mark it inactive so the discrepancy remains recoverable.\n"
        "                if subscription.status != \"inactive\":\n"
        "                    subscription.status = \"inactive\"\n"
        "                    changed = True\n"
        "                logger.warning(\n"
        "                    \"Subscription %s (%s) client %s is missing from XUI server %s; synchronized status=inactive without deleting DB record.\",\n"
        "                    subscription.id,\n"
        "                    subscription.config_name,\n"
        "                    stored_client_id,\n"
        "                    server.name,\n"
        "                )\n"
        "                continue\n"
    )
    missing_new = (
        "            client = live_clients.get(stored_client_id)\n"
        "            if client is None and subscription.config_name:\n"
        "                client = live_clients.get(str(subscription.config_name).strip())\n"
        "            if client is None:\n"
        "                await session.execute(\n"
        "                    delete(Subscription).where(Subscription.id == subscription.id)\n"
        "                )\n"
        "                changed = True\n"
        "                logger.warning(\n"
        "                    \"Subscription %s (%s) client %s is missing from XUI server %s; removed orphan DB record.\",\n"
        "                    subscription.id,\n"
        "                    subscription.config_name,\n"
        "                    stored_client_id,\n"
        "                    server.name,\n"
        "                )\n"
        "                continue\n"
    )
    text = replace_once(text, missing_old, missing_new, "focused sync orphan handling")

    if text.count("subscriptions[:8]") != 2:
        raise RuntimeError(
            f"dashboard truncation: expected 2 subscriptions[:8] occurrences, "
            f"found {text.count('subscriptions[:8]')}"
        )
    text = text.replace("subscriptions[:8]", "subscriptions")

    if text == original:
        raise RuntimeError("No changes were made")

    PATH.write_text(text, encoding="utf-8")
    print(f"Patched {PATH}")


if __name__ == "__main__":
    main()
