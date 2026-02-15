"""Minecraft 适配器插件的命令处理器"""

import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.api.message_components import Image

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


@dataclass
class CmdTarget:
    """A selectable command target (proxy itself or a backend server)"""

    label: str  # display label
    server: object  # ServerConnection
    target_server: str | None = None  # None = execute on proxy itself


@dataclass
class PendingAction:
    """A pending action waiting for the user to select a number"""

    action: str  # The command name: "status", "list", "player", "cmd", "bind"
    args: dict[str, Any] = field(default_factory=dict)
    servers: list = field(default_factory=list)  # list of ServerConnection
    cmd_targets: list[CmdTarget] = field(
        default_factory=list
    )  # unified cmd target choices (proxy + backends)
    timestamp: float = 0.0


# Pending actions expire after 60 seconds
PENDING_ACTION_TIMEOUT = 60


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
        # Pending actions per session UMO
        self._pending_actions: dict[str, PendingAction] = {}

    def register_custom_commands(self, server_id: str, mappings: list[str]):
        """为服务器注册自定义命令"""
        self._custom_parsers[server_id] = CustomCommandParser(mappings)
        logger.info(
            f"[CommandHandler] 已为服务器 {server_id} 注册了 {len(mappings)} 个自定义命令"
        )

    async def handle_custom_command(self, event: AstrMessageEvent):
        """Try to match and execute a custom command from the message text.

        Async generator: yields results if a custom command was matched.
        Sets event extra 'custom_cmd_matched' to True if matched.

        流程: 参数解析/匹配 → 收集所有匹配的服务器目标 → 目标选择 → 执行
        (跳过黑白名单——管理员配置的自定义指令是受信任的)
        """
        message_str = event.message_str.strip()
        if not message_str:
            return

        umo = event.unified_msg_origin

        # Collect all matching servers and their resolved commands
        all_targets: list[CmdTarget] = []
        matched_command: str | None = None
        first_missing_usage: str | None = None

        for server_id, parser in self._custom_parsers.items():
            config = self.get_server_config(server_id)
            if not config:
                continue
            if not config.target_sessions or umo not in config.target_sessions:
                continue
            if not config.cmd_enabled:
                continue

            # Check missing usage (show hint from first match)
            usage = parser.get_missing_usage(message_str)
            if usage and first_missing_usage is None:
                first_missing_usage = usage

            # Get sender's bound MC name
            sender_mc_name = None
            if config.bind_enable:
                platform = event.get_platform_name()
                user_id = event.get_sender_id()
                binding = self.binding_service.get_binding(platform, user_id)
                sender_mc_name = binding.mc_player_name if binding else None

            result = parser.match(message_str, sender_mc_name)
            if result:
                command, _ = result
                matched_command = command
                server = self.server_manager.get_server(server_id)
                if not server or not server.connected:
                    continue

                # Build targets for this server (reuse common method)
                targets = await self._build_server_targets(server)
                all_targets.extend(targets)

        # If no match found but missing usage detected, show hint
        if not all_targets and first_missing_usage:
            yield event.plain_result(f"❌ 参数不足，格式: {first_missing_usage}")
            event.set_extra("custom_cmd_matched", True)
            return

        if all_targets and matched_command:
            # Execute or prompt for selection across all matching servers
            async for r in self._execute_or_select_target(
                event, all_targets, matched_command, action="custom_cmd"
            ):
                yield r
            event.set_extra("custom_cmd_matched", True)
            return

    def has_pending_action(self, umo: str) -> bool:
        """Check if a session has a valid pending action."""
        pending = self._pending_actions.get(umo)
        if not pending:
            return False
        if time.time() - pending.timestamp > PENDING_ACTION_TIMEOUT:
            del self._pending_actions[umo]
            return False
        return True

    async def dispatch_number_selection(self, event: AstrMessageEvent):
        """Dispatch a number selection to the pending action."""
        umo = event.unified_msg_origin
        pending = self._pending_actions.pop(umo, None)
        if not pending:
            return

        text = event.message_str.strip()
        if not text.isdigit():
            yield event.plain_result("❌ 请发送有效的数字编号")
            self._pending_actions[umo] = pending
            return

        idx = int(text)
        action = pending.action
        args = pending.args

        if pending.cmd_targets:
            # Unified cmd target selection (proxy + backends)
            if idx < 1 or idx > len(pending.cmd_targets):
                choices = self._format_target_choices(pending.cmd_targets)
                yield event.plain_result(f"❌ 编号无效，请从以下列表中选择:\n{choices}")
                self._pending_actions[umo] = pending
                return

            target = pending.cmd_targets[idx - 1]
            server = target.server
            target_server = target.target_server

            # Auth check only for user-initiated cmd
            if action == "cmd":
                allowed, deny_message = self._is_cmd_allowed_on_server(
                    args["command"], server
                )
                if not allowed:
                    yield event.plain_result(deny_message)
                    return
            async for result in self._do_cmd(
                event, server, args["command"], target_server=target_server
            ):
                yield result
        else:
            # Server selection (multi-server mode) for non-cmd actions
            if idx < 1 or idx > len(pending.servers):
                choices = self._format_server_choices(pending.servers)
                yield event.plain_result(f"❌ 编号无效，请从以下列表中选择:\n{choices}")
                self._pending_actions[umo] = pending
                return

            server = pending.servers[idx - 1]

            async for result in self._dispatch_server_action(
                event, action, server, args
            ):
                yield result

    async def handle_help(self, event: AstrMessageEvent):
        """显示帮助信息"""
        help_text = """📖 Minecraft 适配器指令帮助

基础指令:
    /mc help - 显示此帮助信息
    /mc status - 查看服务器状态
    /mc list - 查看在线玩家列表
    /mc player <玩家ID> - 查看玩家详细信息

远程指令:
    /mc cmd <指令> - 远程执行服务器指令

绑定功能:
    /mc bind <游戏ID> - 绑定你的游戏ID
    /mc unbind - 解除绑定

多服务器: 关联多个服务器时，会显示服务器列表，发送编号选择目标"""

        # 收集自定义指令列表
        custom_cmds = self._get_custom_command_triggers()
        if custom_cmds:
            help_text += "\n\n自定义指令:\n"
            for trigger in custom_cmds:
                help_text += f"  {trigger}\n"
            help_text = help_text.rstrip("\n")

        yield event.plain_result(help_text)

    async def handle_status(self, event: AstrMessageEvent):
        """显示服务器状态"""
        server, msg = self._resolve_server_or_pending(
            event.unified_msg_origin, action="status"
        )
        if server is None:
            if msg:
                yield event.plain_result(msg)
            return

        async for result in self._do_status(event, server):
            yield result

    async def _do_status(self, event: AstrMessageEvent, server):
        """Execute status query on a resolved server"""
        info, err = await server.rest_client.get_server_info()
        if not info:
            yield event.plain_result(f"❌ 获取服务器信息失败: {err}")
            return

        status, err = await server.rest_client.get_server_status()
        if not status:
            yield event.plain_result(f"❌ 获取服务器状态失败: {err}")
            return

        config = self.get_server_config(server.server_id)
        use_image = config.text2image if config else True

        result = await self.renderer.render_server_status(
            info, status, as_image=use_image
        )

        if result.is_image:
            yield event.chain_result([Image.fromBytes(result.image.getvalue())])
        else:
            yield event.plain_result(result.text)

    async def handle_list(self, event: AstrMessageEvent):
        """显示在线玩家列表"""
        server, msg = self._resolve_server_or_pending(
            event.unified_msg_origin, action="list"
        )
        if server is None:
            if msg:
                yield event.plain_result(msg)
            return

        async for result in self._do_list(event, server):
            yield result

    async def _do_list(self, event: AstrMessageEvent, server):
        """Execute player list query on a resolved server"""
        players, total, err = await server.rest_client.get_players()
        if err:
            yield event.plain_result(f"❌ 获取玩家列表失败: {err}")
            return

        if total == 0 and players:
            total = len(players)

        server_name = ""
        if server.server_info:
            server_name = server.server_info.name

        config = self.get_server_config(server.server_id)
        use_image = config.text2image if config else True

        result = await self.renderer.render_player_list(
            players, total, server_name, as_image=use_image
        )

        if result.is_image:
            yield event.chain_result([Image.fromBytes(result.image.getvalue())])
        else:
            yield event.plain_result(result.text)

    async def handle_player(self, event: AstrMessageEvent, player_id: str):
        """显示玩家详细信息"""
        if not player_id:
            yield event.plain_result("❌ 请指定玩家ID")
            return

        server, msg = self._resolve_server_or_pending(
            event.unified_msg_origin,
            action="player",
            args={"player_id": player_id},
        )
        if server is None:
            if msg:
                yield event.plain_result(msg)
            return

        async for result in self._do_player(event, server, player_id):
            yield result

    async def _do_player(self, event: AstrMessageEvent, server, player_id: str):
        """Execute player detail query on a resolved server"""
        player, err = await server.rest_client.get_player_by_name(player_id)
        if not player:
            yield event.plain_result(f"❌ 获取玩家信息失败: {err}")
            return

        config = self.get_server_config(server.server_id)
        use_image = config.text2image if config else True

        result = await self.renderer.render_player_detail(player, as_image=use_image)

        if result.is_image:
            yield event.chain_result([Image.fromBytes(result.image.getvalue())])
        else:
            yield event.plain_result(result.text)

    async def handle_cmd(self, event: AstrMessageEvent, command: str):
        """执行远程命令

        流程: 构建目标列表(含proxy展开) → cmd_enabled/黑白名单检查 → 目标选择 → 执行
        """
        if not command:
            yield event.plain_result("❌ 请指定要执行的指令")
            return

        umo = event.unified_msg_origin
        servers = self._get_session_servers(umo)
        if not servers:
            yield event.plain_result(
                "❌ 当前会话未关联任何服务器，请在插件配置中将此会话添加到服务器的目标会话列表"
            )
            return

        # Build unified target list across all servers
        all_targets = await self._build_all_cmd_targets(servers)
        if not all_targets:
            yield event.plain_result("❌ 没有可用的执行目标")
            return

        # Per-target auth checks: may differ by server config
        allowed_targets: list[CmdTarget] = []
        first_deny_message: str | None = None
        for target in all_targets:
            allowed, deny_message = self._is_cmd_allowed_on_server(
                command, target.server
            )
            if allowed:
                allowed_targets.append(target)
            elif first_deny_message is None:
                first_deny_message = deny_message

        if not allowed_targets:
            yield event.plain_result(first_deny_message or "❌ 没有可用的执行目标")
            return

        # Execute or prompt for selection
        async for result in self._execute_or_select_target(
            event, allowed_targets, command, action="cmd"
        ):
            yield result

    async def _dispatch_server_action(
        self, event: AstrMessageEvent, action: str, server, args: dict
    ):
        """Dispatch non-cmd pending actions to concrete executors."""
        if action == "status":
            async for result in self._do_status(event, server):
                yield result
            return

        if action == "list":
            async for result in self._do_list(event, server):
                yield result
            return

        if action == "player":
            async for result in self._do_player(
                event, server, args.get("player_id", "")
            ):
                yield result
            return

        if action == "bind":
            async for result in self._do_bind(event, server, args.get("player_id", "")):
                yield result

    def _is_cmd_allowed_on_server(self, command: str, server) -> tuple[bool, str]:
        """Check cmd switch + whitelist/blacklist against the target server config."""
        config = self.get_server_config(server.server_id)
        if not config or not config.cmd_enabled:
            return False, "❌ 远程指令功能未启用"

        if not self._check_command_allowed(command, config):
            return False, "❌ 此指令不在允许列表中"

        return True, ""

    async def _build_all_cmd_targets(self, servers: list) -> list[CmdTarget]:
        """Build unified target list across all servers, expanding proxies."""
        all_targets: list[CmdTarget] = []
        for server in servers:
            targets = await self._build_server_targets(server)
            all_targets.extend(targets)
        return all_targets

    async def _execute_or_select_target(
        self,
        event: AstrMessageEvent,
        targets: list[CmdTarget],
        command: str,
        action: str = "cmd",
    ):
        """Execute directly if single target, otherwise prompt user to select."""
        if not targets:
            yield event.plain_result("❌ 没有可用的执行目标")
            return

        if len(targets) == 1:
            t = targets[0]
            async for result in self._do_cmd(
                event, t.server, command, target_server=t.target_server
            ):
                yield result
            return

        # Multiple targets: prompt user to select
        choices = self._format_target_choices(targets)
        umo = event.unified_msg_origin
        self._pending_actions[umo] = PendingAction(
            action=action,
            args={"command": command},
            cmd_targets=targets,
            timestamp=time.time(),
        )
        yield event.plain_result(f"⚠️ 请选择执行目标:\n{choices}")

    async def _do_cmd(
        self,
        event: AstrMessageEvent,
        server,
        command: str,
        target_server: str | None = None,
    ):
        """Pure command executor — sends command to server and yields result.

        No auth/permission checks here. Callers are responsible for
        cmd_enabled and whitelist/blacklist checks before calling.
        """
        success, output, _ = await server.rest_client.execute_command(
            command, target_server=target_server
        )

        target_label = f" [{target_server}]" if target_server else ""
        if success:
            yield event.plain_result(f"✅{target_label} 指令执行成功\n{output}")
        else:
            yield event.plain_result(f"❌{target_label} 指令执行失败: {output}")

    async def handle_bind(self, event: AstrMessageEvent, player_id: str):
        """绑定用户到 MC 玩家"""
        if not player_id:
            yield event.plain_result("❌ 请指定要绑定的游戏ID")
            return

        server, msg = self._resolve_server_or_pending(
            event.unified_msg_origin,
            action="bind",
            args={"player_id": player_id},
        )
        if server is None:
            if msg:
                yield event.plain_result(msg)
            return

        async for result in self._do_bind(event, server, player_id):
            yield result

    async def _do_bind(self, event: AstrMessageEvent, server, player_id: str):
        """Execute bind on a resolved server"""
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
        seen: set[str] = set()
        for server_id in self._custom_parsers:
            config = self.get_server_config(server_id)
            if not config or not config.custom_cmd_list:
                continue
            for mapping_str in config.custom_cmd_list:
                if CustomCommandParser.SEPARATOR in mapping_str:
                    trigger_part = mapping_str.split(CustomCommandParser.SEPARATOR, 1)[
                        0
                    ].strip()
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
            name = (
                server.server_info.name
                if server.server_info and server.server_info.name
                else ""
            )
            name_part = f" ({name})" if name else ""
            lines.append(f"{idx}. {server.server_id}{name_part}")
        return "\n".join(lines)

    async def _server_is_proxy(self, server) -> bool:
        """Check if a server is in proxy (Velocity) mode by querying server info"""
        if server.server_info and server.server_info.is_proxy:
            return True
        info, _ = await server.rest_client.get_server_info()
        return info is not None and info.is_proxy

    async def _build_server_targets(self, server) -> list[CmdTarget]:
        """Build target list for a single server, auto-detecting proxy mode.

        For proxy servers: returns [proxy, backend1, backend2, ...]
        For standalone servers: returns [server]
        """
        if await self._server_is_proxy(server):
            return await self._build_proxy_targets(server)

        name = (
            server.server_info.name
            if server.server_info and server.server_info.name
            else server.server_id
        )
        return [CmdTarget(label=name, server=server, target_server=None)]

    async def _build_proxy_targets(self, server) -> list[CmdTarget]:
        """Build target list for a proxy server: [proxy itself, backend1, backend2, ...]"""
        info, _ = await server.rest_client.get_server_info()
        targets: list[CmdTarget] = []
        # Proxy itself is always a valid target
        proxy_label = info.name if info and info.name else server.server_id
        targets.append(
            CmdTarget(
                label=f"{proxy_label} (代理端)", server=server, target_server=None
            )
        )
        # Add backends
        if info and info.backends:
            for b in info.backends:
                if b.name:
                    targets.append(
                        CmdTarget(label=b.name, server=server, target_server=b.name)
                    )
        return targets

    def _format_target_choices(self, targets: list[CmdTarget]) -> str:
        """Format cmd target choices for user selection"""
        lines = []
        for idx, t in enumerate(targets, start=1):
            server_id = t.server.server_id if t.server else ""
            # Show server_id as context if label differs from server_id
            if t.label and t.label != server_id:
                lines.append(f"{idx}. {t.label} [{server_id}]")
            else:
                lines.append(f"{idx}. {t.label}")
        return "\n".join(lines)

    def _resolve_server_or_pending(
        self,
        umo: str,
        action: str = "",
        args: dict | None = None,
    ) -> tuple[object | None, str]:
        """Resolve the target server for a command.

        If only one server is associated, return it directly.
        If multiple servers are associated, create a pending action and
        return the server choice prompt. Returns (None, prompt_msg) when pending.
        Returns (None, error_msg) on error.
        Returns (server, "") on success.
        """
        servers = self._get_session_servers(umo)
        if not servers:
            return (
                None,
                "❌ 当前会话未关联任何服务器，请在插件配置中将此会话添加到服务器的目标会话列表",
            )

        if len(servers) == 1:
            return servers[0], ""

        # Multiple servers: create pending action and return prompt
        choices = self._format_server_choices(servers)
        self._pending_actions[umo] = PendingAction(
            action=action,
            args=args or {},
            servers=servers,
            timestamp=time.time(),
        )
        return (
            None,
            f"⚠️ 当前会话关联多个服务器，请发送编号选择:\n{choices}",
        )

    def _check_command_allowed(self, command: str, config) -> bool:
        """检查命令是否在白名单/黑名单中允许"""
        parts = command.split()
        if not parts:
            return False
        cmd_name = parts[0].lower()

        cmd_list = [c.lower() for c in config.cmd_list]
        list_mode = (config.cmd_white_black_list or "white").lower()

        if list_mode == "none":
            return True

        if list_mode == "white":
            return cmd_name in cmd_list

        if list_mode == "black":
            return cmd_name not in cmd_list

        return cmd_name in cmd_list
