"""Minecraft 适配器插件的命令处理器"""

import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import File, Image, Plain

if TYPE_CHECKING:
    from ..core.server_manager import ServerManager
    from ..services.binding import BindingService
    from ..services.renderer import InfoRenderer


# 命令处理器常量
DEFAULT_LOG_LINES = 100
MAX_LOG_LINES = 1000
MIN_LOG_LINES = 1


class CustomCommandParser:
    """自定义命令映射解析器"""

    # 格式: trigger <&arg1&> <&arg2&><<>>actual_command {sender} {arg1} {arg2}
    SEPARATOR = "<<>>"

    def __init__(self, mappings: list[str]):
        """使用映射字符串初始化

        格式: "trigger <&param&><<>>actual_command {param} {sender}"
        """
        self.mappings: list[tuple[str, list[str], str]] = []
        for mapping in mappings:
            parsed = self._parse_mapping(mapping)
            if parsed:
                self.mappings.append(parsed)

    def _parse_mapping(self, mapping: str) -> tuple[str, list[str], str] | None:
        """解析映射字符串

        返回:
            tuple: (trigger_pattern, param_names, command_template) 或 None
        """
        if self.SEPARATOR not in mapping:
            return None

        trigger_part, command_part = mapping.split(self.SEPARATOR, 1)
        trigger_part = trigger_part.strip()
        command_part = command_part.strip()

        # 从触发器中提取参数占位符: <&name&>
        param_pattern = r"<&(\w+)&>"
        param_names = re.findall(param_pattern, trigger_part)

        # 构建用于匹配触发器的正则表达式模式
        # 将 <&name&> 替换为命名捕获组
        trigger_regex = trigger_part
        for param in param_names:
            trigger_regex = trigger_regex.replace(f"<&{param}&>", f"(?P<{param}>\\S+)")

        return (trigger_regex, param_names, command_part)

    def match(
        self, text: str, sender_mc_name: str | None = None
    ) -> tuple[str, dict] | None:
        """尝试将输入文本与自定义命令匹配

        返回:
            tuple: (actual_command, matched_params) 或 None
        """
        for trigger_regex, param_names, command_template in self.mappings:
            match = re.match(f"^{trigger_regex}$", text, re.IGNORECASE)
            if match:
                params = match.groupdict()
                # 添加发送者参数
                params["sender"] = sender_mc_name or ""

                # 构建实际命令
                command = command_template
                for key, value in params.items():
                    command = command.replace(f"{{{key}}}", value)

                return command, params

        return None


