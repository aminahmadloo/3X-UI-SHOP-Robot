from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .server_pool import ServerPoolService

import logging

from py3xui import Client, Inbound
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.bot.models import ClientData
from app.bot.utils.network import extract_base_url
from app.bot.utils.time import (
    add_days_to_timestamp,
    days_to_timestamp,
    get_current_timestamp,
)
from app.config import Config
from app.db.models import Promocode, User

logger = logging.getLogger(__name__)


class VPNService:
    def __init__(
        self,
        config: Config,
        session: async_sessionmaker,
        server_pool_service: ServerPoolService,
    ) -> None:
        self.config = config
        self.session = session
        self.server_pool_service = server_pool_service
        logger.info("VPN Service initialized.")

    async def _find_client(self, user: User) -> tuple[Client, Inbound] | None:
        """Find a client through the inbound list API.

        py3xui 0.3.x uses the client-traffic endpoint for get_by_email(), but
        some newer 3X-UI versions do not expose that endpoint. The inbound
        list response contains both client settings and clientStats, so use it
        consistently for client lookup and updates.
        """
        connection = await self.server_pool_service.get_connection(user)
        if not connection:
            return None

        try:
            inbounds: list[Inbound] = await connection.api.inbound.get_list()
        except Exception as exception:
            logger.error(
                f"Failed to fetch inbounds while looking up client {user.tg_id}: {exception}"
            )
            return None

        email = str(user.tg_id)
        for inbound in inbounds:
            for client in inbound.settings.clients or []:
                if client.email == email:
                    return client, inbound

        return None

    async def is_client_exists(self, user: User) -> Client | None:
        result = await self._find_client(user)

        if result:
            client, inbound = result
            connection = await self.server_pool_service.get_connection(user)
            server_name = connection.server.name if connection else "unknown"
            logger.debug(
                f"Client {user.tg_id} exists in inbound {inbound.id} on server {server_name}."
            )
            return client

        connection = await self.server_pool_service.get_connection(user)
        server_name = connection.server.name if connection else "unknown"
        logger.debug(
            f"Client {user.tg_id} not found on server {server_name}."
        )
        return None

    async def get_limit_ip(self, user: User, client: Client) -> int | None:
        result = await self._find_client(user)
        if not result:
            logger.error(f"Client {client.email} not found in inbound list.")
            return None

        inbound_client, _ = result
        logger.debug(
            f"Client {client.email} limit ip: {inbound_client.limit_ip}"
        )
        return inbound_client.limit_ip

    async def get_client_data(self, user: User) -> ClientData | None:
        logger.debug(f"Starting to retrieve client data for {user.tg_id}.")

        connection = await self.server_pool_service.get_connection(user)
        if not connection:
            return None

        try:
            # Do not use client.get_by_email() here. py3xui 0.3.x resolves that
            # through /panel/api/inbounds/getClientTraffics/{email}, which is
            # missing on some newer 3X-UI installations. The inbound list API
            # already contains client settings and clientStats, so use it as
            # the compatibility path for reading the subscription page.
            inbounds: list[Inbound] = await connection.api.inbound.get_list()

            client: Client | None = None
            for inbound in inbounds:
                for inbound_client in inbound.settings.clients or []:
                    if inbound_client.email == str(user.tg_id):
                        client = inbound_client
                        break
                if client:
                    break

            if not client:
                logger.warning(
                    f"Client {user.tg_id} not found on server {connection.server.name}."
                )
                return None

            # clientStats contains the live up/down/total/expiry counters.
            # Prefer the matching stats record, but keep the client settings
            # as a safe fallback for panels that return an empty clientStats.
            stats_client: Client | None = None
            for inbound in inbounds:
                for stat in inbound.client_stats or []:
                    if stat.email == str(user.tg_id):
                        stats_client = stat
                        break
                if stats_client:
                    break

            source = stats_client or client
            limit_ip = client.limit_ip
            max_devices = -1 if limit_ip == 0 else limit_ip
            traffic_total = source.total
            expiry_time = -1 if source.expiry_time == 0 else source.expiry_time

            if traffic_total <= 0:
                traffic_remaining = -1
                traffic_total = -1
            else:
                traffic_remaining = max(
                    0,
                    source.total - (source.up + source.down),
                )

            traffic_used = source.up + source.down
            client_data = ClientData(
                max_devices=max_devices,
                traffic_total=traffic_total,
                traffic_remaining=traffic_remaining,
                traffic_used=traffic_used,
                traffic_up=source.up,
                traffic_down=source.down,
                expiry_time=expiry_time,
            )
            logger.debug(
                f"Successfully retrieved client data for {user.tg_id}: {client_data}."
            )
            return client_data
        except Exception as exception:
            logger.error(
                f"Error retrieving client data for {user.tg_id}: {exception}"
            )
            return None

    async def get_key(self, user: User) -> str | None:
        async with self.session() as session:
            user = await User.get(session=session, tg_id=user.tg_id)

        if not user or not user.server_id:
            logger.debug(f"Server ID for user {user.tg_id} not found.")
            return None

        subscription = extract_base_url(
            url=user.server.host,
            port=self.config.xui.SUBSCRIPTION_PORT,
            path=self.config.xui.SUBSCRIPTION_PATH,
        )
        key = f"{subscription}{user.vpn_id}"
        logger.debug(f"Fetched key for {user.tg_id}: {key}.")
        return key

    async def create_client(
        self,
        user: User,
        devices: int,
        duration: int,
        enable: bool = True,
        flow: str = "xtls-rprx-vision",
        total_gb: int = 0,
        inbound_id: int = 1,
    ) -> bool:
        logger.info(
            f"Creating new client {user.tg_id} | {devices} devices {duration} days."
        )

        if not await self.server_pool_service.assign_server_to_user(user):
            logger.error(f"Could not assign a server to user {user.tg_id}.")
            return False

        connection = await self.server_pool_service.get_connection(user)
        if not connection:
            return False

        selected_inbound_id = await self.server_pool_service.get_inbound_id(
            connection.api,
            preferred_id=inbound_id,
        )
        if selected_inbound_id is None:
            logger.error(
                f"No usable inbound found on server {connection.server.name}."
            )
            return False

        new_client = Client(
            email=str(user.tg_id),
            enable=enable,
            id=user.vpn_id,
            expiry_time=days_to_timestamp(duration),
            flow=flow,
            limit_ip=devices,
            sub_id=user.vpn_id,
            total_gb=total_gb,
        )

        try:
            await connection.api.client.add(
                inbound_id=selected_inbound_id,
                clients=[new_client],
            )
            logger.info(
                f"Successfully created client for {user.tg_id} "
                f"on inbound {selected_inbound_id}"
            )
            return True
        except Exception as exception:
            logger.error(
                f"Error creating client for {user.tg_id}: {exception}"
            )
            return False

    async def update_client(
        self,
        user: User,
        devices: int,
        duration: int,
        replace_devices: bool = False,
        replace_duration: bool = False,
        enable: bool = True,
        flow: str = "xtls-rprx-vision",
        total_gb: int = 0,
    ) -> bool:
        logger.info(
            f"Updating client {user.tg_id} | {devices} devices {duration} days."
        )
        connection = await self.server_pool_service.get_connection(user)
        if not connection:
            return False

        try:
            result = await self._find_client(user)
            if not result:
                logger.error(
                    f"Client {user.tg_id} not found for update on server {connection.server.name}."
                )
                return False

            client, inbound = result

            if not replace_devices:
                current_device_limit = client.limit_ip
                if current_device_limit is None:
                    current_device_limit = 0
                devices = current_device_limit + devices

            current_time = get_current_timestamp()

            if not replace_duration:
                expiry_time_to_use = max(client.expiry_time, current_time)
            else:
                expiry_time_to_use = current_time

            expiry_time = add_days_to_timestamp(
                timestamp=expiry_time_to_use,
                days=duration,
            )

            client.enable = enable
            client.id = client.id or user.vpn_id
            client.expiry_time = expiry_time
            client.flow = flow
            client.limit_ip = devices
            client.sub_id = user.vpn_id
            client.total_gb = total_gb

            if not client.id:
                logger.error(
                    f"Client {user.tg_id} has no UUID; cannot update it."
                )
                return False

            await connection.api.client.update(
                client_uuid=client.id,
                client=client,
            )
            logger.info(
                f"Client {user.tg_id} updated successfully on inbound {inbound.id}."
            )
            return True
        except Exception as exception:
            logger.error(
                f"Error updating client {user.tg_id}: {exception}"
            )
            return False

    async def create_subscription(
        self,
        user: User,
        devices: int,
        duration: int,
    ) -> bool:
        if not await self.is_client_exists(user):
            return await self.create_client(
                user=user,
                devices=devices,
                duration=duration,
            )
        return False

    async def extend_subscription(
        self,
        user: User,
        devices: int,
        duration: int,
    ) -> bool:
        return await self.update_client(
            user=user,
            devices=devices,
            duration=duration,
            replace_devices=True,
        )

    async def change_subscription(
        self,
        user: User,
        devices: int,
        duration: int,
    ) -> bool:
        if await self.is_client_exists(user):
            return await self.update_client(
                user,
                devices,
                duration,
                replace_devices=True,
                replace_duration=True,
            )
        return False

    async def process_bonus_days(
        self,
        user: User,
        duration: int,
        devices: int,
    ) -> bool:
        if await self.is_client_exists(user):
            updated = await self.update_client(
                user=user,
                devices=0,
                duration=duration,
            )
            if updated:
                logger.info(
                    f"Updated client {user.tg_id} with additional {duration} day(s)."
                )
                return True
        else:
            created = await self.create_client(
                user=user,
                devices=devices,
                duration=duration,
            )
            if created:
                logger.info(
                    f"Created client {user.tg_id} with additional {duration} day(s)"
                )
                return True

        return False

    async def activate_promocode(
        self,
        user: User,
        promocode: Promocode,
    ) -> bool:
        # TODO: consider moving to some 'promocode module services' with usage of VPN service methods.
        async with self.session() as session:
            activated = await Promocode.set_activated(
                session=session,
                code=promocode.code,
                user_id=user.tg_id,
            )

        if not activated:
            logger.critical(
                f"Failed to activate promocode {promocode.code} for user {user.tg_id}."
            )
            return False

        logger.info(
            f"Begun applying promocode ({promocode.code}) to a client {user.tg_id}."
        )
        success = await self.process_bonus_days(
            user,
            duration=promocode.duration,
            devices=self.config.shop.BONUS_DEVICES_COUNT,
        )

        if success:
            return True

        async with self.session() as session:
            await Promocode.set_deactivated(
                session=session,
                code=promocode.code,
            )

        logger.warning(
            f"Promocode {promocode.code} not activated due to failure."
        )
        return False
