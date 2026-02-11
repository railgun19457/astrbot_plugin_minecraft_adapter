"""Minecraft 服务器连接管理器"""

import asyncio
from collections.abc import Callable, Coroutine
from typing import Any

from astrbot.api import logger

from .models import MCMessage, ServerConfig, ServerInfo
from .rest_client import RestClient
from .ws_client import WebSocketClient


class ServerConnection:
    """表示与单个 Minecraft 服务器的连接"""

    def __init__(
        self,
        config: ServerConfig,
        on_message: Callable[[str, MCMessage], Coroutine[Any, Any, None]] | None = None,
        on_connect: Callable[[str, ServerInfo], Coroutine[Any, Any, None]]
        | None = None,
        on_disconnect: Callable[[str, str], Coroutine[Any, Any, None]] | None = None,
    ):
        self.config = config
        self._on_message = on_message
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect

        # 创建客户端
        self.ws_client = WebSocketClient(
            server_id=config.server_id,
            host=config.host,
            port=config.port,
            token=config.token,
            on_message=self._handle_ws_message,
            on_connect=self._handle_connect,
            on_disconnect=self._handle_disconnect,
        )

        self.rest_client = RestClient(
            server_id=config.server_id,
            host=config.host,
            port=config.port,
            token=config.token,
        )

        self._task: asyncio.Task | None = None

    @property
    def server_id(self) -> str:
        return self.config.server_id

    @property
    def connected(self) -> bool:
        return self.ws_client.connected

    @property
    def server_info(self) -> ServerInfo | None:
        return self.ws_client.server_info

    async def _handle_ws_message(self, msg: MCMessage):
        if self._on_message:
            await self._on_message(self.server_id, msg)

    async def _handle_connect(self, info: ServerInfo):
        if self._on_connect:
            await self._on_connect(self.server_id, info)

    async def _handle_disconnect(self, reason: str):
        if self._on_disconnect:
            await self._on_disconnect(self.server_id, reason)

    async def start(self):
        """启动服务器连接"""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.ws_client.start())
            logger.info(f"[MC-{self.server_id}] 连接任务已启动")

    async def stop(self):
        """停止服务器连接"""
        await self.ws_client.disconnect()
        await self.rest_client.close()

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        logger.info(f"[MC-{self.server_id}] 连接已停止")


class ServerManager:
    """管理多个 Minecraft 服务器连接"""

    def __init__(self):
        self._servers: dict[str, ServerConnection] = {}
        self._on_message: (
            Callable[[str, MCMessage], Coroutine[Any, Any, None]] | None
        ) = None
        self._on_connect: (
            Callable[[str, ServerInfo], Coroutine[Any, Any, None]] | None
        ) = None
        self._on_disconnect: Callable[[str, str], Coroutine[Any, Any, None]] | None = (
            None
        )

    def set_message_handler(
        self, handler: Callable[[str, MCMessage], Coroutine[Any, Any, None]]
    ):
        """设置传入消息的处理器"""
        self._on_message = handler

    def set_connect_handler(
        self, handler: Callable[[str, ServerInfo], Coroutine[Any, Any, None]]
    ):
        """设置连接事件的处理器"""
        self._on_connect = handler

    def set_disconnect_handler(
        self, handler: Callable[[str, str], Coroutine[Any, Any, None]]
    ):
        """设置断开连接事件的处理器"""
        self._on_disconnect = handler

    def add_server(self, config: ServerConfig) -> bool:
        """添加服务器配置"""
        if config.server_id in self._servers:
            logger.warning(f"[ServerManager] 服务器 {config.server_id} 已存在")
            return False

        connection = ServerConnection(
            config=config,
            on_message=self._on_message,
            on_connect=self._on_connect,
            on_disconnect=self._on_disconnect,
        )
        self._servers[config.server_id] = connection
        logger.info(f"[ServerManager] 已添加服务器: {config.server_id}")
        return True

    def remove_server(self, server_id: str) -> bool:
        """移除服务器配置"""
        if server_id not in self._servers:
            return False

        del self._servers[server_id]
        logger.info(f"[ServerManager] 已移除服务器: {server_id}")
        return True

    def get_server(self, server_id: str) -> ServerConnection | None:
        """通过 ID 获取服务器连接"""
        return self._servers.get(server_id)

    def get_all_servers(self) -> dict[str, ServerConnection]:
        """获取所有服务器连接"""
        return self._servers.copy()

    def get_connected_servers(self) -> list[ServerConnection]:
        """获取所有已连接的服务器"""
        return [s for s in self._servers.values() if s.connected]

    async def start_all(self):
        """启动所有服务器连接"""
        for server in self._servers.values():
            if server.config.enabled:
                await server.start()

    async def stop_all(self):
        """停止所有服务器连接"""
        for server in self._servers.values():
            await server.stop()

    async def start_server(self, server_id: str) -> bool:
        """启动特定的服务器连接"""
        server = self._servers.get(server_id)
        if server:
            await server.start()
            return True
        return False

    async def stop_server(self, server_id: str) -> bool:
        """停止特定的服务器连接"""
        server = self._servers.get(server_id)
        if server:
            await server.stop()
            return True
        return False

    # 发送消息的便捷方法

    async def send_chat_response(
        self,
        server_id: str,
        reply_to: str,
        target_type: str,
        chat_mode: str,
        content: str,
        player_uuid: str = "",
    ) -> bool:
        """向服务器发送 AI 聊天响应"""
        server = self._servers.get(server_id)
        if server and server.connected:
            return await server.ws_client.send_chat_response(
                reply_to=reply_to,
                target_type=target_type,
                chat_mode=chat_mode,
                content=content,
                player_uuid=player_uuid,
            )
        return False

    async def send_incoming_message(
        self,
        server_id: str,
        platform: str,
        user_id: str,
        user_name: str,
        content: str,
    ) -> bool:
        """将来自外部平台的消息发送到 MC 服务器"""
        server = self._servers.get(server_id)
        if server and server.connected:
            return await server.ws_client.send_incoming_message(
                platform=platform,
                user_id=user_id,
                user_name=user_name,
                content=content,
            )
        return False
