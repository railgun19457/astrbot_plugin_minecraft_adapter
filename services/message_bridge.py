"""Message bridge service for forwarding messages between MC and other platforms."""

import re
from typing import TYPE_CHECKING

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import Plain
from astrbot.core.platform.astr_message_event import MessageSesion

from ..core.models import MCMessage, MessageType, ServerConfig

if TYPE_CHECKING:
    from astrbot.core.star.context import Context

    from ..core.server_manager import ServerManager


# Emoji reaction constants for message forwarding feedback
EMOJI_OK_GESTURE = 124  # 👌
EMOJI_THUMBS_UP = 76  # 👍
EMOJI_LOVE = 66  # ❤️
EMOJI_ROSE = 63  # 🌹


class MessageBridge:
    """Service for forwarding messages between MC servers and AstrBot sessions."""

    def __init__(self, context: "Context", server_manager: "ServerManager"):
        self.context = context
        self.server_manager = server_manager
        # Map from session UMO to server configs that want to receive messages
        self._session_to_servers: dict[str, list[tuple[str, ServerConfig]]] = {}
        # Map from server_id to config
        self._server_configs: dict[str, ServerConfig] = {}

    def register_server(self, config: ServerConfig):
        """Register a server for message forwarding."""
        self._server_configs[config.server_id] = config

        # Build reverse mapping for auto-forward sessions
        for session in config.auto_forward_sessions:
            if session not in self._session_to_servers:
                self._session_to_servers[session] = []
            self._session_to_servers[session].append((config.server_id, config))

    def unregister_server(self, server_id: str):
        """Unregister a server from message forwarding."""
        config = self._server_configs.pop(server_id, None)
        if config:
            # Remove from reverse mapping
            for session in config.auto_forward_sessions:
                if session in self._session_to_servers:
                    self._session_to_servers[session] = [
                        (sid, cfg)
                        for sid, cfg in self._session_to_servers[session]
                        if sid != server_id
                    ]

    async def handle_mc_message(self, server_id: str, msg: MCMessage) -> bool:
        """Handle message from MC server and forward to target sessions.

        Returns True if the message was forwarded.
        """
        config = self._server_configs.get(server_id)
        if not config:
            return False

        # Check if forwarding is enabled
        if msg.type == MessageType.MESSAGE_FORWARD:
            if not config.forward_chat_to_astrbot:
                return False
        elif msg.type in (MessageType.PLAYER_JOIN, MessageType.PLAYER_QUIT):
            if not config.forward_join_leave_to_astrbot:
                return False
        else:
            return False

        # Get target sessions
        targets = config.forward_target_session
        if not targets:
            return False

        # Format message content
        content = self._format_mc_message(msg, config)
        if not content:
            return False

        # Send to each target session
        for target_umo in targets:
            await self._send_to_session(target_umo, content)

        return True

    def _format_mc_message(self, msg: MCMessage, config: ServerConfig) -> str:
        """Format MC message for forwarding to external platforms.

        Args:
            msg: The Minecraft message to format
            config: Server configuration containing format templates

        Returns:
            Formatted message string ready for forwarding, or empty string
            if message type is not supported for forwarding.

        Note:
            Supports MESSAGE_FORWARD, PLAYER_JOIN, and PLAYER_QUIT message types.
        """
        if msg.type == MessageType.MESSAGE_FORWARD:
            player_name = msg.source.player_name if msg.source else "Unknown"
            content = msg.payload.get("content", "")
            # Apply format template
            return config.forward_chat_format.format(
                player=player_name, message=content
            )

        elif msg.type == MessageType.PLAYER_JOIN:
            player = msg.payload.get("player", {})
            player_name = player.get("name", "Unknown")
            online = msg.payload.get("onlineCount", 0)
            max_players = msg.payload.get("maxPlayers", 0)
            return f"🟢 {player_name} 加入了服务器 ({online}/{max_players})"

        elif msg.type == MessageType.PLAYER_QUIT:
            player = msg.payload.get("player", {})
            player_name = player.get("name", "Unknown")
            online = msg.payload.get("onlineCount", 0)
            max_players = msg.payload.get("maxPlayers", 0)
            reason = msg.payload.get("reason", "QUIT")
            reason_text = {
                "QUIT": "离开",
                "KICK": "被踢出",
                "TIMEOUT": "超时断开",
            }.get(reason, "离开")
            return f"🔴 {player_name} {reason_text}了服务器 ({online}/{max_players})"

        return ""

    async def _send_to_session(self, umo: str, content: str):
        """Send message to a specific session via platform manager.

        Args:
            umo: Unified Message Origin in format 'platform:type:id'
            content: Message content to send

        Note:
            Parses UMO to find the target platform and sends via platform manager.
            Logs warnings if UMO format is invalid or platform is not found.
        """
        try:
            # Parse UMO format: platform:type:id
            parts = umo.split(":")
            if len(parts) < 3:
                logger.warning(f"[MessageBridge] Invalid UMO format: {umo}")
                return

            platform_name = parts[0]
            # msg_type = parts[1]  # GroupMessage or FriendMessage
            # session_id = ":".join(parts[2:])  # Not used, session uses full UMO

            # Create message chain
            message_chain = MessageChain([Plain(text=content)])

            # Create message session
            session = MessageSesion(
                session_id=umo,
            )

            # Get platform manager from context
            pm = self.context.platform_mgr
            if pm:
                # Find the platform
                for platform in pm.platforms:
                    if platform.meta().name == platform_name:
                        await platform.send_by_session(session, message_chain)
                        return

            logger.warning(f"[MessageBridge] Platform not found: {platform_name}")

        except Exception as e:
            logger.error(f"[MessageBridge] Failed to send message: {e}")

    async def handle_external_message(self, event: AstrMessageEvent) -> bool:
        """Handle message from external platform and forward to MC if needed.

        Returns True if the message was forwarded.
        """
        # Get the message content
        message_str = event.message_str
        umo = event.unified_msg_origin

        # Check each server config
        for server_id, config in self._server_configs.items():
            # Check if auto-forward is enabled
            if not config.auto_forward_prefix:
                continue

            # Check if this session is in the auto-forward list
            # Empty list means all sessions
            if config.auto_forward_sessions and umo not in config.auto_forward_sessions:
                continue

            # Check prefix
            if not message_str.startswith(config.auto_forward_prefix):
                continue

            # Remove prefix and forward
            content = message_str[len(config.auto_forward_prefix) :].strip()
            if not content:
                continue

            # Get sender info
            sender_name = event.get_sender_name()
            sender_id = event.get_sender_id()
            platform_name = event.get_platform_name()

            # Send to MC server
            server = self.server_manager.get_server(server_id)
            if server and server.connected:
                success = await server.ws_client.send_incoming_message(
                    platform=platform_name,
                    user_id=sender_id,
                    user_name=sender_name,
                    content=content,
                )

                if success:
                    # Send feedback based on config
                    await self._send_forward_feedback(event, config)
                    return True

        return False

    async def _send_forward_feedback(
        self, event: AstrMessageEvent, config: ServerConfig
    ):
        """Send feedback after successful message forwarding."""
        mark_option = config.mark_option

        if mark_option == "none":
            return

        elif mark_option == "emoji":
            # Try to react with emoji using napcat/onebot API
            await self._react_with_emoji(event)

        elif mark_option == "text":
            # Send text confirmation
            try:
                await event.send(MessageChain([Plain(text="✓ 消息已转发")]))
            except Exception:
                pass

    async def _react_with_emoji(
        self, event: AstrMessageEvent, emoji_id: int = EMOJI_OK_GESTURE
    ):
        """React to a message with an emoji using napcat/onebot API.

        Args:
            event: The message event to react to
            emoji_id: The emoji ID to use (default: EMOJI_OK_GESTURE)
                Common emoji IDs:
                - EMOJI_OK_GESTURE (124): 👌
                - EMOJI_THUMBS_UP (76): 👍
                - EMOJI_LOVE (66): ❤️
                - EMOJI_ROSE (63): 🌹
        """
        platform_name = event.get_platform_name()

        # Only aiocqhttp (OneBot v11) supports emoji reactions
        if platform_name != "aiocqhttp":
            return

        try:
            # Lazy import to avoid circular dependency at runtime
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
                AiocqhttpMessageEvent,
            )

            if not isinstance(event, AiocqhttpMessageEvent):
                return

            # Get the bot client
            client = event.bot
            message_id = event.message_obj.message_id

            # Call napcat/onebot API to set emoji reaction
            # API: set_msg_emoji_like
            payloads = {
                "message_id": int(message_id),
                "emoji_id": str(emoji_id),
            }

            await client.api.call_action("set_msg_emoji_like", **payloads)
            logger.debug(
                f"[MessageBridge] Reacted with emoji {emoji_id} to message {message_id}"
            )

        except Exception as e:
            # Emoji reaction failed, this is not critical
            logger.debug(f"[MessageBridge] Failed to react with emoji: {e}")

    def get_servers_for_session(self, umo: str) -> list[str]:
        """Get server IDs that want to receive messages from this session."""
        result = []
        for server_id, config in self._server_configs.items():
            if not config.auto_forward_prefix:
                continue
            if not config.auto_forward_sessions or umo in config.auto_forward_sessions:
                result.append(server_id)
        return result

    def strip_color_codes(self, text: str) -> str:
        """Remove Minecraft color codes from text."""
        # Remove § followed by any character
        return re.sub(r"§[0-9a-fk-or]", "", text)
