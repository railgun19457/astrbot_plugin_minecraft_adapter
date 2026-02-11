"""Minecraft 平台消息事件"""

from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import Plain
from astrbot.api.platform import AstrBotMessage, PlatformMetadata

from ..core.models import ChatMode
from ..core.server_manager import ServerConnection


class MCMessageEvent(AstrMessageEvent):
    """用于 Minecraft 平台的消息事件"""

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
        """将响应消息发送回 Minecraft"""
        # 从消息链提取文本内容
        content_parts = []
        for component in message.chain:
            if isinstance(component, Plain):
                content_parts.append(component.text)

        content = "".join(content_parts)

        if not content:
            return

        # 根据聊天模式确定目标类型
        target_type = "BROADCAST" if self.chat_mode == ChatMode.GROUP else "PLAYER"

        # 通过 WebSocket 发送响应
        await self.server_connection.ws_client.send_chat_response(
            reply_to=self.request_id,
            target_type=target_type,
            chat_mode=self.chat_mode.value,
            content=content,
            player_uuid=self.player_uuid if self.chat_mode == ChatMode.PRIVATE else "",
        )

        await super().send(message)
