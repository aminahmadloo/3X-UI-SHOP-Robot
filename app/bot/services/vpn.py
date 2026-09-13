from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .server_pool import ServerPoolService

import asyncio
import base64
import copy
import logging
import urllib.request
import uuid

from py3xui import Client, Inbound
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.models import ClientData
from app.bot.services.xui_inbound_adapter import get_inbounds
from app.bot.utils.network import extract_base_url
from app.bot.utils.time import add_days_to_timestamp, days_to_timestamp, get_current_timestamp
from app.config import Config
from app.db.models import Promocode, Server, Subscription, SubscriptionSettings, User

logger = logging.getLogger(__name__)


class VPNService:
    DEFAULT_FLOW = "xtls-rprx-vision"
    BYTES_PER_GB = 1024 ** 3

    def __init__(self, config: Config, session: async_sessionmaker, server_pool_service: ServerPoolService) -> None:
        self.config = config
        self.session = session
        self.server_pool_service = server_pool_service
        logger.info("VPN Service initialized.")

    @classmethod
    def _gb_to_bytes(cls, total_gb: int) -> int:
        """Convert the user-facing traffic quota in GiB to the bytes expected by 3X-UI."""
        if total_gb <= 0:
            return 0
        return int(total_gb) * cls.BYTES_PER_GB

    @staticmethod
    def _build_auto_config_name(volume_gb: int, duration_days: int, tg_id: int, sub_number: int = 101) -> str:
        """Build the standard automatic config/client name."""
        return f"{volume_gb}GB-{duration_days}D-tg{tg_id}-{sub_number}"

    async def _generate_unique_config_name(
        self,
        volume_gb: int,
        duration_days: int,
        tg_id: int,
        connection=None,
    ) -> str:
        """Generate a unique client name across DB subscriptions and XUI clients."""
        existing_names = set()

        async with self.session() as session:
            result = await session.execute(Subscription.__table__.select())
            for row in result.mappings().all():
                if row["config_name"]:
                    existing_names.add(str(row["config_name"]))

        if connection:
            try:
                inbounds = await get_inbounds(connection.api)
                for inbound in inbounds:
                    for client in inbound.settings.clients or []:
                        if client.email:
                            existing_names.add(str(client.email))
            except Exception as exception:
                logger.warning(f"Could not read existing XUI clients while generating name: {exception}")

        number = 1
        while True:
            name = self._build_auto_config_name(
                volume_gb=volume_gb,
                duration_days=duration_days,
                tg_id=tg_id,
                sub_number=number,
            )
            if name not in existing_names:
                return name
            number += 1

    async def generate_custom_config_name(
        self,
        raw_name: str,
        volume_gb: int,
        duration_days: int,
        tg_id: int,
    ) -> str:
        """Generate a custom config name numbered per user/service/custom name.

        The sequence is independent for each Telegram user, service dimensions
        (volume + duration), and exact custom name. Existing subscriptions are
        considered so the sequence continues monotonically.
        """
        prefix = f"{raw_name}-{volume_gb}GB-{duration_days}D-tg{tg_id}-"
        max_number = 0

        async with self.session() as session:
            result = await session.execute(select(Subscription.config_name))
            for (config_name,) in result.all():
                if not config_name:
                    continue
                name = str(config_name)
                if not name.startswith(prefix):
                    continue
                suffix = name[len(prefix):]
                if suffix.isdigit():
                    max_number = max(max_number, int(suffix))

        return f"{prefix}{max_number + 1}"

    async def _find_clients(self, user: User) -> list[tuple[Client, Inbound]]:
        """Find every copy of the user's legacy client across all inbounds."""
        connection = await self.server_pool_service.get_connection(user)
        if not connection:
            return []

        try:
            inbounds: list[Inbound] = await get_inbounds(connection.api)
        except Exception as exception:
            logger.error(f"Failed to fetch inbounds while looking up client {user.tg_id}: {exception}")
            return []

        user_vpn_id = str(user.vpn_id)
        legacy_email = str(user.tg_id)
        matches: list[tuple[Client, Inbound]] = []

        for inbound in inbounds:
            for client in inbound.settings.clients or []:
                if str(client.sub_id or "") == user_vpn_id:
                    matches.append((client, inbound))

        if matches:
            return matches

        for inbound in inbounds:
            for client in inbound.settings.clients or []:
                if str(client.email or "") == legacy_email:
                    matches.append((client, inbound))

        return matches

    async def _find_client(self, user: User) -> tuple[Client, Inbound] | None:
        matches = await self._find_clients(user)
        return matches[0] if matches else None

    is_client_exists_legacy = None

    async def is_client_exists(self, user: User) -> Client | None:
        result = await self._find_client(user)
        if result:
            client, inbound = result
            connection = await self.server_pool_service.get_connection(user)
            server_name = connection.server.name if connection else "unknown"
            logger.debug(f"Client {user.tg_id} exists in inbound {inbound.id} on server {server_name}.")
            return client

        connection = await self.server_pool_service.get_connection(user)
        server_name = connection.server.name if connection else "unknown"
        logger.debug(f"Client {user.tg_id} not found on server {server_name}.")
        return None

    async def get_limit_ip(self, user: User, client: Client) -> int | None:
        result = await self._find_client(user)
        if not result:
            logger.error(f"Client {client.email} not found in inbound list.")
            return None
        inbound_client, _ = result
        logger.debug(f"Client {client.email} limit ip: {inbound_client.limit_ip}")
        return inbound_client.limit_ip

    async def get_client_data(
        self,
        user: User,
        subscription_id: int | None = None,
    ) -> ClientData | None:
        """Return XUI data for one exact subscription.

        When subscription_id is supplied, the lookup is strictly scoped to that
        subscription's server and stored client_id. The legacy user-based lookup
        remains available only for callers that have not yet supplied a subscription.
        """
        logger.debug(
            "Starting to retrieve client data for user %s, subscription=%s.",
            user.tg_id,
            subscription_id,
        )

        target_subscription: Subscription | None = None
        target_client_id: str | None = None

        if subscription_id is not None:
            target_server: Server | None = None

            async with self.session() as session:
                result = await session.execute(
                    select(Subscription)
                    .where(
                        Subscription.id == subscription_id,
                        Subscription.user_id == user.id,
                    )
                )
                target_subscription = result.scalar_one_or_none()

                if target_subscription is None or target_subscription.server_id is None:
                    logger.warning(
                        "Subscription %s for user %s was not found or has no server.",
                        subscription_id,
                        user.tg_id,
                    )
                    return None

                if not target_subscription.client_id:
                    logger.warning(
                        "Subscription %s for user %s has no client_id.",
                        subscription_id,
                        user.tg_id,
                    )
                    return None

                target_client_id = str(target_subscription.client_id).strip()

                server_result = await session.execute(
                    select(Server).where(Server.id == target_subscription.server_id)
                )
                target_server = server_result.scalar_one_or_none()

            if target_server is None:
                logger.warning(
                    "Server %s for subscription %s was not found.",
                    target_subscription.server_id,
                    subscription_id,
                )
                return None

            connection = await self.server_pool_service.get_connection_for_server(
                target_server
            )
        else:
            connection = await self.server_pool_service.get_connection(user)

        if not connection:
            return None

        try:
            inbounds: list[Inbound] = await get_inbounds(connection.api)
            client: Client | None = None
            matched_inbound: Inbound | None = None

            if target_subscription is not None and target_client_id is not None:
                for inbound in inbounds:
                    for inbound_client in inbound.settings.clients or []:
                        if (
                            str(inbound_client.id or "").strip() == target_client_id
                            or str(inbound_client.sub_id or "").strip() == target_client_id
                        ):
                            client = inbound_client
                            matched_inbound = inbound
                            break
                    if client:
                        break
            else:
                for inbound in inbounds:
                    for inbound_client in inbound.settings.clients or []:
                        if str(inbound_client.sub_id or "") == str(user.vpn_id):
                            client = inbound_client
                            matched_inbound = inbound
                            break
                    if client:
                        break

                if not client:
                    for inbound in inbounds:
                        for inbound_client in inbound.settings.clients or []:
                            if str(inbound_client.email or "") == str(user.tg_id):
                                client = inbound_client
                                matched_inbound = inbound
                                break
                        if client:
                            break

            if not client:
                logger.warning(
                    "Client for user %s subscription %s not found on server %s.",
                    user.tg_id,
                    subscription_id,
                    connection.server.name,
                )
                return None

            stats_client: Client | None = None
            for inbound in inbounds:
                for stat in inbound.client_stats or []:
                    if str(stat.email or "") == str(client.email or ""):
                        stats_client = stat
                        break
                if stats_client:
                    break

            source = stats_client or client

            # Normalize all numeric X-UI values before constructing ClientData.
            # py3xui may expose some values as strings depending on the
            # endpoint/response, while ClientData handlers expect integers.
            try:
                limit_ip = int(client.limit_ip or 0)
            except (TypeError, ValueError):
                limit_ip = 0

            max_devices = -1 if limit_ip == 0 else limit_ip

            try:
                traffic_total = int(source.total or 0)
            except (TypeError, ValueError):
                traffic_total = 0

            try:
                traffic_up = int(source.up or 0)
            except (TypeError, ValueError):
                traffic_up = 0

            try:
                traffic_down = int(source.down or 0)
            except (TypeError, ValueError):
                traffic_down = 0

            traffic_used = traffic_up + traffic_down

            if traffic_total <= 0:
                traffic_total = -1
                traffic_remaining = -1
            else:
                traffic_remaining = max(0, traffic_total - traffic_used)

            try:
                raw_expiry_time = int(source.expiry_time or 0)
            except (TypeError, ValueError):
                raw_expiry_time = 0

            expiry_time = -1 if raw_expiry_time == 0 else raw_expiry_time

            client_data = ClientData(
                max_devices=max_devices,
                traffic_total=traffic_total,
                traffic_remaining=traffic_remaining,
                traffic_used=traffic_used,
                traffic_up=traffic_up,
                traffic_down=traffic_down,
                expiry_time=expiry_time,
                client_id=str(client.id or "") or None,
                sub_id=str(client.sub_id or "") or None,
                tg_id=getattr(client, "tg_id", None),
                flow=getattr(client, "flow", None),
                inbound_id=int(matched_inbound.id) if matched_inbound is not None else None,
                config_name=str(client.email or "") or None,
            )
            logger.debug(
                "Successfully retrieved client data for user %s subscription %s: %s",
                user.tg_id,
                subscription_id,
                client_data,
            )
            return client_data
        except Exception as exception:
            logger.error(
                "Error retrieving client data for user %s subscription %s: %s",
                user.tg_id,
                subscription_id,
                exception,
            )
            return None

    async def get_key(self, user: User, subscription_id: int | None = None) -> str | None:
        async with self.session() as session:
            fresh_user = await User.get(session=session, tg_id=user.tg_id)
            if not fresh_user:
                logger.warning(f"User {user.tg_id} not found.")
                return None

            query = (
                select(Subscription)
                .where(
                    Subscription.user_id == fresh_user.id,
                    Subscription.status == "active",
                )
            )
            if subscription_id is not None:
                query = query.where(Subscription.id == subscription_id)
            else:
                query = query.order_by(Subscription.id.desc())

            result = await session.execute(query)
            target = result.scalars().first()

            if not target or not target.client_id:
                logger.warning(
                    "No active subscription/client found for user %s%s",
                    user.tg_id,
                    f" with id {subscription_id}" if subscription_id is not None else "",
                )
                return None

            client_id = str(target.client_id)
            server_host = None

            if target.server_id is not None:
                server_result = await session.execute(
                    select(Server).where(Server.id == target.server_id)
                )
                target_server = server_result.scalar_one_or_none()

                if target_server is not None:
                    server_connection = (
                        await self.server_pool_service.get_connection_for_server(
                            target_server
                        )
                    )
                    if server_connection is not None:
                        server_host = server_connection.server.host

            settings = await SubscriptionSettings.get_or_create(session)
            base_host = settings.domain or server_host or (user.server.host if user.server else None)
            if not base_host:
                logger.warning("No subscription domain/server host available for user %s.", user.tg_id)
                return None

            subscription_base = extract_base_url(
                url=base_host,
                port=settings.port,
                path=settings.path,
            )

        key = f"{subscription_base}{client_id}"
        logger.info(
            "Subscription key generated from subscription %s for user %s.",
            target.id,
            user.tg_id,
        )
        return key

    async def get_active_subscription_keys(
        self,
        user: User,
    ) -> list[tuple[int, str, str]]:
        """Return the user's CURRENT active connection keys directly from 3X-UI.

        3X-UI is the source of truth for this operation.

        The method intentionally does not depend on the local Subscription rows
        to discover the user's keys. Every configured XUI server is queried,
        the live clients are inspected, and the current client.id is used to
        build the subscription key.

        Returned tuples keep the existing profile-handler contract:

            (subscription_id, config_name, connection_key)

        For a live XUI client that has no local Subscription row,
        ``subscription_id`` is returned as 0 because the profile UI only uses
        the name and connection key.
        """
        user_tg_id = str(user.tg_id).strip()
        user_vpn_id = str(user.vpn_id or "").strip()

        async with self.session() as session:
            settings = await SubscriptionSettings.get_or_create(session)

            server_result = await session.execute(
                select(Server).order_by(Server.id.asc())
            )
            servers = list(server_result.scalars().all())

            # Optional local mapping is used only for preserving the familiar
            # service name / subscription id when a matching DB record exists.
            local_subscriptions: dict[tuple[int, str], Subscription] = {}

            subscription_result = await session.execute(
                select(Subscription).where(
                    Subscription.user_id == user.id,
                    Subscription.server_id.is_not(None),
                )
            )

            for subscription in subscription_result.scalars().all():
                client_id = str(subscription.client_id or "").strip()
                if client_id and subscription.server_id is not None:
                    local_subscriptions[
                        (subscription.server_id, client_id)
                    ] = subscription

            keys: list[tuple[int, str, str]] = []
            seen_clients: set[tuple[int, str]] = set()

            for server in servers:
                connection = (
                    await self.server_pool_service.get_connection_for_server(
                        server
                    )
                )

                if connection is None:
                    logger.warning(
                        "PROFILE LIVE KEYS | Cannot connect to XUI server %s.",
                        server.name,
                    )
                    continue

                try:
                    inbounds = await get_inbounds(connection.api)
                except Exception as exception:
                    logger.warning(
                        "PROFILE LIVE KEYS | Failed to read XUI server %s: %s",
                        server.name,
                        exception,
                    )
                    continue

                server_host = None

                try:
                    server_host = connection.server.host
                except Exception:
                    server_host = getattr(server, "host", None)

                base_host = (
                    settings.domain
                    or server_host
                    or (user.server.host if user.server else None)
                )

                if not base_host:
                    logger.warning(
                        "PROFILE LIVE KEYS | No host available for server %s.",
                        server.name,
                    )
                    continue

                subscription_base = extract_base_url(
                    url=base_host,
                    port=settings.port,
                    path=settings.path,
                )

                for inbound in inbounds:
                    for client in inbound.settings.clients or []:
                        client_tg_id = str(
                            getattr(client, "tg_id", "") or ""
                        ).strip()

                        client_sub_id = str(
                            getattr(client, "sub_id", "") or ""
                        ).strip()

                        client_email = str(
                            getattr(client, "email", "") or ""
                        ).strip()

                        is_match = (
                            client_tg_id == user_tg_id
                            or (
                                user_vpn_id
                                and client_sub_id == user_vpn_id
                            )
                            or client_email == user_tg_id
                        )

                        if not is_match:
                            continue

                        # Disabled XUI clients must not be presented as active
                        # connection keys.
                        if not bool(getattr(client, "enable", False)):
                            logger.info(
                                "PROFILE LIVE KEYS | Skipping disabled client "
                                "%s on server %s.",
                                client_email or client.id,
                                server.name,
                            )
                            continue

                        client_id = str(
                            getattr(client, "id", "") or ""
                        ).strip()

                        if not client_id:
                            logger.warning(
                                "PROFILE LIVE KEYS | Matched client without "
                                "client.id on server %s inbound %s.",
                                server.name,
                                inbound.id,
                            )
                            continue

                        unique_key = (server.id, client_id)

                        # The same XUI client can exist in multiple inbounds.
                        if unique_key in seen_clients:
                            continue

                        seen_clients.add(unique_key)

                        local_subscription = local_subscriptions.get(
                            unique_key
                        )

                        if local_subscription is not None:
                            subscription_id = local_subscription.id
                        else:
                            subscription_id = 0

                        config_name = (
                            client_email
                            or str(
                                getattr(client, "name", "") or ""
                            ).strip()
                            or client_id
                        )

                        connection_key = (
                            f"{subscription_base}{client_id}"
                        )

                        keys.append(
                            (
                                subscription_id,
                                config_name,
                                connection_key,
                            )
                        )

                        logger.info(
                            "PROFILE LIVE KEYS | FOUND live client=%s "
                            "name=%s server=%s inbound=%s user=%s.",
                            client_id,
                            config_name,
                            server.name,
                            inbound.id,
                            user.tg_id,
                        )

            logger.info(
                "PROFILE LIVE KEYS | Generated %s live connection keys "
                "directly from XUI for user %s.",
                len(keys),
                user.tg_id,
            )

            return keys

    async def get_subscription_links(
        self,
        user: User,
        subscription_id: int | None = None,
    ) -> list[str]:
        """Return the individual live connection links for one subscription.

        The subscription URL is resolved from the same 3X-UI subscription
        settings used by get_key(). 3X-UI returns the individual protocol
        share links from that subscription endpoint. This keeps My Services
        dynamically synchronized with the live XUI configuration.
        """
        subscription_url = await self.get_key(
            user,
            subscription_id=subscription_id,
        )

        if not subscription_url:
            return []

        def _fetch() -> bytes:
            request = urllib.request.Request(
                subscription_url,
                headers={
                    "Accept": "text/plain, */*;q=0.1",
                    "User-Agent": "ToonelVPN/1.0",
                },
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.read()

        try:
            raw = await asyncio.to_thread(_fetch)
        except Exception as exception:
            logger.warning(
                "Could not fetch subscription links for user %s subscription %s: %s",
                user.tg_id,
                subscription_id,
                exception,
            )
            return []

        body = raw.decode("utf-8", errors="replace").strip()

        if not body:
            return []

        # 3X-UI may return the standard subscription body as base64.
        decoded = body
        try:
            normalized = "".join(body.split())
            padding = "=" * (-len(normalized) % 4)
            decoded_bytes = base64.b64decode(
                normalized + padding,
                validate=True,
            )
            decoded_candidate = decoded_bytes.decode(
                "utf-8",
                errors="replace",
            ).strip()

            if decoded_candidate:
                decoded = decoded_candidate
        except Exception:
            # Plain-text subscription response; keep it unchanged.
            pass

        links: list[str] = []

        for line in decoded.replace("\r\n", "\n").split("\n"):
            line = line.strip()

            if not line:
                continue

            # Only accept actual proxy share links.
            if "://" not in line:
                continue

            scheme = line.split("://", 1)[0].lower()

            if scheme in {
                "vless",
                "vmess",
                "trojan",
                "ss",
                "socks",
                "http",
                "hysteria",
                "hysteria2",
                "hy2",
            }:
                if line not in links:
                    links.append(line)

        logger.info(
            "Retrieved %s individual live subscription links for user %s subscription %s.",
            len(links),
            user.tg_id,
            subscription_id,
        )

        return links

    async def create_client(
        self,
        user: User,
        devices: int,
        duration: int,
        enable: bool = True,
        flow: str = DEFAULT_FLOW,
        total_gb: int = 0,
        inbound_id: int = 1,
        config_name: str | None = None,
    ) -> str | None:
        total_bytes = self._gb_to_bytes(total_gb)
        logger.info(
            f"Creating new client {user.tg_id} | {devices} devices {duration} days | {total_gb} GB ({total_bytes} bytes)."
        )

        if not await self.server_pool_service.assign_server_to_user(user):
            logger.error(f"Could not assign a server to user {user.tg_id}.")
            return False

        connection = await self.server_pool_service.get_connection(user)
        if not connection:
            return False

        selected_inbounds = await self.server_pool_service.get_selected_inbounds(connection.server, connection.api)
        if not selected_inbounds:
            logger.error(f"No selected/usable inbounds found on server {connection.server.name}.")
            return False

        if not config_name or not config_name.strip():
            logger.error(f"No config name provided for client creation. User={user.tg_id}")
            return False

        client_name = config_name.strip()
        logger.info(
            f"Using config/client name for {user.tg_id}: {client_name}; selected inbounds={[inbound.id for inbound in selected_inbounds]}"
        )

        client_uuid = str(uuid.uuid4())
        new_client = Client(
            email=client_name,
            enable=enable,
            id=client_uuid,
            expiry_time=days_to_timestamp(duration),
            flow=flow or self.DEFAULT_FLOW,
            limit_ip=devices,
            sub_id=client_uuid,
            tg_id=user.tg_id,
            total_gb=total_bytes,
        )

        created_ids: list[int] = []
        try:
            for inbound in selected_inbounds:
                await connection.api.client.add(
                    inbound_id=inbound.id,
                    clients=[copy.deepcopy(new_client)],
                )
                logger.info(
                    f"CREATED CLIENT DEBUG | id={new_client.id} | sub_id={new_client.sub_id} | tg_id={new_client.tg_id} | flow={new_client.flow} | total_gb={new_client.total_gb}"
                )
                created_ids.append(int(inbound.id))
                logger.info(
                    f"Successfully created client for {user.tg_id} on inbound {inbound.id} with limit_ip={devices}, total_gb={total_bytes}, tg_id={user.tg_id}, flow={new_client.flow}, name={client_name}"
                )

            try:
                refreshed_inbounds = await get_inbounds(connection.api)
                for refreshed in refreshed_inbounds:
                    for client in refreshed.settings.clients or []:
                        if str(client.id) == str(client_uuid):
                            logger.info(f"REAL SUB ID FOUND | id={client.id} | sub_id={client.sub_id}")
                            return str(client.sub_id or client.id)
            except Exception as exception:
                logger.warning(f"Could not refresh client after creation: {exception}")

            return client_uuid
        except Exception as exception:
            logger.error(
                f"Error creating client for {user.tg_id} on inbound {getattr(inbound, 'id', 'unknown')}: {exception}"
            )
            return None

    async def update_client(
        self,
        user: User,
        devices: int,
        duration: int,
        replace_devices: bool = False,
        replace_duration: bool = False,
        enable: bool = True,
        flow: str = DEFAULT_FLOW,
        total_gb: int = 0,
    ) -> bool:
        total_bytes = self._gb_to_bytes(total_gb)
        logger.info(
            f"Updating client {user.tg_id} | {devices} devices {duration} days | {total_gb} GB ({total_bytes} bytes)."
        )
        connection = await self.server_pool_service.get_connection(user)
        if not connection:
            return False

        try:
            matches = await self._find_clients(user)
            if not matches:
                logger.error(f"Client {user.tg_id} not found for update on server {connection.server.name}.")
                return False

            primary_client, _ = matches[0]
            if not replace_devices:
                current_device_limit = primary_client.limit_ip or 0
                devices = current_device_limit + devices

            current_time = get_current_timestamp()
            expiry_time_to_use = max(primary_client.expiry_time, current_time) if not replace_duration else current_time
            expiry_time = add_days_to_timestamp(timestamp=expiry_time_to_use, days=duration)

            for client, inbound in matches:
                client.enable = enable
                client.id = client.id or user.vpn_id
                client.expiry_time = expiry_time
                client.flow = flow or self.DEFAULT_FLOW
                client.limit_ip = devices
                client.sub_id = user.vpn_id
                client.tg_id = user.tg_id
                client.total_gb = total_bytes
                if not client.id:
                    logger.error(f"Client {user.tg_id} has no UUID; cannot update it on inbound {inbound.id}.")
                    return False
                await connection.api.client.update(client_uuid=client.id, client=client)
                logger.info(
                    f"Client {user.tg_id} updated successfully on inbound {inbound.id} with limit_ip={devices}, total_gb={total_bytes}, tg_id={user.tg_id}, flow={client.flow}."
                )
            return True
        except Exception as exception:
            logger.error(f"Error updating client {user.tg_id}: {exception}")
            return False

    async def create_subscription(
        self,
        user: User,
        devices: int,
        duration: int,
        total_gb: int = 0,
        config_name: str | None = None,
    ) -> bool:
        if config_name and config_name.strip():
            requested_name = config_name.strip()
            if requested_name.endswith("-1"):
                final_config_name = await self._generate_unique_config_name(
                    volume_gb=total_gb,
                    duration_days=duration,
                    tg_id=user.tg_id,
                )
            else:
                final_config_name = requested_name
        else:
            final_config_name = await self._generate_unique_config_name(
                volume_gb=total_gb,
                duration_days=duration,
                tg_id=user.tg_id,
            )

        client_uuid = await self.create_client(
            user=user,
            devices=devices,
            duration=duration,
            total_gb=total_gb,
            config_name=final_config_name,
        )
        if not client_uuid:
            return False

        async with self.session() as session:
            fresh_user = await User.get(session=session, tg_id=user.tg_id)
            if not fresh_user:
                logger.error(f"User {user.tg_id} not found while saving subscription.")
                return False

            subscription = Subscription(
                user_id=fresh_user.id,
                server_id=fresh_user.server_id,
                config_name=final_config_name,
                client_id=client_uuid,
                volume_gb=total_gb,
                duration_days=duration,
                devices=devices,
                status="active",
            )
            session.add(subscription)
            await session.commit()

        logger.info(f"Subscription record created for user {user.tg_id}")
        return True

    async def extend_subscription(self, user: User, devices: int, duration: int, total_gb: int = 0) -> bool:
        return await self.update_client(user=user, devices=devices, duration=duration, replace_devices=True, total_gb=total_gb)

    async def change_subscription(self, user: User, devices: int, duration: int, total_gb: int = 0) -> bool:
        if await self.is_client_exists(user):
            return await self.update_client(user, devices, duration, replace_devices=True, replace_duration=True, total_gb=total_gb)
        return False

    async def process_bonus_days(self, user: User, duration: int, devices: int) -> bool:
        if await self.is_client_exists(user):
            updated = await self.update_client(user=user, devices=0, duration=duration)
            if updated:
                logger.info(f"Updated client {user.tg_id} with additional {duration} day(s).")
                return True
        else:
            config_name = await self._generate_unique_config_name(
                volume_gb=0,
                duration_days=duration,
                tg_id=user.tg_id,
            )
            created = await self.create_client(
                user=user,
                devices=devices,
                duration=duration,
                config_name=config_name,
            )
            if created:
                logger.info(
                    f"Created client {user.tg_id} with additional {duration} day(s) and name={config_name}"
                )
                return True
        return False