class CommandHandler:
    """所有 mc 命令的处理器"""

    def __init__(
        self,
        server_manager: "ServerManager",
        binding_service: "BindingService",
        renderer: "InfoRenderer",
        get_server_config,
    ):
        self.server_manager = server_manager
        self.binding_service = binding_service
        self.renderer = renderer
        self.get_server_config = get_server_config
        self._custom_parsers: dict[str, CustomCommandParser] = {}

    def register_custom_commands(self, server_id: str, mappings: list[str]):
        """为服务器注册自定义命令"""
        self._custom_parsers[server_id] = CustomCommandParser(mappings)
        logger.info(
            f"[CommandHandler] 已为服务器 {server_id} 注册了 {len(mappings)} 个自定义命令"
        )

    async def handle_help(self, event: AstrMessageEvent, server_id: str = ""):
        """显示帮助信息"""
        help_text = """📖 Minecraft 适配器指令帮助

基础指令:
  /mc help - 显示此帮助信息
  /mc status [服务器ID] - 查看服务器状态
  /mc list [服务器ID] - 查看在线玩家列表
  /mc player <玩家ID> [服务器ID] - 查看玩家详细信息

远程指令:
  /mc cmd <指令> [服务器ID] - 远程执行服务器指令
  /mc log <行数> [服务器ID] - 查询服务器日志

绑定功能:
  /mc bind <游戏ID> - 绑定你的游戏ID
  /mc unbind - 解除绑定

说明:
  - [服务器ID] 为可选参数，不填则使用默认服务器
  - 使用 * 前缀可将消息转发到MC服务器（如配置）"""

        yield event.plain_result(help_text)

    async def handle_status(self, event: AstrMessageEvent, server_id: str = ""):
        """显示服务器状态"""
        server = self._get_server(server_id)
        if not server:
            yield event.plain_result(f"❌ 服务器 {server_id or '默认'} 未找到或未连接")
            return

        # 通过 REST API 获取服务器信息
        info, err = await server.rest_client.get_server_info()
        if not info:
            yield event.plain_result(f"❌ 获取服务器信息失败: {err}")
            return

        status, err = await server.rest_client.get_server_status()
        if not status:
            yield event.plain_result(f"❌ 获取服务器状态失败: {err}")
            return

        # 渲染结果
        config = self.get_server_config(server.server_id)
        use_image = config.text2image if config else True

        result = await self.renderer.render_server_status(
            info, status, as_image=use_image
        )

        if result.is_image:
            yield MessageChain([Image.fromBytes(result.image.getvalue())])
        else:
            yield event.plain_result(result.text)

    async def handle_list(self, event: AstrMessageEvent, server_id: str = ""):
        """显示在线玩家列表"""
        server = self._get_server(server_id)
        if not server:
            yield event.plain_result(f"❌ 服务器 {server_id or '默认'} 未找到或未连接")
            return

        players, total, err = await server.rest_client.get_players()
        if err:
            yield event.plain_result(f"❌ 获取玩家列表失败: {err}")
            return

        # 获取服务器名称
        server_name = ""
        if server.server_info:
            server_name = server.server_info.name

        # 渲染结果
        config = self.get_server_config(server.server_id)
        use_image = config.text2image if config else True

        result = await self.renderer.render_player_list(
            players, total, server_name, as_image=use_image
        )

        if result.is_image:
            yield MessageChain([Image.fromBytes(result.image.getvalue())])
        else:
            yield event.plain_result(result.text)

    async def handle_player(
        self, event: AstrMessageEvent, player_id: str, server_id: str = ""
    ):
        """显示玩家详细信息"""
        if not player_id:
            yield event.plain_result("❌ 请指定玩家ID")
            return

        server = self._get_server(server_id)
        if not server:
            yield event.plain_result(f"❌ 服务器 {server_id or '默认'} 未找到或未连接")
            return

        # 首先通过名称尝试
        player, err = await server.rest_client.get_player_by_name(player_id)
        if not player:
            yield event.plain_result(f"❌ 获取玩家信息失败: {err}")
            return

        # 渲染结果
        config = self.get_server_config(server.server_id)
        use_image = config.text2image if config else True

        result = await self.renderer.render_player_detail(player, as_image=use_image)

        if result.is_image:
            yield MessageChain([Image.fromBytes(result.image.getvalue())])
        else:
            yield event.plain_result(result.text)

    async def handle_cmd(
        self, event: AstrMessageEvent, command: str, server_id: str = ""
    ):
        """执行远程命令"""
        if not command:
            yield event.plain_result("❌ 请指定要执行的指令")
            return

        server = self._get_server(server_id)
        if not server:
            yield event.plain_result(f"❌ 服务器 {server_id or '默认'} 未找到或未连接")
            return

        config = self.get_server_config(server.server_id)
        if not config or not config.cmd_enabled:
            yield event.plain_result("❌ 远程指令功能未启用")
            return

        # 检查命令白名单/黑名单
        if not self._check_command_allowed(command, config):
            yield event.plain_result("❌ 此指令不在允许列表中")
            return

        # 检查自定义命令映射
        sender_mc_name = None
        if config.bind_enable:
            platform = event.get_platform_name()
            user_id = event.get_sender_id()
            binding = self.binding_service.get_binding(platform, user_id)
            sender_mc_name = binding.mc_player_name if binding else None

        parser = self._custom_parsers.get(server.server_id)
        if parser:
            result = parser.match(command, sender_mc_name)
            if result:
                command, _ = result

        # 执行命令
        success, output, _ = await server.rest_client.execute_command(command)

        if success:
            yield event.plain_result(f"✅ 指令执行成功\n{output}")
        else:
            yield event.plain_result(f"❌ 指令执行失败: {output}")

    async def handle_log(
        self,
        event: AstrMessageEvent,
        lines: int = DEFAULT_LOG_LINES,
        server_id: str = "",
    ):
        """查询服务器日志"""
        server = self._get_server(server_id)
        if not server:
            yield event.plain_result(f"❌ 服务器 {server_id or '默认'} 未找到或未连接")
            return

        lines = min(max(MIN_LOG_LINES, lines), MAX_LOG_LINES)  # 限制到 1-1000

        logs, err = await server.rest_client.get_logs(lines=lines)
        if err:
            yield event.plain_result(f"❌ 获取日志失败: {err}")
            return

        if not logs:
            yield event.plain_result("📋 没有日志记录")
            return

        # 将日志格式化为文本文件
        log_content = []
        for log in logs:
            timestamp = datetime.fromtimestamp(log.timestamp / 1000).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            log_content.append(f"[{timestamp}] [{log.level}] {log.message}")

        log_text = "\n".join(log_content)

        # 使用 NamedTemporaryFile，设置 delete=False 以便发送后手动清理
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".log",
            prefix=f"mc_server_log_{server.server_id}_",
            delete=False,
        ) as temp_file:
            temp_file.write(log_text)
            temp_path = Path(temp_file.name)

        try:
            yield MessageChain(
                [
                    File(file=f"file://{temp_path}", name=f"server_log_{lines}.log"),
                    Plain(text=f"📋 最近 {len(logs)} 条日志"),
                ]
            )
        finally:
            # 发送后清理临时文件
            try:
                temp_path.unlink(missing_ok=True)
            except OSError as e:
                logger.warning(f"[CommandHandler] 无法清理临时文件: {e}")

    async def handle_bind(
        self, event: AstrMessageEvent, player_id: str, server_id: str = ""
    ):
        """绑定用户到 MC 玩家"""
        if not player_id:
            yield event.plain_result("❌ 请指定要绑定的游戏ID")
            return

        config = self.get_server_config(server_id) if server_id else None
        if config and not config.bind_enable:
            yield event.plain_result("❌ 绑定功能未启用")
            return

        platform = event.get_platform_name()
        user_id = event.get_sender_id()

        success, message = self.binding_service.bind(
            platform=platform,
            user_id=user_id,
            mc_player_name=player_id,
            server_id=server_id,
        )

        if success:
            yield event.plain_result(f"✅ {message}")
        else:
            yield event.plain_result(f"❌ {message}")

    async def handle_unbind(self, event: AstrMessageEvent):
        """解绑用户与 MC 玩家的绑定"""
        platform = event.get_platform_name()
        user_id = event.get_sender_id()

        success, message = self.binding_service.unbind(
            platform=platform,
            user_id=user_id,
        )

        if success:
            yield event.plain_result(f"✅ {message}")
        else:
            yield event.plain_result(f"❌ {message}")

    def _get_server(self, server_id: str = ""):
        """通过 ID 获取服务器连接，或如果未指定则获取第一个已连接的服务器"""
        if server_id:
            server = self.server_manager.get_server(server_id)
            if server and server.connected:
                return server
            return None

        # 返回第一个已连接的服务器
        connected = self.server_manager.get_connected_servers()
        return connected[0] if connected else None

    def _check_command_allowed(self, command: str, config) -> bool:
        """检查命令是否在白名单/黑名单中允许"""
        # 提取命令名（第一个单词）
        parts = command.split()
        if not parts:
            return False
        cmd_name = parts[0].lower()

        cmd_list = [c.lower() for c in config.cmd_list]

        if config.cmd_white_black_list == "white":
            # 白名单模式：仅在列表中则允许
            return cmd_name in cmd_list
        else:
            # 黑名单模式：不在列表中则允许
            return cmd_name not in cmd_list
