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



async def login_xui(api: AsyncApi, server: Server) -> None:
    import httpx

    base_url = server.host.rstrip("/")

    async with httpx.AsyncClient(
        verify=False,
        follow_redirects=True,
        timeout=20.0,
    ) as http:
        csrf_response = await http.get(
            f"{base_url}/csrf-token",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        csrf_response.raise_for_status()

        csrf_data = csrf_response.json()
        csrf_token = csrf_data.get("obj")

        if not csrf_token:
            raise RuntimeError(
                f"CSRF token missing: {csrf_data}"
            )

        data = {
            "username": api.client.username,
            "password": api.client.password,
        }

        if api.client.token:
            data["loginSecret"] = api.client.token

        login_response = await http.post(
            f"{base_url}/login",
            headers={
                "X-CSRF-Token": csrf_token,
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/json",
            },
            json=data,
        )

        login_response.raise_for_status()

        result = login_response.json()

        if not result.get("success"):
            raise RuntimeError(
                f"3X-UI login failed: {result}"
            )

        cookie = next(
            (c for c in http.cookies.jar if c.name == "3x-ui"),
            None,
        )

        if cookie is None:
            raise RuntimeError(
                "3X-UI login succeeded but session cookie was not found"
            )

        api.session = cookie.value
        api.cookie_name = cookie.name

class ServerPoolService:
    def __init__(self, config: Config, session: async_sessionmaker) -> None:
        self.config = config
        self.session = session
        self._servers: dict[int, Connection] = {}
        logger.info("Server Pool Service initialized.")

    async def _add_server(self, server: Server) -> None:
        if server.id not in self._servers:
            api = AsyncApi(
                host=server.host,
                username=self.config.xui.USERNAME,
                password=self.config.xui.PASSWORD,
                token=self.config.xui.TOKEN,
                # use_tls_verify=False,
                logger=logging.getLogger(f"xui_{server.name}"),
            )
            try:
                await login_xui(api, server)
                server.online = True
                server_conn = Connection(server=server, api=api)
                self._servers[server.id] = server_conn
                logger.info(f"Server {server.name} ({server.host}) added to pool successfully.")
            except Exception as exception:
                server.online = False
                logger.error(f"Failed to add server {server.name} ({server.host}): {exception}")

            async with self.session() as session:
                await Server.update(session=session, name=server.name, online=server.online)

    def _remove_server(self, server: Server) -> None:
        if server.id in self._servers:
            try:
                del self._servers[server.id]
            except Exception as exception:
                logger.error(f"Failed to remove server {server.name}: {exception}")

    async def refresh_server(self, server: Server) -> None:
        if server.id in self._servers:
            self._remove_server(server)

        await self._add_server(server)
        logger.info(f"Server {server.name} reinitialized successfully.")

    async def get_inbound_id(self, api: AsyncApi) -> int | None:
        try:
            inbounds = await api.inbound.get_list()
        except Exception as exception:
            logger.error(f"Failed to fetch inbounds: {exception}")
            return None
        return inbounds[0].id

    async def get_connection(self, user: User) -> Connection | None:
        if not user.server_id:
            logger.debug(f"User {user.tg_id} not assigned to any server.")
            return None

        connection = self._servers.get(user.server_id)

        if not connection:
            available_servers = list(self._servers.keys())
            logger.critical(
                f"Server {user.server_id} not found in pool. "
                f"User assigned server: {user.server_id}, "
                f"Available servers in pool: {available_servers}"
            )

            async with self.session() as session:
                server = await Server.get_by_id(session=session, id=user.server_id)

            if server:
                logger.debug(f"Server {server.name} ({server.host}) found in database.")
                # TODO: Try to add server to pool
            else:
                logger.error(f"Server {user.server_id} not found in database.")

            return None

        async with self.session() as session:
            server = await Server.get_by_id(session=session, id=user.server_id)

        connection.server = server
        return connection

    async def sync_servers(self) -> None:
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
            if db_server := db_server_map.get(server_id):
                conn.server = db_server
            await self.refresh_server(conn.server)

        for server in db_servers:
            if server.id not in self._servers:
                await self._add_server(server)

        logger.info(f"Sync complete. Currently active servers: {len(self._servers)}")

    async def assign_server_to_user(self, user: User) -> None:
        async with self.session() as session:
            server = await self.get_available_server()
            user.server_id = server.id
            await User.update(session=session, tg_id=user.tg_id, server_id=server.id)

    async def get_available_server(self) -> Server | None:
        await self.sync_servers()

        servers_with_free_slots = [
            conn.server
            for conn in self._servers.values()
            if conn.server.current_clients < conn.server.max_clients
        ]

        if servers_with_free_slots:
            server = sorted(servers_with_free_slots, key=lambda s: s.current_clients)[0]
            logger.debug(
                f"Found server with free slots: {server.name} "
                f"(clients: {server.current_clients}/{server.max_clients})"
            )
            return server

        servers_least_loaded = [conn.server for conn in self._servers.values()]
        if servers_least_loaded:
            server = sorted(servers_least_loaded, key=lambda s: s.current_clients)[0]
            logger.warning(
                f"No servers with free slots. Using least loaded server: {server.name} "
                f"(clients: {server.current_clients}/{server.max_clients})"
            )
            return server

        logger.critical("No available servers found in pool")
        return None
