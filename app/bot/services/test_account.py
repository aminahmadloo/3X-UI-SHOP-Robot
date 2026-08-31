from __future__ import annotations

import copy
import logging
import uuid
from datetime import datetime, timedelta

from py3xui import Client
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.bot.services.xui_inbound_adapter import get_inbounds
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

            existing_records = await TestAccount.get_all_by_telegram_id(
                session=session,
                telegram_user_id=user.tg_id,
            )

            active_existing = [
                record
                for record in existing_records
                if record.status in {"active", "pending"}
            ]

            if active_existing:
                logger.warning(
                    "User %s already has test account records: %s",
                    user.tg_id,
                    [record.id for record in active_existing],
                )
                return None

            for record in existing_records:
                if record.status == "failed":
                    await session.delete(record)

            if existing_records:
                await session.commit()

            server = await self.server_pool_service.get_available_server()

            if server is None:
                logger.warning(
                    "No available server for test account of user %s",
                    user.tg_id,
                )
                return None

            connection = await self.server_pool_service.get_connection_for_server(server)

            if connection is None:
                logger.warning(
                    "Could not connect to server %s for test account",
                    server.name,
                )
                return None

            inbounds = await self.server_pool_service.get_selected_inbounds(
                server,
                connection.api,
            )

            if not inbounds:
                logger.warning(
                    "No configured inbound available on server %s",
                    server.name,
                )
                return None

            logger.info(
                "Creating test account for user %s on selected inbounds: %s",
                user.tg_id,
                [int(inbound.id) for inbound in inbounds],
            )

            client_id = str(uuid.uuid4())
            subscription_token = client_id

            quota_bytes = int(settings.volume_mb) * self.BYTES_PER_MB
            expires_at = datetime.utcnow() + timedelta(
                days=int(settings.duration_days)
            )
            expiry_ms = int(expires_at.timestamp() * 1000)

            created_records: list[TestAccount] = []
            created_inbounds: list[int] = []

            try:
                for inbound in inbounds:
                    inbound_id = int(inbound.id)

                    client_email = (
                        f"test-{user.tg_id}-"
                        f"{uuid.uuid4().hex[:8]}-in{inbound_id}"
                    )

                    record = TestAccount(
                        telegram_user_id=user.tg_id,
                        username=user.username,
                        first_name=user.first_name,
                        server_id=server.id,
                        inbound_id=inbound_id,
                        client_id=client_id,
                        client_email=client_email,
                        subscription_token=subscription_token,
                        quota_bytes=quota_bytes,
                        expires_at=expires_at,
                        status="pending",
                    )

                    session.add(record)

                    await session.flush()

                    protocol = str(
                        getattr(inbound, "protocol", "") or ""
                    ).lower()

                    flow = ""
                    if protocol == "vless":
                        flow = "xtls-rprx-vision"

                    client = Client(
                        id=client_id,
                        uuid=client_id,
                        email=client_email,
                        enable=True,
                        expiry_time=expiry_ms,
                        total_gb=quota_bytes,
                        sub_id=subscription_token,
                        tg_id=user.tg_id,
                        flow=flow,
                        limit_ip=0,
                    )

                    if protocol == "trojan":
                        client.password = client_id

                    logger.info(
                        "Creating test client %s on inbound %s",
                        client_email,
                        inbound_id,
                    )

                    await connection.api.client.add(
                        inbound_id=inbound_id,
                        clients=[copy.deepcopy(client)],
                    )

                    created_records.append(record)
                    created_inbounds.append(inbound_id)

                if len(created_records) != len(inbounds):
                    raise RuntimeError(
                        "Not all selected inbounds received a test client"
                    )

                for record in created_records:
                    record.status = "active"

                await session.execute(
                    update(User)
                    .where(User.tg_id == user.tg_id)
                    .values(is_trial_used=True)
                )

                await session.commit()

            except Exception as exception:
                logger.exception(
                    "Failed to create complete multi-inbound test account "
                    "for user %s",
                    user.tg_id,
                )

                await session.rollback()

                # Roll back every XUI client that was already created.
                for inbound_id in created_inbounds:
                    try:
                        await connection.api.client.delete(
                            inbound_id,
                            client_id,
                        )
                        logger.info(
                            "Rolled back test client %s from inbound %s",
                            client_id,
                            inbound_id,
                        )
                    except Exception as rollback_exception:
                        logger.error(
                            "Could not rollback test client %s from inbound %s: %s",
                            client_id,
                            inbound_id,
                            rollback_exception,
                        )

                return None

            subscription_settings = await SubscriptionSettings.get_or_create(
                session
            )

            base_host = subscription_settings.domain or connection.server.host

            subscription_base = extract_base_url(
                url=base_host,
                port=subscription_settings.port,
                path=subscription_settings.path,
            )

            subscription_key = (
                f"{subscription_base}{subscription_token}"
            )

            await session.refresh(created_records[0])

            logger.info(
                "Created complete multi-inbound test account for Telegram "
                "user %s on %s: inbounds=%s client_id=%s",
                user.tg_id,
                server.name,
                created_inbounds,
                client_id,
            )

            return subscription_key, created_records[0]

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
            inbounds = await get_inbounds(connection.api)

            target_inbounds = [
                inbound
                for inbound in inbounds
                if any(
                    str(c.id or "") == str(record.client_id)
                    or str(c.uuid or "") == str(record.client_id)
                    or str(c.email or "") == str(record.client_email)
                    for c in (inbound.settings.clients or [])
                )
            ]

            if not target_inbounds:
                logger.info(
                    "Test client %s was not found on server %s",
                    record.client_email,
                    server.name,
                )
                return True

            failed = False

            for inbound in target_inbounds:
                try:
                    await connection.api.client.delete(
                        int(inbound.id),
                        record.client_id,
                    )
                    logger.info(
                        "Deleted test client %s from inbound %s",
                        record.client_email,
                        inbound.id,
                    )
                except Exception as exception:
                    failed = True
                    logger.warning(
                        "Could not delete test client %s from inbound %s: %s",
                        record.client_email,
                        inbound.id,
                        exception,
                    )

            if failed:
                # Verify whether any copy of the test client remains.
                try:
                    remaining = await get_inbounds(connection.api)
                    still_exists = any(
                        str(c.id or "") == str(record.client_id)
                        or str(c.uuid or "") == str(record.client_id)
                        or str(c.email or "") == str(record.client_email)
                        for inbound in remaining
                        for c in (inbound.settings.clients or [])
                    )
                    return not still_exists
                except Exception:
                    return False

            return True

        except Exception as exception:
            logger.warning(
                "Could not delete test client %s: %s",
                record.client_email,
                exception,
            )
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
                inbounds = await get_inbounds(connection.api)
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
