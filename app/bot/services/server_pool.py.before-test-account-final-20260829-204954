import asyncio
import logging
from dataclasses import dataclass

from py3xui import AsyncApi
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.config import Config
from app.db.models import Server, User

logger = logging.getLogger(__name__)


@dataclass
class Connection:
    server: Server
    api: AsyncApi


class ServerPoolService:
    def __init__(self, config: Config, session: async_sessionmaker) -> None:
        self.config = config
        self.session = session
        self._servers: dict[int, Connection] = {}
        self._pool_lock = asyncio.Lock()
        logger.info("Server Pool Service initialized.")

    def _build_api(self, server: Server) -> AsyncApi:
        return AsyncApi(
            host=server.host,
            username=self.config.xui.USERNAME,
            password=self.config.xui.PASSWORD,
            token=self.config.xui.TOKEN,
            use_tls_verify=False,
            logger=logging.getLogger(f"xui_{server.name}"),
        )

    async def _set_server_online(self, server: Server, online: bool) -> None:
        server.online = online
        async with self.session() as session:
            await Server.update(session=session, name=server.name, online=online)

    async def _add_server(self, server: Server) -> bool:
        """Connect to a 3X-UI server using its Bearer token and add it to the pool."""
        async with self._pool_lock:
            existing = self._servers.get(server.id)
            if existing is not None:
                return True

            api = self._build_api(server)
            try:
                inbounds = await api.inbound.get_list()
                if not inbounds:
                    raise RuntimeError("3X-UI API returned no inbounds")

                server.online = True
                self._servers[server.id] = Connection(server=server, api=api)
                logger.info(f"Server {server.name} ({server.host}) added to pool successfully.")
            except Exception as exception:
                server.online = False
                logger.error(f"Failed to add server {server.name} ({server.host}): {exception}")

            async with self.session() as session:
                await Server.update(session=session, name=server.name, online=server.online)

            return server.online

    def _remove_server(self, server: Server) -> None:
        if server.id in self._servers:
            try:
                del self._servers[server.id]
                logger.info(f"Server {server.name} removed from pool.")
            except Exception as exception:
                logger.error(f"Failed to remove server {server.name}: {exception}")

    async def refresh_server(self, server: Server) -> bool:
        """Force a fresh 3X-UI API connection for one server."""
        self._remove_server(server)
        result = await self._add_server(server)
        if result:
            logger.info(f"Server {server.name} reinitialized successfully.")
        return result

    async def get_inbound_id(self, api: AsyncApi, preferred_id: int | None = None) -> int | None:
        """Return the requested inbound when it exists, otherwise the first inbound."""
        try:
            inbounds = await api.inbound.get_list()
        except Exception as exception:
            logger.error(f"Failed to fetch inbounds: {exception}")
            return None

        if not inbounds:
            logger.error("No inbounds found in 3X-UI.")
            return None

        if preferred_id is not None:
            for inbound in inbounds:
                if inbound.id == preferred_id:
                    return inbound.id
            logger.warning(
                f"Requested inbound {preferred_id} was not found; using first inbound {inbounds[0].id}."
            )

        return inbounds[0].id

    async def get_inbounds_for_server(self, server: Server):
        """Return the live inbound list for an admin-selected server."""
        connection = self._servers.get(server.id)
        if connection is None:
            if not await self._add_server(server):
                return []
            connection = self._servers.get(server.id)
            if connection is None:
                return []

        try:
            return await connection.api.inbound.get_list()
        except Exception as exception:
            logger.error(f"Failed to fetch inbounds for server {server.name}: {exception}")
            return []

    async def get_connection_for_server(self, server: Server) -> Connection | None:
        """Return a live 3X-UI connection for a specific server."""
        connection = self._servers.get(server.id)
        if connection is None:
            if not await self._add_server(server):
                return None
            connection = self._servers.get(server.id)
            if connection is None:
                return None

        async with self.session() as session:
            fresh_server = await Server.get_by_id(session=session, id=server.id)

        if fresh_server is None:
            self._remove_server(connection.server)
            logger.error(f"Server {server.id} disappeared from database.")
            return None

        if connection.server.host != fresh_server.host:
            logger.info(
                f"Server {fresh_server.name} host changed from {connection.server.host} to {fresh_server.host}; refreshing connection."
            )
            if not await self.refresh_server(fresh_server):
                return None
            connection = self._servers.get(fresh_server.id)
            if connection is None:
                return None
        else:
            connection.server = fresh_server

        return connection

    async def get_selected_inbounds(self, server: Server, api: AsyncApi):
        """Return configured live inbounds, preserving legacy fallback when none are configured."""
        try:
            inbounds = await api.inbound.get_list()
        except Exception as exception:
            logger.error(f"Failed to fetch inbounds for server {server.name}: {exception}")
            return []

        if not inbounds:
            return []

        configured = set(server.configured_inbound_ids)
        if not configured:
            return [inbounds[0]]

        selected = [inbound for inbound in inbounds if int(inbound.id) in configured]
        if not selected:
            logger.error(
                f"Server {server.name} has configured inbound IDs {sorted(configured)}, but none exist in 3X-UI."
            )
        return selected

    async def get_connection(self, user: User) -> Connection | None:
        if not user.server_id:
            logger.debug(f"User {user.tg_id} not assigned to any server.")
            return None

        connection = self._servers.get(user.server_id)

        if connection is None:
            available_servers = list(self._servers.keys())
            logger.warning(
                f"Server {user.server_id} not found in pool. User assigned server: {user.server_id}, "
                f"available servers in pool: {available_servers}. Trying to reconnect."
            )

            async with self.session() as session:
                server = await Server.get_by_id(session=session, id=user.server_id)

            if server is None:
                logger.error(f"Server {user.server_id} not found in database.")
                return None

            if not await self._add_server(server):
                logger.error(f"Could not reconnect server {server.name} ({server.host}) for user {user.tg_id}.")
                return None

            connection = self._servers.get(user.server_id)
            if connection is None:
                logger.error(f"Server {user.server_id} was added successfully but connection is unavailable.")
                return None

        async with self.session() as session:
            server = await Server.get_by_id(session=session, id=user.server_id)

        if server is None:
            self._remove_server(connection.server)
            logger.error(f"User's server {user.server_id} disappeared from database.")
            return None

        if connection.server.host != server.host:
            logger.info(
                f"Server {server.name} host changed from {connection.server.host} to {server.host}; refreshing connection."
            )
            if not await self.refresh_server(server):
                return None
            connection = self._servers.get(server.id)
            if connection is None:
                return None
        else:
            connection.server = server

        return connection


    async def check_panel_connection(self):
        """
        Check live connection with XUI panel using existing pool connections.
        """
        result = {
            "online": False,
            "servers": 0,
            "inbounds": 0,
            "message": "",
        }

        try:
            connections = list(self._servers.values())

            if not connections:
                result["message"] = "No active XUI connection"
                return result

            result["servers"] = len(connections)

            total_inbounds = 0

            for connection in connections:
                try:
                    inbounds = await connection.api.inbound.get_list()
                    total_inbounds += len(inbounds)

                except Exception as exc:
                    logger.error(
                        f"Failed checking XUI server {connection.server.name}: {exc}"
                    )

            result["inbounds"] = total_inbounds
            result["online"] = True
            result["message"] = "XUI connection OK"

            return result

        except Exception as exc:
            logger.error(f"Panel connection check failed: {exc}")
            result["message"] = str(exc)
            return result

    async def sync_servers(self) -> None:
        """Synchronize DB servers with the connection pool without re-login storms."""
        async with self.session() as session:
            db_servers = await Server.get_all(session)

        if not db_servers and not self._servers:
            logger.warning("No servers found in the database.")
            return

        db_server_map = {server.id: server for server in db_servers}

        for server_id in list(self._servers.keys()):
            if server_id not in db_server_map:
                self._remove_server(self._servers[server_id].server)

        for server_id, conn in list(self._servers.items()):
            db_server = db_server_map.get(server_id)
            if db_server is None:
                continue

            if conn.server.host != db_server.host:
                logger.info(f"Server {db_server.name} configuration changed; refreshing connection.")
                await self.refresh_server(db_server)
            else:
                conn.server = db_server

        for server in db_servers:
            if server.id not in self._servers:
                await self._add_server(server)

        logger.info(f"Sync complete. Currently active servers: {len(self._servers)}")

    async def assign_server_to_user(self, user: User) -> bool:
        server = await self.get_available_server()
        if server is None:
            logger.error(f"No available server to assign to user {user.tg_id}.")
            return False

        async with self.session() as session:
            await User.update(session=session, tg_id=user.tg_id, server_id=server.id)

        user.server_id = server.id
        logger.info(f"Assigned server {server.name} ({server.id}) to user {user.tg_id}.")
        return True

    async def get_available_server(self) -> Server | None:
        await self.sync_servers()

        servers_with_free_slots = [
            conn.server for conn in self._servers.values() if conn.server.current_clients < conn.server.max_clients
        ]

        if servers_with_free_slots:
            server = sorted(servers_with_free_slots, key=lambda s: s.current_clients)[0]
            logger.debug(f"Found server with free slots: {server.name} (clients: {server.current_clients}/{server.max_clients})")
            return server

        servers_least_loaded = list(conn.server for conn in self._servers.values())
        if servers_least_loaded:
            server = sorted(servers_least_loaded, key=lambda s: s.current_clients)[0]
            logger.warning(f"No servers with free slots. Using least loaded server: {server.name} (clients: {server.current_clients}/{server.max_clients})")
            return server

        logger.critical("No available servers found in pool")
        return None
