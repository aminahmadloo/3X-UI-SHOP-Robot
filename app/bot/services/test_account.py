from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from py3xui import Client
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.services.server_pool import ServerPoolService
from app.bot.utils.network import extract_base_url
from app.config import Config
from app.db.models import Server, SubscriptionSettings, TestAccount, TestAccountSettings, User

logger = logging.getLogger(__name__)


class TestAccountService:
    BYTES_PER_MB = 1024 * 1024

    def __init__(
        self,
        config: Config,
        session_factory: async_sessionmaker,
        server_pool_service: ServerPoolService,
    ) -> None:
        self.config = config
        self.session_factory = session_factory
        self.server_pool_service = server_pool_service
        logger.info("Test Account Service initialized.")

    async def get_settings(self, session: AsyncSession) -> TestAccountSettings:
        return await TestAccountSettings.get_or_create(session)

    async def create_test_account(self, user: User) -> tuple[str, TestAccount] | None:
        async with self.session_factory() as session:
            settings = await self.get_settings(session)
            if not settings.enabled:
                return None

            fresh_user = await User.get(session=session, tg_id=user.tg_id)
            if fresh_user and fresh_user.is_trial_used:
                return None

            existing = await TestAccount.get_by_telegram_id(session, user.tg_id)
            if existing and existing.status in {"active", "deleted", "pending"}:
                return None
            if existing and existing.status == "failed":
                await session.delete(existing)
                await session.commit()

            server = await self.server_pool_service.get_available_server()
            if server is None:
                logger.warning("No available server for test account of user %s", user.tg_id)
                return None

            connection = await self.server_pool_service.get_connection_for_server(server)
            if connection is None:
                logger.warning("Could not connect to server %s for test account", server.name)
                return None

            inbounds = await self.server_pool_service.get_selected_inbounds(server, connection.api)
            if not inbounds:
                logger.warning("No configured inbound available on server %s", server.name)
                return None

            inbound = inbounds[0]
            client_id = str(uuid.uuid4())
            client_email = f"test-{user.tg_id}-{uuid.uuid4().hex[:6]}"
            quota_bytes = int(settings.volume_mb) * self.BYTES_PER_MB
            expires_at = datetime.utcnow() + timedelta(days=int(settings.duration_days))
            expiry_ms = int(expires_at.timestamp() * 1000)

            record = TestAccount(
                telegram_user_id=user.tg_id,
                username=user.username,
                first_name=user.first_name,
                server_id=server.id,
                inbound_id=int(inbound.id),
                client_id=client_id,
                client_email=client_email,
                subscription_token=client_id,
                quota_bytes=quota_bytes,
                expires_at=expires_at,
                status="pending",
            )
            session.add(record)
            try:
                await session.commit()
                await session.refresh(record)
            except IntegrityError:
                await session.rollback()
                logger.info("User %s already reserved a test account.", user.tg_id)
                return None

            flow = ""
            protocol = str(getattr(inbound, "protocol", "") or "").lower()
            if protocol == "vless":
                flow = "xtls-rprx-vision"

            client = Client(
                id=client_id,
                uuid=client_id,
                email=client_email,
                enable=True,
                expiry_time=expiry_ms,
                total_gb=quota_bytes,
                sub_id=client_id,
                tg_id=user.tg_id,
                flow=flow,
                limit_ip=0,
            )
            if protocol == "trojan":
                client.password = client_id

            try:
                await connection.api.client.add(
                    inbound_id=int(inbound.id),
                    clients=[client],
                )
            except Exception as exception:
                logger.exception("Failed to create test client %s in 3X-UI", client_email)
                record.status = "failed"
                record.failure_reason = str(exception)
                await session.commit()
                return None

            record.status = "active"
            await session.execute(
                update(User).where(User.tg_id == user.tg_id).values(is_trial_used=True)
            )
            await session.commit()

            subscription_settings = await SubscriptionSettings.get_or_create(session)
            base_host = subscription_settings.domain or connection.server.host
            subscription_base = extract_base_url(
                url=base_host,
                port=subscription_settings.port,
                path=subscription_settings.path,
            )
            subscription_key = f"{subscription_base}{client_id}"

            logger.info(
                "Created one-time test account %s for Telegram user %s on %s/inbound %s",
                client_email,
                user.tg_id,
                server.name,
                inbound.id,
            )
            return subscription_key, record

    async def _delete_from_xui(self, record: TestAccount) -> bool:
        async with self.session_factory() as session:
            server = await session.get(Server, record.server_id)

        if server is None:
            logger.error("Server %s for test account %s no longer exists", record.server_id, record.id)
            return False

        connection = await self.server_pool_service.get_connection_for_server(server)
        if connection is None:
            return False

        try:
            await connection.api.client.delete(record.inbound_id, record.client_id)
            return True
        except Exception as exception:
            try:
                inbounds = await connection.api.inbound.get_list()
                still_exists = any(
                    str(c.email or "") == record.client_email
                    for inbound in inbounds
                    for c in (inbound.settings.clients or [])
                )
                if not still_exists:
                    return True
            except Exception:
                pass
            logger.warning("Could not delete test client %s: %s", record.client_email, exception)
            return False

    async def cleanup_expired(self) -> int:
        removed = 0
        now = datetime.utcnow()

        async with self.session_factory() as session:
            result = await session.execute(
                select(TestAccount).where(TestAccount.status == "active")
            )
            records = result.scalars().all()

        for record in records:
            usage_up = record.usage_up_bytes
            usage_down = record.usage_down_bytes
            should_delete = record.expires_at <= now

            async with self.session_factory() as session:
                server = await session.get(Server, record.server_id)

            if server is None:
                continue

            connection = await self.server_pool_service.get_connection_for_server(server)
            if connection is None:
                continue

            try:
                inbounds = await connection.api.inbound.get_list()
                live_client = None
                for inbound in inbounds:
                    for client in inbound.settings.clients or []:
                        if str(client.email or "") == record.client_email:
                            live_client = client
                            break
                    if live_client:
                        break

                if live_client is None:
                    should_delete = True
                else:
                    stats = None
                    for inbound in inbounds:
                        for item in inbound.client_stats or []:
                            if str(item.email or "") == record.client_email:
                                stats = item
                                break
                        if stats:
                            break

                    if stats is not None:
                        try:
                            usage_up = int(stats.up or 0)
                            usage_down = int(stats.down or 0)
                        except (TypeError, ValueError):
                            pass

                    if usage_up + usage_down >= record.quota_bytes:
                        should_delete = True
            except Exception as exception:
                logger.warning("Could not inspect test account %s: %s", record.client_email, exception)
                continue

            if not should_delete:
                async with self.session_factory() as session:
                    db_record = await session.get(TestAccount, record.id)
                    if db_record:
                        db_record.usage_up_bytes = usage_up
                        db_record.usage_down_bytes = usage_down
                        await session.commit()
                continue

            if not await self._delete_from_xui(record):
                continue

            async with self.session_factory() as session:
                db_record = await session.get(TestAccount, record.id)
                if db_record:
                    db_record.usage_up_bytes = usage_up
                    db_record.usage_down_bytes = usage_down
                    db_record.status = "deleted"
                    db_record.deleted_at = datetime.utcnow()
                    await session.commit()
                    removed += 1

        logger.info("Test account cleanup finished: %s account(s) deleted.", removed)
        return removed
