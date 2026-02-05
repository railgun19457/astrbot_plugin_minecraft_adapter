"""Minecraft Adapter Plugin for AstrBot.

This plugin enables communication between Minecraft servers and AstrBot,
providing AI chat, message forwarding, and server management features.
"""

import asyncio
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .core.models import MCMessage, MessageType, ServerConfig, ServerInfo
from .core.server_manager import ServerManager
from .handlers.commands import CommandHandler
from .platform.adapter import MCPlatformAdapter
from .services.binding import BindingService
from .services.message_bridge import MessageBridge
from .services.renderer import InfoRenderer


@register(
    "astrbot_plugin_minecraft_adapter",
    "AstrBot",
    "Minecraft服务器适配器插件，支持AI聊天、消息互通、服务器管理",
    "1.0.0",
    "https://github.com/AstrBotDevs/astrbot_plugin_minecraft_adapter",
)
class MinecraftAdapterPlugin(Star):
    """Main plugin class for Minecraft adapter."""

    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}

        # Get plugin data path
        plugin_data_path = (
            Path(get_astrbot_data_path()) / "plugin_data" / "astrbot_plugin_minecraft_adapter"
        )
        plugin_data_path.mkdir(parents=True, exist_ok=True)

        # Initialize services
        self.server_manager = ServerManager()
        self.binding_service = BindingService(plugin_data_path)
        self.message_bridge = MessageBridge(context, self.server_manager)

        # Server configs cache
        self._server_configs: dict[str, ServerConfig] = {}

        # Platform adapters
        self._adapters: dict[str, MCPlatformAdapter] = {}

        # Command handler
        self.command_handler: CommandHandler | None = None

        # Set up message handlers
        self.server_manager.set_message_handler(self._on_server_message)
        self.server_manager.set_connect_handler(self._on_server_connect)
        self.server_manager.set_disconnect_handler(self._on_server_disconnect)

        # Background tasks
        self._init_task: asyncio.Task | None = None

        # Load configuration and start servers
        self._init_task = asyncio.create_task(self._initialize())
        self._init_task.add_done_callback(self._on_init_done)

    def _on_init_done(self, task: asyncio.Task):
        """Callback when initialization task completes."""
        try:
            exc = task.exception()
            if exc:
                logger.error(f"[MC Adapter] Initialization failed: {exc}")
        except asyncio.CancelledError:
            pass

    async def _initialize(self):
        """Initialize the plugin."""
        if not self.config.get("enabled", True):
            logger.info("[MC Adapter] Plugin is disabled")
            return

        # Parse server configurations
        mc_servers = self.config.get("mc_servers", [])
        if not mc_servers:
            logger.warning("[MC Adapter] No servers configured")
            return

        for server_data in mc_servers:
            if not server_data.get("enabled", True):
                continue

            config = ServerConfig.from_dict(server_data)
            if not config.server_id:
                logger.warning("[MC Adapter] Skipping server with empty ID")
                continue

            self._server_configs[config.server_id] = config

            # Add server to manager
            self.server_manager.add_server(config)

            # Register with message bridge
            self.message_bridge.register_server(config)

            logger.info(f"[MC Adapter] Configured server: {config.server_id}")

        # Initialize renderer
        # Check if any server has text2image enabled
        any_text2image = any(c.text2image for c in self._server_configs.values())
        renderer = InfoRenderer(text2image_enabled=any_text2image)

        # Initialize command handler
        self.command_handler = CommandHandler(
            server_manager=self.server_manager,
            binding_service=self.binding_service,
            renderer=renderer,
            get_server_config=lambda sid: self._server_configs.get(sid),
        )

        # Register custom commands for each server
        for server_id, config in self._server_configs.items():
            if config.custom_cmd_list:
                self.command_handler.register_custom_commands(
                    server_id, config.custom_cmd_list
                )

        # Start all servers
        await self.server_manager.start_all()

        logger.info(
            f"[MC Adapter] Plugin initialized with {len(self._server_configs)} servers"
        )

    async def _on_server_message(self, server_id: str, msg: MCMessage):
        """Handle incoming message from MC server."""
        config = self._server_configs.get(server_id)
        if not config:
            return

        logger.debug(f"[MC-{server_id}] Received message type: {msg.type}")

        if msg.type == MessageType.CHAT_REQUEST:
            # AI chat request - forward to platform adapter
            adapter = self._adapters.get(server_id)
            if adapter:
                await adapter.handle_chat_request(msg)

        elif msg.type in (
            MessageType.MESSAGE_FORWARD,
            MessageType.PLAYER_JOIN,
            MessageType.PLAYER_QUIT,
        ):
            # Forward to external sessions
            await self.message_bridge.handle_mc_message(server_id, msg)

    async def _on_server_connect(self, server_id: str, info: ServerInfo):
        """Handle server connection."""
        config = self._server_configs.get(server_id)
        if not config:
            return

        logger.info(
            f"[MC-{server_id}] Connected to {info.name} "
            f"({info.platform} {info.minecraft_version})"
        )

        # Create platform adapter if AI chat is enabled
        if config.enable_ai_chat:
            server = self.server_manager.get_server(server_id)
            if server:
                adapter = MCPlatformAdapter(
                    server_config=config,
                    server_connection=server,
                    event_queue=self.context.platform_mgr.event_queue
                    if self.context.platform_mgr
                    else asyncio.Queue(),
                )
                self._adapters[server_id] = adapter

                # Register with platform manager
                if self.context.platform_mgr:
                    self.context.platform_mgr.add_platform(adapter)

                # Start adapter (non-blocking)
                asyncio.create_task(adapter.run())

                logger.info(f"[MC-{server_id}] Platform adapter registered")

    async def _on_server_disconnect(self, server_id: str, reason: str):
        """Handle server disconnection."""
        logger.warning(f"[MC-{server_id}] Disconnected: {reason}")

        # Stop platform adapter
        adapter = self._adapters.pop(server_id, None)
        if adapter:
            await adapter.stop()

    def _get_server_config(self, server_id: str) -> ServerConfig | None:
        """Get server configuration by ID."""
        return self._server_configs.get(server_id)

    # Command handlers

    @filter.command_group("mc")
    def mc_group(self):
        """Minecraft server management commands."""
        pass

    @mc_group.command("help")
    async def cmd_help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        if self.command_handler:
            async for result in self.command_handler.handle_help(event):
                yield result

    @mc_group.command("status")
    async def cmd_status(self, event: AstrMessageEvent, server_id: str = ""):
        """查看服务器状态"""
        if self.command_handler:
            async for result in self.command_handler.handle_status(event, server_id):
                yield result

    @mc_group.command("list")
    async def cmd_list(self, event: AstrMessageEvent, server_id: str = ""):
        """查看在线玩家列表"""
        if self.command_handler:
            async for result in self.command_handler.handle_list(event, server_id):
                yield result

    @mc_group.command("player")
    async def cmd_player(
        self, event: AstrMessageEvent, player_id: str, server_id: str = ""
    ):
        """查看玩家详细信息"""
        if self.command_handler:
            async for result in self.command_handler.handle_player(
                event, player_id, server_id
            ):
                yield result

    @mc_group.command("cmd")
    async def cmd_execute(
        self, event: AstrMessageEvent, command: str, server_id: str = ""
    ):
        """远程执行服务器指令"""
        if self.command_handler:
            async for result in self.command_handler.handle_cmd(
                event, command, server_id
            ):
                yield result

    @mc_group.command("log")
    async def cmd_log(
        self, event: AstrMessageEvent, lines: int = 100, server_id: str = ""
    ):
        """查询服务器日志"""
        if self.command_handler:
            async for result in self.command_handler.handle_log(
                event, lines, server_id
            ):
                yield result

    @mc_group.command("bind")
    async def cmd_bind(
        self, event: AstrMessageEvent, player_id: str, server_id: str = ""
    ):
        """绑定游戏ID"""
        if self.command_handler:
            async for result in self.command_handler.handle_bind(
                event, player_id, server_id
            ):
                yield result

    @mc_group.command("unbind")
    async def cmd_unbind(self, event: AstrMessageEvent):
        """解除绑定"""
        if self.command_handler:
            async for result in self.command_handler.handle_unbind(event):
                yield result

    # Message forwarding listener

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """Listen for messages to forward to MC server."""
        # Check if this message should be forwarded
        forwarded = await self.message_bridge.handle_external_message(event)
        if forwarded:
            # Stop event propagation if message was forwarded
            # Return nothing to indicate the message was handled
            return

    async def terminate(self):
        """Clean up when plugin is terminated."""
        logger.info("[MC Adapter] Shutting down...")

        # Stop all adapters
        for adapter in self._adapters.values():
            await adapter.stop()
        self._adapters.clear()

        # Stop all server connections
        await self.server_manager.stop_all()

        logger.info("[MC Adapter] Shutdown complete")
