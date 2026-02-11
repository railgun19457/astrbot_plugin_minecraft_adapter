"""Minecraft 平台适配器，用于 AI 聊天"""

import asyncio

from astrbot.api import logger
from astrbot.api.event import MessageChain
from astrbot.api.message_components import At, Plain
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
    """用于 Minecraft 服务器的平台适配器"""

    def __init__(
        self,
        server_config: ServerConfig,
        server_connection: ServerConnection,
        event_queue: asyncio.Queue,
    ):
        super().__init__({}, event_queue)
        self.server_config = server_config
        self.server_connection = server_connection
        self._platform_name = f"minecraft_{server_config.server_id}"
        self._running = False

    def meta(self) -> PlatformMetadata:
        return PlatformMetadata(
            name=self._platform_name,
            description=f"Minecraft Server: {self.server_config.server_id}",
            id=self._platform_name,
        )

    async def send_by_session(
        self, session: MessageSesion, message_chain: MessageChain
    ):
        """通过会话发送消息"""
        # 提取文本内容
        content_parts = []
        for component in message_chain.chain:
            if isinstance(component, Plain):
                content_parts.append(component.text)

        content = "".join(content_parts)
        if not content:
            return

        # 解析会话格式: minecraft_serverid:MessageType:identifier
        # 示例:
        #   - minecraft_survival:FriendMessage:550e8400-e29b-41d4-a716-446655440000
        #   - minecraft_survival:GroupMessage:Server
        session_parts = session.session_id.split(":", 2)

        if len(session_parts) < 3:
            logger.warning(
                f"[MC-{self.server_config.server_id}] 无效的会话格式: {session.session_id}"
            )
            return

        _, msg_type, identifier = session_parts

        if msg_type == "FriendMessage":
            # 私聊给特定玩家
            await self.server_connection.ws_client.send_chat_response(
                reply_to="",
                target_type="PLAYER",
                chat_mode="PRIVATE",
                content=content,
                player_uuid=identifier,
            )
        else:
            # 广播消息 (群聊消息或其他类型)
            await self.server_connection.ws_client.send_chat_response(
                reply_to="",
                target_type="BROADCAST",
                chat_mode="GROUP",
                content=content,
            )

        await super().send_by_session(session, message_chain)

    async def run(self):
        """主运行循环 - 由插件管理，而不是平台"""
        self._running = True
        logger.info(f"[MC-{self.server_config.server_id}] 平台适配器已启动")
        # 实际连接由 ServerManager 管理
        # 此方法只是保持平台“活着”
        # 使用 asyncio.Event 进行正确的异步等待
        self._stop_event = asyncio.Event()
        await self._stop_event.wait()

    async def stop(self):
        """停止平台适配器"""
        self._running = False
        if hasattr(self, "_stop_event"):
            self._stop_event.set()

    async def handle_chat_request(self, msg: MCMessage):
        """处理来自 Minecraft 的聊天请求"""
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

        # 创建 AstrBotMessage
        abm = AstrBotMessage()

        # 根据聊天模式设置消息类型
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
        if chat_mode == ChatMode.GROUP:
            abm.message = [At(qq=abm.self_id), Plain(text=content)]
        else:
            abm.message = [Plain(text=content)]
        abm.message_str = content
        abm.raw_message = msg.payload

        # 创建事件
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

        # 将事件提交到队列
        self.commit_event(event)
        logger.debug(
            f"[MC-{self.server_config.server_id}] "
            f"来自 {player_name} 的聊天请求: {content[:50]}..."
        )
