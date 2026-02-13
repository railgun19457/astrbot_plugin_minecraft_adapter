"""Minecraft 适配器插件的命令处理器"""

import re
from typing import TYPE_CHECKING

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import Image, Plain

if TYPE_CHECKING:
    from ..core.server_manager import ServerManager
    from ..services.binding import BindingService
    from ..services.renderer import InfoRenderer


class CustomCommandParser:
    """自定义命令映射解析器"""

    # 格式: trigger <&arg1&> <&arg2&><<>>actual_command {sender} {arg1} {arg2}
    SEPARATOR = "<<>>"

    def __init__(self, mappings: list[str]):
        """使用映射字符串初始化

        格式: "trigger <&param&><<>>actual_command {param} {sender}"
        """
        self.mappings: list[dict[str, object]] = []
        for mapping in mappings:
            parsed = self._parse_mapping(mapping)
            if parsed:
                self.mappings.append(parsed)

    def _parse_mapping(self, mapping: str) -> dict[str, object] | None:
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

        trigger_name = trigger_part.split()[0] if trigger_part else ""
        return {
            "trigger_part": trigger_part,
            "trigger_name": trigger_name,
            "trigger_regex": trigger_regex,
            "param_names": param_names,
            "command_template": command_part,
        }

    def match(
        self, text: str, sender_mc_name: str | None = None
    ) -> tuple[str, dict] | None:
        """尝试将输入文本与自定义命令匹配

        返回:
            tuple: (actual_command, matched_params) 或 None
        """
        for mapping in self.mappings:
            trigger_regex = mapping["trigger_regex"]
            command_template = mapping["command_template"]
            match = re.match(f"^{trigger_regex}$", text, re.IGNORECASE)
            if match:
                params = match.groupdict()
                # 添加发送者参数
                params["sender"] = sender_mc_name or ""

                # 构建实际命令
                command = command_template
                for key, value in params.items():
                    command = command.replace(f"{{{key}}}", value)
                    command = command.replace(f"<&{key}&>", value)

                return command, params

        return None

    def get_missing_usage(self, text: str) -> str | None:
        """If text looks like a custom command but misses params, return usage."""
        tokens = re.split(r"\s+", text.strip())
        if not tokens or not tokens[0]:
            return None

        first_token = tokens[0].lower()
        for mapping in self.mappings:
            trigger_name = str(mapping["trigger_name"]).lower()
            if not trigger_name or first_token != trigger_name:
                continue
            param_names = mapping["param_names"]
            expected_count = 1 + len(param_names)
            if len(tokens) < expected_count:
                return str(mapping["trigger_part"])

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

    async def handle_custom_command(self, event: AstrMessageEvent) -> bool:
        """Try to match and execute a custom command from the message text.

        Returns True if a custom command was matched and executed.
        """
        message_str = event.message_str.strip()
        if not message_str:
            return False

        umo = event.unified_msg_origin

        # Find servers whose target_sessions include this session
        for server_id, parser in self._custom_parsers.items():
            config = self.get_server_config(server_id)
            if not config:
                continue
            # Only match in sessions associated with this server
            if not config.target_sessions or umo not in config.target_sessions:
                continue
            if not config.cmd_enabled:
                continue

            # Get sender's bound MC name
            sender_mc_name = None
            if config.bind_enable:
                platform = event.get_platform_name()
                user_id = event.get_sender_id()
                binding = self.binding_service.get_binding(platform, user_id)
                sender_mc_name = binding.mc_player_name if binding else None

            missing_usage = parser.get_missing_usage(message_str)
            if missing_usage:
                await event.send(
                    MessageChain([Plain(text=f"❌ 参数不足，格式: {missing_usage}")])
                )
                return True

            result = parser.match(message_str, sender_mc_name)
            if result:
                command, _ = result
                server = self.server_manager.get_server(server_id)
                if not server or not server.connected:
                    await event.send(
                        MessageChain([Plain(text=f"❌ 服务器 {server_id} 未连接")])
                    )
                    return True

                success, output, _ = await server.rest_client.execute_command(command)
                if success:
                    await event.send(
                        MessageChain([Plain(text=f"✅ 指令执行成功\n{output}")])
                    )
                else:
                    await event.send(
                        MessageChain([Plain(text=f"❌ 指令执行失败: {output}")])
                    )
                return True

        return False

    async def handle_help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_text = """📖 Minecraft 适配器指令帮助

基础指令:
    /mc help - 显示此帮助信息
    /mc status [编号] - 查看服务器状态
    /mc list [编号] - 查看在线玩家列表
    /mc player <玩家ID> [编号] - 查看玩家详细信息

远程指令:
    /mc cmd [编号] <指令> - 远程执行服务器指令

绑定功能:
    /mc bind <游戏ID> [编号] - 绑定你的游戏ID
    /mc unbind - 解除绑定"""

        # 收集自定义指令列表
        custom_cmds = self._get_custom_command_triggers()
        if custom_cmds:
            help_text += "\n\n自定义指令:\n"
            for trigger in custom_cmds:
                help_text += f"  {trigger}\n"
            help_text = help_text.rstrip("\n")

        yield event.plain_result(help_text)

    async def handle_status(self, event: AstrMessageEvent, server_no: int = 0):
        """显示服务器状态"""
        server, error_msg = self._resolve_server(
            event.unified_msg_origin, server_no, command_hint="/mc status <编号>"
        )
        if not server:
            yield event.plain_result(error_msg)
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
            yield event.chain_result([Image.fromBytes(result.image.getvalue())])
        else:
            yield event.plain_result(result.text)

    async def handle_list(self, event: AstrMessageEvent, server_no: int = 0):
        """显示在线玩家列表"""
        server, error_msg = self._resolve_server(
            event.unified_msg_origin, server_no, command_hint="/mc list <编号>"
        )
        if not server:
            yield event.plain_result(error_msg)
            return

        players, total, err = await server.rest_client.get_players()
        if err:
            yield event.plain_result(f"❌ 获取玩家列表失败: {err}")
            return

        if total == 0 and players:
            total = len(players)

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
            yield event.chain_result([Image.fromBytes(result.image.getvalue())])
        else:
            yield event.plain_result(result.text)

    async def handle_player(
        self, event: AstrMessageEvent, player_id: str, server_no: int = 0
    ):
        """显示玩家详细信息"""
        if not player_id:
            yield event.plain_result("❌ 请指定玩家ID")
            return

        server, error_msg = self._resolve_server(
            event.unified_msg_origin,
            server_no,
            command_hint="/mc player <玩家ID> <编号>",
        )
        if not server:
            yield event.plain_result(error_msg)
            return
        player, err = await server.rest_client.get_player_by_name(player_id)
        if not player:
            yield event.plain_result(f"❌ 获取玩家信息失败: {err}")
            return

        # 渲染结果
        config = self.get_server_config(server.server_id)
        use_image = config.text2image if config else True

        result = await self.renderer.render_player_detail(player, as_image=use_image)

        if result.is_image:
            yield event.chain_result([Image.fromBytes(result.image.getvalue())])
        else:
            yield event.plain_result(result.text)

    async def handle_cmd(
        self, event: AstrMessageEvent, command: str, server_no: int = 0
    ):
        """执行远程命令"""
        server_no, command = self._extract_server_no(command, server_no)
        if not command:
            yield event.plain_result("❌ 请指定要执行的指令")
            return

        server, error_msg = self._resolve_server(
            event.unified_msg_origin,
            server_no,
            command_hint="/mc cmd <编号> <指令>",
        )
        if not server:
            yield event.plain_result(error_msg)
            return

        config = self.get_server_config(server.server_id)
        if not config or not config.cmd_enabled:
            yield event.plain_result("❌ 远程指令功能未启用")
            return

        # 检查命令白名单/黑名单
        if not self._check_command_allowed(command, config):
            yield event.plain_result("❌ 此指令不在允许列表中")
            return

        # 执行命令
        success, output, _ = await server.rest_client.execute_command(command)

        if success:
            yield event.plain_result(f"✅ 指令执行成功\n{output}")
        else:
            yield event.plain_result(f"❌ 指令执行失败: {output}")

    async def handle_bind(
        self, event: AstrMessageEvent, player_id: str, server_no: int = 0
    ):
        """绑定用户到 MC 玩家"""
        if not player_id:
            yield event.plain_result("❌ 请指定要绑定的游戏ID")
            return

        server, error_msg = self._resolve_server(
            event.unified_msg_origin,
            server_no,
            command_hint="/mc bind <游戏ID> <编号>",
        )
        if not server:
            yield event.plain_result(error_msg)
            return

        config = self.get_server_config(server.server_id)
        if config and not config.bind_enable:
            yield event.plain_result("❌ 绑定功能未启用")
            return

        platform = event.get_platform_name()
        user_id = event.get_sender_id()

        success, message = self.binding_service.bind(
            platform=platform,
            user_id=user_id,
            mc_player_name=player_id,
            server_id=server.server_id,
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

    def _get_custom_command_triggers(self) -> list[str]:
        """获取所有服务器的自定义命令触发词列表（去重）"""
        triggers = []
        seen = set()
        for server_id, parser in self._custom_parsers.items():
            config = self.get_server_config(server_id)
            if config and config.custom_cmd_list:
                for mapping_str in config.custom_cmd_list:
                    if CustomCommandParser.SEPARATOR in mapping_str:
                        trigger_part = mapping_str.split(
                            CustomCommandParser.SEPARATOR, 1
                        )[0].strip()
                        if trigger_part not in seen:
                            seen.add(trigger_part)
                            triggers.append(trigger_part)
        return triggers

    def _get_session_servers(self, umo: str) -> list:
        if not umo:
            return []
        servers = []
        for server in self.server_manager.get_connected_servers():
            config = self.get_server_config(server.server_id)
            if config and config.target_sessions and umo in config.target_sessions:
                servers.append(server)
        return servers

    def _format_server_choices(self, servers: list) -> str:
        lines = []
        for idx, server in enumerate(servers, start=1):
            name = server.server_info.name if server.server_info else ""
            name_part = f" ({name})" if name else ""
            lines.append(f"{idx}. {server.server_id}{name_part}")
        return "\n".join(lines)

    def _resolve_server(
        self, umo: str, server_no: int, command_hint: str
    ) -> tuple[object | None, str]:
        servers = self._get_session_servers(umo)
        if not servers:
            return (
                None,
                "❌ 当前会话未关联任何服务器，请在插件配置中将此会话添加到服务器的目标会话列表",
            )

        if server_no <= 0:
            if len(servers) == 1:
                return servers[0], ""
            choices = self._format_server_choices(servers)
            return (
                None,
                "⚠️ 当前会话关联多个服务器，请使用编号指定:\n"
                f"{choices}\n"
                f"示例: {command_hint}",
            )

        if server_no > len(servers):
            choices = self._format_server_choices(servers)
            return (
                None,
                "❌ 服务器编号无效，请使用以下编号:\n"
                f"{choices}\n"
                f"示例: {command_hint}",
            )

        return servers[server_no - 1], ""

    def _extract_server_no(self, command: str, server_no: int) -> tuple[int, str]:
        if server_no > 0:
            return server_no, command
        tokens = command.split()
        if tokens and tokens[0].isdigit():
            return int(tokens[0]), " ".join(tokens[1:]).strip()
        return 0, command

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
