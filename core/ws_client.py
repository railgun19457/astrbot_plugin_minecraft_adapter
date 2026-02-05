"""WebSocket client for Minecraft server communication."""

import asyncio
import time
import uuid
from collections.abc import Callable, Coroutine
from typing import Any

import aiohttp

from astrbot.api import logger

from .models import MCMessage, MessageType, ServerInfo

# Connection constants
DEFAULT_RECONNECT_DELAY = 1  # Initial reconnect delay in seconds
MAX_RECONNECT_DELAY = 60  # Maximum reconnect delay in seconds
DEFAULT_HEARTBEAT_INTERVAL = 30  # Heartbeat interval in seconds
CONNECTION_TIMEOUT = 10  # Connection timeout in seconds


class WebSocketClient:
    """WebSocket client for communicating with Minecraft server."""

    def __init__(
        self,
        server_id: str,
        host: str,
        port: int,
        token: str,
        on_message: Callable[[MCMessage], Coroutine[Any, Any, None]] | None = None,
        on_connect: Callable[[ServerInfo], Coroutine[Any, Any, None]] | None = None,
        on_disconnect: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        heartbeat_interval: int = DEFAULT_HEARTBEAT_INTERVAL,
        max_reconnect_delay: int = MAX_RECONNECT_DELAY,
    ):
        self.server_id = server_id
        self.host = host
        self.port = port
        self.token = token
        self.on_message = on_message
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect

        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._session: aiohttp.ClientSession | None = None
        self._running = False
        self._connected = False
        self._reconnect_delay = DEFAULT_RECONNECT_DELAY
        self._max_reconnect_delay = max_reconnect_delay
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_task: asyncio.Task | None = None
        self._session_id: str = ""
        self._server_info: ServerInfo | None = None

    @property
    def connected(self) -> bool:
        return self._connected

    @property
    def server_info(self) -> ServerInfo | None:
        return self._server_info

    @property
    def ws_url(self) -> str:
        return f"ws://{self.host}:{self.port}/ws?token={self.token}"

    async def connect(self) -> bool:
        """Establish WebSocket connection."""
        if self._connected:
            return True

        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()

            logger.info(f"[MC-{self.server_id}] Connecting to {self.host}:{self.port}")
            self._ws = await self._session.ws_connect(
                self.ws_url,
                heartbeat=self._heartbeat_interval,
            )

            # Wait for CONNECTION_ACK
            msg = await asyncio.wait_for(self._ws.receive(), timeout=CONNECTION_TIMEOUT)
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = msg.json()
                if data.get("type") == MessageType.CONNECTION_ACK.value:
                    self._session_id = data.get("data", {}).get("sessionId", "")
                    server_data = data.get("data", {}).get("serverInfo", {})
                    self._server_info = ServerInfo.from_dict(server_data)
                    self._connected = True
                    self._reconnect_delay = DEFAULT_RECONNECT_DELAY  # Reset on success

                    logger.info(
                        f"[MC-{self.server_id}] Connected to {self._server_info.name} "
                        f"({self._server_info.platform} {self._server_info.minecraft_version})"
                    )

                    if self.on_connect:
                        await self.on_connect(self._server_info)

                    return True

            logger.error(
                f"[MC-{self.server_id}] Failed to receive CONNECTION_ACK: {msg}"
            )
            return False

        except asyncio.TimeoutError:
            logger.error(f"[MC-{self.server_id}] Connection timeout")
            return False
        except Exception as e:
            logger.error(f"[MC-{self.server_id}] Connection failed: {e}")
            return False

    async def disconnect(self):
        """Close WebSocket connection."""
        self._running = False
        self._connected = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

        if self._ws and not self._ws.closed:
            await self._ws.close()
            self._ws = None

        if self._session:
            await self._session.close()
            self._session = None

        logger.info(f"[MC-{self.server_id}] Disconnected")

    async def start(self):
        """Start the WebSocket client with automatic reconnection."""
        self._running = True

        while self._running:
            if not self._connected:
                success = await self.connect()
                if not success:
                    # Exponential backoff for reconnection
                    logger.info(
                        f"[MC-{self.server_id}] "
                        f"Reconnecting in {self._reconnect_delay}s..."
                    )
                    await asyncio.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(
                        self._reconnect_delay * 2, self._max_reconnect_delay
                    )
                    continue

            # Start heartbeat task
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # Message receiving loop
            try:
                await self._receive_loop()
            except Exception as e:
                logger.error(f"[MC-{self.server_id}] Receive loop error: {e}")
            finally:
                self._connected = False
                if self._heartbeat_task:
                    self._heartbeat_task.cancel()

                if self.on_disconnect and self._running:
                    await self.on_disconnect("Connection lost")

    async def _receive_loop(self):
        """Main message receiving loop."""
        if not self._ws:
            return

        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    data = msg.json()
                    mc_msg = MCMessage.from_dict(data)
                    await self._handle_message(mc_msg)
                except Exception as e:
                    logger.error(f"[MC-{self.server_id}] Error parsing message: {e}")

            elif msg.type == aiohttp.WSMsgType.ERROR:
                logger.error(f"[MC-{self.server_id}] WebSocket error: {msg.data}")
                break

            elif msg.type == aiohttp.WSMsgType.CLOSED:
                logger.info(f"[MC-{self.server_id}] WebSocket closed")
                break

    async def _handle_message(self, msg: MCMessage):
        """Handle incoming WebSocket message.

        Args:
            msg: The MCMessage object to process

        Note:
            Handles different message types including heartbeat, disconnect,
            error messages, and forwards other types to the registered handler.
        """
        if msg.type == MessageType.HEARTBEAT:
            # Respond to server heartbeat
            await self._send_heartbeat_ack(msg.id)

        elif msg.type == MessageType.HEARTBEAT_ACK:
            # Heartbeat acknowledged
            pass

        elif msg.type == MessageType.DISCONNECT:
            reason = msg.payload.get("reason", "Unknown")
            message = msg.payload.get("message", "")
            logger.warning(
                f"[MC-{self.server_id}] Server disconnect: {reason} - {message}"
            )
            self._connected = False

        elif msg.type == MessageType.ERROR:
            code = msg.payload.get("code", 0)
            error_msg = msg.payload.get("message", "")
            logger.error(f"[MC-{self.server_id}] Error {code}: {error_msg}")

        else:
            # Forward to message handler
            if self.on_message:
                try:
                    await self.on_message(msg)
                except Exception as e:
                    logger.error(f"[MC-{self.server_id}] Error in message handler: {e}")

    async def _heartbeat_loop(self):
        """Send periodic heartbeats."""
        while self._connected and self._running:
            await asyncio.sleep(self._heartbeat_interval)
            if self._connected:
                await self._send_heartbeat()

    async def _send_heartbeat(self):
        """Send heartbeat message."""
        msg = {
            "type": MessageType.HEARTBEAT.value,
            "id": str(uuid.uuid4()),
            "timestamp": int(time.time() * 1000),
        }
        await self._send(msg)

    async def _send_heartbeat_ack(self, msg_id: str):
        """Send heartbeat acknowledgment."""
        msg = {
            "type": MessageType.HEARTBEAT_ACK.value,
            "id": msg_id,
            "timestamp": int(time.time() * 1000),
        }
        await self._send(msg)

    async def _send(self, data: dict) -> bool:
        """Send JSON data over WebSocket."""
        if not self._ws or self._ws.closed:
            return False

        try:
            await self._ws.send_json(data)
            return True
        except Exception as e:
            logger.error(f"[MC-{self.server_id}] Send error: {e}")
            return False

    async def send_message(self, msg: MCMessage) -> bool:
        """Send a MCMessage over WebSocket."""
        return await self._send(msg.to_dict())

    async def send_chat_response(
        self,
        reply_to: str,
        target_type: str,
        chat_mode: str,
        content: str,
        player_uuid: str = "",
        success: bool = True,
        error_message: str = "",
    ) -> bool:
        """Send AI chat response."""
        msg = {
            "type": MessageType.CHAT_RESPONSE.value,
            "id": str(uuid.uuid4()),
            "replyTo": reply_to,
            "target": {
                "type": target_type,
            },
            "payload": {
                "content": content,
                "chatMode": chat_mode,
                "success": success,
                "errorMessage": error_message if not success else None,
            },
            "timestamp": int(time.time() * 1000),
        }

        if player_uuid:
            msg["target"]["playerUuid"] = player_uuid

        return await self._send(msg)

    async def send_incoming_message(
        self,
        platform: str,
        user_id: str,
        user_name: str,
        content: str,
        target_type: str = "BROADCAST",
        player_uuid: str = "",
    ) -> bool:
        """Send incoming message from external platform to MC server."""
        msg = {
            "type": MessageType.MESSAGE_INCOMING.value,
            "id": str(uuid.uuid4()),
            "target": {
                "type": target_type,
            },
            "payload": {
                "source": {
                    "platform": platform,
                    "userId": user_id,
                    "userName": user_name,
                },
                "content": content,
            },
            "timestamp": int(time.time() * 1000),
        }

        if player_uuid:
            msg["target"]["playerUuid"] = player_uuid

        return await self._send(msg)

    async def send_command_request(
        self,
        command: str,
        executor: str = "CONSOLE",
        player_uuid: str | None = None,
    ) -> bool:
        """Send command execution request."""
        msg = {
            "type": MessageType.COMMAND_REQUEST.value,
            "id": str(uuid.uuid4()),
            "payload": {
                "command": command,
                "executor": executor,
            },
            "timestamp": int(time.time() * 1000),
        }

        if player_uuid:
            msg["payload"]["playerUuid"] = player_uuid

        return await self._send(msg)
