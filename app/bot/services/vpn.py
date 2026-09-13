from .vpn_base import Subscription, User
from .vpn_base import VPNService as _BaseVPNService


class VPNService(_BaseVPNService):
    """VPN service with explicit custom config names preserved end-to-end.

    The legacy implementation treated every requested name ending in ``-1``
    as an automatic-name marker. That is incompatible with the custom naming
    scheme because the first valid custom name naturally ends in ``-1``.
    """

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
