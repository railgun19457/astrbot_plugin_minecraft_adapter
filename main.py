"""AstrBot 的 Minecraft 适配器插件

本插件实现了 Minecraft 服务器与 AstrBot 之间的通信，
提供 AI 聊天、消息转发和服务器管理功能。
"""

import asyncio
from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.star.filter.command import GreedyStr
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
    """Minecraft 适配器主插件类"""

    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}

        # 获取插件数据路径
        plugin_data_path = (
            Path(get_astrbot_data_path())
            / "plugin_data"
            / "astrbot_plugin_minecraft_adapter"
        )
        plugin_data_path.mkdir(parents=True, exist_ok=True)

        # 初始化服务
        self.server_manager = ServerManager()
        self.binding_service = BindingService(plugin_data_path)
        self.message_bridge = MessageBridge(context, self.server_manager)

        # 服务器配置缓存
        self._server_configs: dict[str, ServerConfig] = {}

        # 平台适配器
        self._adapters: dict[str, MCPlatformAdapter] = {}

        # 命令处理器
        self.command_handler: CommandHandler | None = None

        # 设置消息处理器
        self.server_manager.set_message_handler(self._on_server_message)
        self.server_manager.set_connect_handler(self._on_server_connect)
        self.server_manager.set_disconnect_handler(self._on_server_disconnect)

        # 后台任务
        self._init_task: asyncio.Task | None = None

        # 加载配置并启动服务器
        self._init_task = asyncio.create_task(self._initialize())
        self._init_task.add_done_callback(self._on_init_done)

    def _on_init_done(self, task: asyncio.Task):
        """初始化任务完成时的回调"""
        try:
            exc = task.exception()
            if exc:
                logger.error(f"[MC Adapter] 初始化失败: {exc}")
        except asyncio.CancelledError:
            pass

    async def _initialize(self):
        """初始化插件"""
        if not self.config.get("enabled", True):
            logger.info("[MC Adapter] 插件已禁用")
            return

        # 解析服务器配置
        mc_servers = self.config.get("mc_servers", [])
        if not mc_servers:
            logger.warning("[MC Adapter] 未配置任何服务器")
            return

        for server_data in mc_servers:
            if not server_data.get("enabled", True):
                continue

            config = ServerConfig.from_dict(server_data)
            if not config.server_id:
                logger.warning("[MC Adapter] 跳过 ID 为空的服务器")
                continue

            self._server_configs[config.server_id] = config

            # 将服务器添加到管理器
            self.server_manager.add_server(config)

            # 注册到消息桥接
            self.message_bridge.register_server(config)

            logger.info(f"[MC Adapter] 已配置服务器: {config.server_id}")

        # 初始化渲染器
        # 检查是否有任何服务器启用了 text2image
        any_text2image = any(c.text2image for c in self._server_configs.values())
        renderer = InfoRenderer(text2image_enabled=any_text2image)

        # 初始化命令处理器
        self.command_handler = CommandHandler(
            server_manager=self.server_manager,
            binding_service=self.binding_service,
            renderer=renderer,
            get_server_config=lambda sid: self._server_configs.get(sid),
        )

        # 为每个服务器注册自定义命令
        for server_id, config in self._server_configs.items():
            if config.custom_cmd_list:
                self.command_handler.register_custom_commands(
                    server_id, config.custom_cmd_list
                )

        # 启动所有服务器
        await self.server_manager.start_all()

        logger.info(
            f"[MC Adapter] 插件已初始化，配置了 {len(self._server_configs)} 个服务器"
        )

    async def _on_server_message(self, server_id: str, msg: MCMessage):
        """处理来自 MC 服务器的消息"""
        config = self._server_configs.get(server_id)
        if not config:
            return

        logger.debug(f"[MC-{server_id}] 收到消息类型: {msg.type}")

        if msg.type == MessageType.CHAT_REQUEST:
            payload = msg.payload or {}
            chat_mode = payload.get("chatMode", "GROUP")
            content = payload.get("content", "")
            source_server = (
                msg.source.server_name if msg.source and msg.source.server_name else ""
            )
            source_player = (
                msg.source.player_name if msg.source and msg.source.player_name else ""
            )
            source_label = source_server or server_id
            logger.info(
                f"[MC-{server_id}] 收到AI聊天消息: {source_label}"
                f"/{source_player} -> {content} [{chat_mode}]"
            )
            # AI 聊天请求 - 转发到平台适配器
            adapter = self._adapters.get(server_id)
            if adapter:
                await adapter.handle_chat_request(msg)

        elif msg.type in (
            MessageType.MESSAGE_FORWARD,
            MessageType.PLAYER_JOIN,
            MessageType.PLAYER_QUIT,
        ):
            # 转发到外部会话
            await self.message_bridge.handle_mc_message(server_id, msg)

    async def _on_server_connect(self, server_id: str, info: ServerInfo):
        """处理服务器连接"""
        config = self._server_configs.get(server_id)
        if not config:
            return

        logger.info(
            f"[MC-{server_id}] 已连接到 {info.name} "
            f"({info.platform} {info.minecraft_version})"
        )

        # 如果启用了 AI 聊天，创建平台适配器
        if config.enable_ai_chat:
            server = self.server_manager.get_server(server_id)
            if server:
                event_queue = (
                    self.context.platform_manager.event_queue
                    if self.context and self.context.platform_manager
                    else asyncio.Queue()
                )
                adapter = MCPlatformAdapter(
                    server_config=config,
                    server_connection=server,
                    event_queue=event_queue,
                )
                self._adapters[server_id] = adapter

                # 启动适配器（非阻塞）
                asyncio.create_task(adapter.run())

                logger.info(f"[MC-{server_id}] 平台适配器已注册")

    async def _on_server_disconnect(self, server_id: str, reason: str):
        """处理服务器断开连接"""
        logger.warning(f"[MC-{server_id}] 已断开连接: {reason}")

        # 停止平台适配器
        adapter = self._adapters.pop(server_id, None)
        if adapter:
            await adapter.stop()

    def _get_server_config(self, server_id: str) -> ServerConfig | None:
        """根据 ID 获取服务器配置"""
        return self._server_configs.get(server_id)

    # 命令处理器

    @filter.command_group("mc")
    def mc_group(self):
        """我的世界服务器管理命令"""
        pass

    @mc_group.command("help")
    async def cmd_help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        if self.command_handler:
            async for result in self.command_handler.handle_help(event):
                yield result

    @mc_group.command("status")
    async def cmd_status(self, event: AstrMessageEvent, server_no: int = 0):
        """查看服务器状态"""
        if self.command_handler:
            async for result in self.command_handler.handle_status(event, server_no):
                yield result

    @mc_group.command("list")
    async def cmd_list(self, event: AstrMessageEvent, server_no: int = 0):
        """查看在线玩家列表"""
        if self.command_handler:
            async for result in self.command_handler.handle_list(event, server_no):
                yield result

    @mc_group.command("player")
    async def cmd_player(
        self, event: AstrMessageEvent, player_id: str, server_no: int = 0
    ):
        """查看玩家详细信息"""
        if self.command_handler:
            async for result in self.command_handler.handle_player(
                event, player_id, server_no
            ):
                yield result

    @mc_group.command("cmd")
    async def cmd_execute(self, event: AstrMessageEvent, command=GreedyStr):
        """远程执行服务器指令"""
        if self.command_handler:
            async for result in self.command_handler.handle_cmd(event, str(command)):
                yield result

    @mc_group.command("bind")
    async def cmd_bind(
        self, event: AstrMessageEvent, player_id: str, server_no: int = 0
    ):
        """绑定游戏ID"""
        if self.command_handler:
            async for result in self.command_handler.handle_bind(
                event, player_id, server_no
            ):
                yield result

    @mc_group.command("unbind")
    async def cmd_unbind(self, event: AstrMessageEvent):
        """解除绑定"""
        if self.command_handler:
            async for result in self.command_handler.handle_unbind(event):
                yield result

    # 消息转发监听器

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """监听需要转发到 MC 服务器的消息，并处理自定义指令"""
        # 允许在未唤醒状态下直接使用 `mc ...` 指令
        if self.command_handler and not event.is_at_or_wake_command:
            text = event.get_message_str().strip()
            if text:
                parts = text.split()
                if parts and parts[0].lower() == "mc":
                    subcommand = parts[1].lower() if len(parts) > 1 else "help"
                    args = parts[2:]

                    if subcommand == "help":
                        async for result in self.command_handler.handle_help(event):
                            yield result
                        event.stop_event()
                        return

                    if subcommand == "status":
                        if args and not args[0].isdigit():
                            yield event.plain_result("❌ 服务器编号应为数字")
                            event.stop_event()
                            return
                        server_no = int(args[0]) if args else 0
                        async for result in self.command_handler.handle_status(
                            event, server_no
                        ):
                            yield result
                        event.stop_event()
                        return

                    if subcommand == "list":
                        if args and not args[0].isdigit():
                            yield event.plain_result("❌ 服务器编号应为数字")
                            event.stop_event()
                            return
                        server_no = int(args[0]) if args else 0
                        async for result in self.command_handler.handle_list(
                            event, server_no
                        ):
                            yield result
                        event.stop_event()
                        return

                    if subcommand == "player":
                        if not args:
                            yield event.plain_result("❌ 请指定玩家ID")
                            event.stop_event()
                            return
                        player_id = args[0]
                        if len(args) > 1 and not args[1].isdigit():
                            yield event.plain_result("❌ 服务器编号应为数字")
                            event.stop_event()
                            return
                        server_no = int(args[1]) if len(args) > 1 else 0
                        async for result in self.command_handler.handle_player(
                            event, player_id, server_no
                        ):
                            yield result
                        event.stop_event()
                        return

                    if subcommand == "cmd":
                        command = " ".join(args)
                        async for result in self.command_handler.handle_cmd(
                            event, command
                        ):
                            yield result
                        event.stop_event()
                        return

                    if subcommand == "bind":
                        if not args:
                            yield event.plain_result("❌ 请指定要绑定的游戏ID")
                            event.stop_event()
                            return
                        player_id = args[0]
                        if len(args) > 1 and not args[1].isdigit():
                            yield event.plain_result("❌ 服务器编号应为数字")
                            event.stop_event()
                            return
                        server_no = int(args[1]) if len(args) > 1 else 0
                        async for result in self.command_handler.handle_bind(
                            event, player_id, server_no
                        ):
                            yield result
                        event.stop_event()
                        return

                    if subcommand == "unbind":
                        async for result in self.command_handler.handle_unbind(event):
                            yield result
                        event.stop_event()
                        return

                    async for result in self.command_handler.handle_help(event):
                        yield result
                    event.stop_event()
                    return

        # 先检查自定义指令
        if self.command_handler:
            handled = await self.command_handler.handle_custom_command(event)
            if handled:
                event.stop_event()
                return

        # 检查此消息是否应该被转发
        forwarded = await self.message_bridge.handle_external_message(event)
        if forwarded:
            event.stop_event()
            return

    async def terminate(self):
        """插件终止时的清理工作"""
        logger.info("[MC Adapter] 正在关闭...")

        # 停止所有适配器
        for adapter in self._adapters.values():
            await adapter.stop()
        self._adapters.clear()

        # 停止所有服务器连接
        await self.server_manager.stop_all()

        logger.info("[MC Adapter] 关闭完成")
