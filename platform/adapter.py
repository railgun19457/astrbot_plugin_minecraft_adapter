"""Minecraft platform adapter for AI chat."""

import asyncio

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import Plain
from astrbot.api.platform import (
    AstrBotMessage,
    MessageMember,
    MessageType,
    Platform,
    PlatformMetadata,
)
from astrbot.core.platform.astr_message_event import MessageSesion

from ..core.models import (
    ChatMode,
    MCMessage,
    ServerConfig,
)
from ..core.models import (
    MessageType as MCMessageType,
)
from ..core.server_manager import ServerConnection
from .event import MCMessageEvent


class MCPlatformAdapter(Platform):
    """Platform adapter for a Minecraft server."""

    def __init__(
        self,
        server_config: ServerConfig,
        server_connection: ServerConnection,
        event_queue: asyncio.Queue,
    ):
        super().__init__(event_queue)
        self.server_config = server_config
        self.server_connection = server_connection
        self._platform_name = f"minecraft_{server_config.server_id}"
        self._running = False

    def meta(self) -> PlatformMetadata:
        return PlatformMetadata(
            name=self._platform_name,
            description=f"Minecraft Server: {self.server_config.server_id}",
        )

    async def send_by_session(
        self, session: MessageSesion, message_chain: MessageChain
    ):
        """Send message by session."""
        # Extract text content
        content_parts = []
        for component in message_chain.chain:
            if isinstance(component, Plain):
                content_parts.append(component.text)

        content = "".join(content_parts)
        if not content:
            return

        # Parse session format: minecraft_serverid:MessageType:identifier
        # Examples:
        #   - minecraft_survival:FriendMessage:550e8400-e29b-41d4-a716-446655440000
        #   - minecraft_survival:GroupMessage:Server
        session_parts = session.session_id.split(":", 2)

        if len(session_parts) < 3:
            logger.warning(
                f"[MC-{self.server_config.server_id}] Invalid session format: {session.session_id}"
            )
            return

        _, msg_type, identifier = session_parts

        if msg_type == "FriendMessage":
            # Private message to specific player
            await self.server_connection.ws_client.send_chat_response(
                reply_to="",
                target_type="PLAYER",
                chat_mode="PRIVATE",
                content=content,
                player_uuid=identifier,
            )
        else:
            # Broadcast message (GroupMessage or other types)
            await self.server_connection.ws_client.send_chat_response(
                reply_to="",
                target_type="BROADCAST",
                chat_mode="GROUP",
                content=content,
            )

        await super().send_by_session(session, message_chain)

    async def run(self):
        """Main run loop - this is managed by the plugin, not the platform."""
        self._running = True
        logger.info(f"[MC-{self.server_config.server_id}] Platform adapter started")
        # The actual connection is managed by ServerManager
        # This method just keeps the platform "alive"
        # Use asyncio.Event for proper async waiting
        self._stop_event = asyncio.Event()
        await self._stop_event.wait()

    async def stop(self):
        """Stop the platform adapter."""
        self._running = False
        if hasattr(self, "_stop_event"):
            self._stop_event.set()

    async def handle_chat_request(self, msg: MCMessage):
        """Handle incoming chat request from Minecraft."""
        if not self.server_config.enable_ai_chat:
            return

        if msg.type != MCMessageType.CHAT_REQUEST:
            return

        if not msg.source:
            return

        payload = msg.payload
        chat_mode_str = payload.get("chatMode", "GROUP")
        chat_mode = ChatMode(chat_mode_str)
        content = payload.get("content", "")

        player_uuid = msg.source.player_uuid
        player_name = msg.source.player_name

        # Create AstrBotMessage
        abm = AstrBotMessage()

        # Set message type based on chat mode
        if chat_mode == ChatMode.PRIVATE:
            abm.type = MessageType.FRIEND_MESSAGE
            abm.session_id = f"{self._platform_name}:FriendMessage:{player_uuid}"
        else:
            abm.type = MessageType.GROUP_MESSAGE
            abm.group_id = "Server"
            abm.session_id = f"{self._platform_name}:GroupMessage:Server"

        abm.self_id = self.server_config.server_id
        abm.message_id = msg.id
        abm.sender = MessageMember(user_id=player_uuid, nickname=player_name)
        abm.message = [Plain(text=content)]
        abm.message_str = content
        abm.raw_message = msg.payload

        # Create event
        event = MCMessageEvent(
            message_str=content,
            message_obj=abm,
            platform_meta=self.meta(),
            session_id=abm.session_id,
            server_connection=self.server_connection,
            chat_mode=chat_mode,
            request_id=msg.id,
            player_uuid=player_uuid,
        )

        # Commit event to queue
        self.commit_event(event)
        logger.debug(
            f"[MC-{self.server_config.server_id}] "
            f"Chat request from {player_name}: {content[:50]}..."
        )
