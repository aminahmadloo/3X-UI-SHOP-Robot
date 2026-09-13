import logging
import uuid

from py3xui import Client

from app.bot.services.xui_inbound_adapter import get_inbounds
from app.bot.utils.time import days_to_timestamp

from .vpn_base import Subscription, User
from .vpn_base import VPNService as _BaseVPNService

logger = logging.getLogger(__name__)


class VPNService(_BaseVPNService):
    """VPN service with explicit custom config names preserved end-to-end.

    The legacy implementation treated every requested name ending in ``-1``
    as an automatic-name marker. That is incompatible with the custom naming
    scheme because the first valid custom name naturally ends in ``-1``.

    Client creation is also kept here as a compatibility override so a logical
    client is created once and attached to every selected inbound in the same
    3X-UI request. This matches the multi-inbound test-account implementation
    and avoids repeatedly posting the same ``subId`` to 3X-UI.
    """

    async def create_client(
        self,
        user: User,
        devices: int,
        duration: int,
        enable: bool = True,
        flow: str = _BaseVPNService.DEFAULT_FLOW,
        total_gb: int = 0,
        inbound_id: int = 1,
        config_name: str | None = None,
    ) -> str | None:
        total_bytes = self._gb_to_bytes(total_gb)
        logger.info(
            "Creating new client %s | %s devices %s days | %s GB (%s bytes).",
            user.tg_id,
            devices,
            duration,
            total_gb,
            total_bytes,
        )

        if not await self.server_pool_service.assign_server_to_user(user):
            logger.error("Could not assign a server to user %s.", user.tg_id)
            return None

        connection = await self.server_pool_service.get_connection(user)
        if not connection:
            return None

        selected_inbounds = await self.server_pool_service.get_selected_inbounds(
            connection.server,
            connection.api,
        )
        if not selected_inbounds:
            logger.error(
                "No selected/usable inbounds found on server %s.",
                connection.server.name,
            )
            return None

        if not config_name or not config_name.strip():
            logger.error(
                "No config name provided for client creation. User=%s",
                user.tg_id,
            )
            return None

        client_name = config_name.strip()
        inbound_ids = [int(inbound.id) for inbound in selected_inbounds]
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

        client_payload = new_client.model_dump(
            by_alias=True,
            exclude_defaults=True,
        )
        endpoint = "panel/api/clients/add"
        headers = {"Accept": "application/json"}
        payload = {
            "client": client_payload,
            "inboundIds": inbound_ids,
        }

        logger.info(
            "Creating logical client %s once across selected inbounds: %s",
            client_name,
            inbound_ids,
        )

        try:
            await connection.api.client._post(
                endpoint,
                headers,
                payload,
            )

            logger.info(
                "3X-UI accepted client %s across %s inbounds.",
                client_name,
                len(inbound_ids),
            )

            # Verify that the client is visible after the atomic create. This
            # prevents the bot from reporting a successful purchase when the
            # panel accepted the request but did not expose the client yet.
            try:
                refreshed_inbounds = await get_inbounds(connection.api)
                matched_ids = {
                    int(inbound.id)
                    for inbound in refreshed_inbounds
                    if any(
                        str(client.id) == client_uuid
                        or str(client.sub_id or "") == client_uuid
                        for client in (inbound.settings.clients or [])
                    )
                }

                missing_ids = sorted(set(inbound_ids) - matched_ids)
                if missing_ids:
                    logger.error(
                        "Client %s was not visible on all selected inbounds after creation; "
                        "missing=%s matched=%s",
                        client_name,
                        missing_ids,
                        sorted(matched_ids),
                    )
                    return None

                logger.info(
                    "Client %s verified on all selected inbounds: %s",
                    client_name,
                    sorted(matched_ids),
                )
            except Exception as exception:
                logger.warning(
                    "Could not verify client %s after creation: %s",
                    client_name,
                    exception,
                )

            return client_uuid
        except Exception as exception:
            logger.error(
                "Error creating client %s for user %s across inbounds %s: %s",
                client_name,
                user.tg_id,
                inbound_ids,
                exception,
            )
            return None

    async def create_subscription(
        self,
        user: User,
        devices: int,
        duration: int,
        total_gb: int = 0,
        config_name: str | None = None,
    ) -> bool:
        if config_name and config_name.strip():
            final_config_name = config_name.strip()
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

        return True
