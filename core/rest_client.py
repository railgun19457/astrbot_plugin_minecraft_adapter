"""REST API client for Minecraft server communication."""

from typing import Any

import aiohttp

from astrbot.api import logger

from .models import (
    ApiResponse,
    LogEntry,
    PlayerDetail,
    PlayerInfo,
    ServerInfo,
    ServerStatus,
)

# REST API constants
DEFAULT_REQUEST_TIMEOUT = 30  # Default request timeout in seconds
HEALTH_CHECK_TIMEOUT = 5  # Health check timeout in seconds
MAX_LOG_LINES = 1000  # Maximum log lines to retrieve


class RestClient:
    """REST API client for communicating with Minecraft server."""

    def __init__(
        self,
        server_id: str,
        host: str,
        port: int,
        token: str,
        request_timeout: int = DEFAULT_REQUEST_TIMEOUT,
    ):
        self.server_id = server_id
        self.host = host
        self.port = port
        self.token = token
        self._request_timeout = request_timeout
        self._session: aiohttp.ClientSession | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/api/v1"

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self):
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: dict | None = None,
        json_data: dict | None = None,
    ) -> ApiResponse:
        """Make HTTP request to the server."""
        url = f"{self.base_url}{endpoint}"

        try:
            session = await self._get_session()
            async with session.request(
                method,
                url,
                headers=self.headers,
                params=params,
                json=json_data,
                timeout=aiohttp.ClientTimeout(total=self._request_timeout),
            ) as resp:
                data = await resp.json()
                return ApiResponse.from_dict(data)

        except aiohttp.ClientConnectorError:
            logger.error(f"[MC-{self.server_id}] Cannot connect to server")
            return ApiResponse(code=3002, message="服务器连接失败")
        except TimeoutError:
            logger.error(f"[MC-{self.server_id}] Request timeout")
            return ApiResponse(code=3002, message="请求超时")
        except Exception as e:
            logger.error(f"[MC-{self.server_id}] Request error: {e}")
            return ApiResponse(code=3001, message=str(e))

    async def _get(self, endpoint: str, params: dict | None = None) -> ApiResponse:
        return await self._request("GET", endpoint, params=params)

    async def _post(self, endpoint: str, json_data: dict | None = None) -> ApiResponse:
        return await self._request("POST", endpoint, json_data=json_data)

    # Server APIs

    async def get_server_info(self) -> tuple[ServerInfo | None, str]:
        """Get server information."""
        resp = await self._get("/server/info")
        if resp.success and resp.data:
            return ServerInfo.from_dict(resp.data), ""
        return None, resp.message

    async def get_server_status(self) -> tuple[ServerStatus | None, str]:
        """Get server status."""
        resp = await self._get("/server/status")
        if resp.success and resp.data:
            return ServerStatus.from_dict(resp.data), ""
        return None, resp.message

    async def health_check(self) -> bool:
        """Check if server is healthy (no auth required)."""
        try:
            session = await self._get_session()
            url = f"http://{self.host}:{self.port}/api/v1/health"
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=HEALTH_CHECK_TIMEOUT)
            ) as resp:
                data = await resp.json()
                return data.get("code") == 0
        except Exception:
            return False

    # Player APIs

    async def get_players(
        self, page: int = 1, size: int = 20
    ) -> tuple[list[PlayerInfo], int, str]:
        """Get online player list."""
        resp = await self._get("/players", params={"page": page, "size": size})
        if resp.success and resp.data:
            players = [PlayerInfo.from_dict(p) for p in resp.data.get("players", [])]
            total = resp.data.get("total", 0)
            return players, total, ""
        return [], 0, resp.message

    async def get_player_by_uuid(self, uuid: str) -> tuple[PlayerDetail | None, str]:
        """Get player detail by UUID."""
        resp = await self._get(f"/players/{uuid}")
        if resp.success and resp.data:
            return PlayerDetail.from_dict(resp.data), ""
        return None, resp.message

    async def get_player_by_name(self, name: str) -> tuple[PlayerDetail | None, str]:
        """Get player detail by name."""
        resp = await self._get(f"/players/name/{name}")
        if resp.success and resp.data:
            return PlayerDetail.from_dict(resp.data), ""
        return None, resp.message

    # Command APIs

    async def execute_command(
        self,
        command: str,
        executor: str = "CONSOLE",
        player_uuid: str | None = None,
        is_async: bool = False,
    ) -> tuple[bool, str, Any]:
        """Execute a command on the server.

        Returns:
            tuple: (success, output/error_message, raw_data)
        """
        json_data: dict[str, Any] = {
            "command": command,
            "executor": executor,
            "async": is_async,
        }
        if player_uuid:
            json_data["playerUuid"] = player_uuid

        resp = await self._post("/command/execute", json_data=json_data)

        if resp.success and resp.data:
            if is_async:
                return True, resp.data.get("taskId", ""), resp.data
            return (
                resp.data.get("success", False),
                resp.data.get("output", ""),
                resp.data,
            )

        return False, resp.message, None

    # Log APIs

    async def get_logs(
        self,
        lines: int = 100,
        level: str | None = None,
        keyword: str | None = None,
        start_time: int | None = None,
        end_time: int | None = None,
    ) -> tuple[list[LogEntry], str]:
        """Get server logs."""
        params: dict[str, Any] = {"lines": min(lines, MAX_LOG_LINES)}
        if level:
            params["level"] = level
        if keyword:
            params["keyword"] = keyword
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        resp = await self._get("/logs", params=params)
        if resp.success and resp.data:
            logs = [LogEntry.from_dict(log) for log in resp.data.get("logs", [])]
            return logs, ""
        return [], resp.message
