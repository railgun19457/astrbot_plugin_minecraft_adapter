"""Minecraft platform message event."""

from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import Plain
from astrbot.api.platform import AstrBotMessage, PlatformMetadata

from ..core.models import ChatMode
from ..core.server_manager import ServerConnection


class MCMessageEvent(AstrMessageEvent):
    """Message event for Minecraft platform."""

    def __init__(
        self,
        message_str: str,
        message_obj: AstrBotMessage,
        platform_meta: PlatformMetadata,
        session_id: str,
        server_connection: ServerConnection,
        chat_mode: ChatMode,
        request_id: str,
        player_uuid: str,
    ):
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.server_connection = server_connection
        self.chat_mode = chat_mode
        self.request_id = request_id
        self.player_uuid = player_uuid

    async def send(self, message: MessageChain):
        """Send response message back to Minecraft."""
        # Extract text content from message chain
        content_parts = []
        for component in message.chain:
            if isinstance(component, Plain):
                content_parts.append(component.text)

        content = "".join(content_parts)

        if not content:
            return

        # Determine target type based on chat mode
        target_type = "BROADCAST" if self.chat_mode == ChatMode.GROUP else "PLAYER"

        # Send response via WebSocket
        await self.server_connection.ws_client.send_chat_response(
            reply_to=self.request_id,
            target_type=target_type,
            chat_mode=self.chat_mode.value,
            content=content,
            player_uuid=self.player_uuid if self.chat_mode == ChatMode.PRIVATE else "",
        )

        await super().send(message)
