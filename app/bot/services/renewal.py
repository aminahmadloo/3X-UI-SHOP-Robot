from __future__ import annotations

from datetime import datetime, timezone

from py3xui import Client
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.bot.models import ServicesContainer
from app.bot.utils.time import add_days_to_timestamp, get_current_timestamp
from app.db.models import Server, ServicePurchasePlan, Subscription, User

TRAFFIC_ADDON_TYPE = "traffic_addon"
TRAFFIC_ADDON_PREFIX = "traffic_addon_"
BYTES_PER_GB = 1024**3


def is_traffic_addon_type(service_type: str | None) -> bool:
    return service_type == TRAFFIC_ADDON_TYPE or bool(service_type and service_type.startswith(TRAFFIC_ADDON_PREFIX))


async def extend_existing_subscription(
    services: ServicesContainer,
    user: User,
    subscription_id: int,
    duration_days: int,
    plan_id: int | None = None,
) -> bool:
    """Extend an existing subscription without changing its original plan identity."""

    if duration_days <= 0:
        return False

    async with services.vpn.session() as session:
        result = await session.execute(
            select(Subscription)
            .join(Server, Subscription.server_id == Server.id)
            .options(selectinload(Subscription.server))
            .where(
                Subscription.id == subscription_id,
                Subscription.user_id == user.id,
                Subscription.server_id.is_not(None),
            )
        )
        subscription = result.scalar_one_or_none()

        if not subscription or not subscription.server or not subscription.client_id:
            return False

        plan = await ServicePurchasePlan.get(session, plan_id) if plan_id is not None else None
        if not plan:
            return False

        connection = await services.server_pool.get_connection_for_server(subscription.server)
        if connection is None:
            return False

        try:
            inbounds = await connection.api.inbound.get_list()
        except Exception:
            return False

        target = None
        target_client_id = str(subscription.client_id).strip()
        for inbound in inbounds:
            for client in inbound.settings.clients or []:
                if (
                    str(client.id or "").strip() == target_client_id
                    or str(client.sub_id or "").strip() == target_client_id
                ):
                    target = client
                    break
            if target:
                break

        if target is None:
            return False

        client = target
        client.enable = True
        client.id = client.id or target_client_id
        client.sub_id = client.sub_id or target_client_id
        client.tg_id = user.tg_id

        now_ms = get_current_timestamp()
        current_expiry_ms = int(client.expiry_time or 0)
        base_expiry_ms = max(current_expiry_ms, now_ms)
        new_expiry_ms = add_days_to_timestamp(base_expiry_ms, duration_days)
        client.expiry_time = new_expiry_ms

        if plan.volume_gb > 0:
            subscription.volume_gb += plan.volume_gb
            current_total_bytes = int(client.total_gb or 0)
            client.total_gb = current_total_bytes + plan.volume_gb * BYTES_PER_GB

        subscription.duration_days += duration_days
        subscription.expire_date = datetime.fromtimestamp(
            new_expiry_ms / 1000,
            tz=timezone.utc,
        ).replace(tzinfo=None)
        subscription.status = "active"

        # IMPORTANT: plan_id is the original purchase plan and must remain immutable.
        # The current renewal/add-on plan is intentionally NOT written back here.

        try:
            await connection.api.client.update(client_uuid=client.id, client=client)
        except Exception:
            return False

        await session.commit()
        return True
