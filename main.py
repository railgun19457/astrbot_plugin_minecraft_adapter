"""
AstrBot Minecraft Adapter Plugin
用于连接 Minecraft 服务器的 AstrBot 插件
支持 WebSocket 实时通信和 REST API
"""

from __future__ import annotations

import asyncio
import json

import aiohttp
import websockets

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star


class MinecraftAdapter(Star):
    """Minecraft 服务器适配器插件"""

    def __init__(self, context: Context, config):
        super().__init__(context)
        self.context = context
        self.config = config

        # 配置项
        self.enabled = config.get("enabled", False)
        self.ws_host = config.get("websocket_host", "localhost")
        self.ws_port = config.get("websocket_port", 8765)
        self.ws_token = config.get("websocket_token", "")
        self.rest_api_host = config.get("rest_api_host", "localhost")
        self.rest_api_port = config.get("rest_api_port", 8766)
        self.rest_api_token = config.get("rest_api_token", "")
        self.auto_reconnect = config.get("auto_reconnect", True)
        self.reconnect_interval = config.get("reconnect_interval", 5)
        self.forward_chat = config.get("forward_chat_to_astrbot", True)
        self.forward_join_leave = config.get("forward_join_leave_to_astrbot", True)
        self.status_check_interval = config.get("status_check_interval", 300)

        # 自动转发配置
        self.auto_forward_prefix = config.get("auto_forward_prefix", "")
        self.auto_forward_sessions = config.get("auto_forward_sessions", [])
        # 如果是字符串格式（兼容旧配置），转换为列表
        if isinstance(self.auto_forward_sessions, str):
            if self.auto_forward_sessions.strip():
                self.auto_forward_sessions = [
                    line.strip()
                    for line in self.auto_forward_sessions.strip().split("\n")
                    if line.strip() and not line.strip().startswith("#")
                ]
            else:
                self.auto_forward_sessions = []

        if self.auto_forward_prefix and self.auto_forward_sessions:
            logger.info(
                f"[MC适配器] 自动转发已启用 | 前缀: '{self.auto_forward_prefix}' | 监听 {len(self.auto_forward_sessions)} 个会话"
            )
        elif self.auto_forward_prefix:
            logger.info(
                f"[MC适配器] 自动转发已启用 | 前缀: '{self.auto_forward_prefix}' | 监听所有会话"
            )

        # 解析转发目标会话
        self.forward_targets = config.get("forward_target_session", [])
        # 如果是字符串格式（兼容旧配置），转换为列表
        if isinstance(self.forward_targets, str):
            if self.forward_targets.strip():
                self.forward_targets = [
                    line.strip()
                    for line in self.forward_targets.strip().split("\n")
                    if line.strip() and not line.strip().startswith("#")
                ]
            else:
                self.forward_targets = []

        if self.forward_targets:
            logger.info(f"[MC适配器] 已配置 {len(self.forward_targets)} 个消息转发目标")

        # 运行状态
        self.ws: websockets.WebSocketClientProtocol | None = None
        self.authenticated = False
        self.running = False
        self.ws_task: asyncio.Task | None = None
        self.reconnect_task: asyncio.Task | None = None
        self.status_task: asyncio.Task | None = None
        self.last_status = {}

        # 启动插件
        if self.enabled and self.ws_token:
            asyncio.create_task(self._start())
            logger.info("[MC适配器] 插件已启用，正在连接到服务器...")
        elif self.enabled and not self.ws_token:
            logger.warning(
                "[MC适配器] 插件已启用但未配置 Token，请在配置中设置 websocket_token"
            )
        else:
            logger.info("[MC适配器] 插件未启用")

    async def _start(self):
        """启动插件"""
        logger.info(f"[MC适配器] 启动插件实例: {id(self)}")
        self.running = True
        self.ws_task = asyncio.create_task(self._ws_connect())
        if self.status_check_interval > 0:
            self.status_task = asyncio.create_task(self._status_check_loop())

    def _is_ws_connected(self) -> bool:
        """检查 WebSocket 是否已连接"""
        return self.ws is not None and self.ws.close_code is None

    async def _ws_connect(self):
        """连接到 WebSocket 服务器"""
        while self.running:
            try:
                uri = f"ws://{self.ws_host}:{self.ws_port}"
                logger.info(f"[MC适配器] 正在连接到 {uri}...")

                async with websockets.connect(uri) as ws:
                    self.ws = ws
                    self.authenticated = False
                    logger.info("[MC适配器] WebSocket 连接已建立")

                    # 处理消息
                    async for message in ws:
                        await self._handle_ws_message(message)

            except websockets.exceptions.ConnectionClosed:
                logger.warning("[MC适配器] WebSocket 连接已关闭")
                self.authenticated = False
                self.ws = None

            except Exception as e:
                logger.error(f"[MC适配器] WebSocket 连接错误: {e}")
                self.authenticated = False
                self.ws = None

            # 自动重连
            if self.running and self.auto_reconnect:
                logger.info(f"[MC适配器] {self.reconnect_interval} 秒后重新连接...")
                await asyncio.sleep(self.reconnect_interval)
            else:
                break

    async def _handle_ws_message(self, message: str):
        """处理 WebSocket 消息"""
        try:
            data = json.loads(message)
            msg_type = data.get("type", "")

            if msg_type == "auth_required":
                # 发送认证
                await self._send_ws_message({"type": "auth", "token": self.ws_token})
                logger.info("[MC适配器] 已发送认证信息")

            elif msg_type == "auth_success":
                self.authenticated = True
                logger.info(f"[MC适配器] ✅ 认证成功 (实例: {id(self)})")

            elif msg_type == "auth_failed":
                logger.error("[MC适配器] ❌ 认证失败，请检查 Token")
                self.authenticated = False
                self.running = False

            elif msg_type == "chat" and self.forward_chat:
                # 玩家聊天消息
                player = data.get("player", "Unknown")
                msg = data.get("message", "")
                await self._forward_to_astrbot(f"[MC] <{player}> {msg}")

            elif msg_type == "player_join" and self.forward_join_leave:
                # 玩家加入
                player = data.get("player", "Unknown")
                await self._forward_to_astrbot(f"[MC] ➕ {player} 加入了游戏")

            elif msg_type == "player_leave" and self.forward_join_leave:
                # 玩家离开
                player = data.get("player", "Unknown")
                await self._forward_to_astrbot(f"[MC] ➖ {player} 离开了游戏")

            elif msg_type == "status_response":
                # 服务器状态
                self.last_status = data

            elif msg_type == "error":
                error_msg = data.get("message", "Unknown error")
                logger.error(f"[MC适配器] 服务器错误: {error_msg}")

        except json.JSONDecodeError:
            logger.error(f"[MC适配器] 无法解析消息: {message}")
        except Exception as e:
            logger.error(f"[MC适配器] 处理消息时出错: {e}")

    async def _send_ws_message(self, data: dict):
        """发送 WebSocket 消息"""
        if self._is_ws_connected():
            await self.ws.send(json.dumps(data))
        else:
            logger.warning("[MC适配器] WebSocket 未连接，无法发送消息")

    async def _forward_to_astrbot(self, message: str):
        """转发消息到 AstrBot"""
        logger.info(f"[MC适配器] 收到消息: {message}")

        # 如果没有配置转发目标，只记录日志
        if not self.forward_targets:
            return

        # 发送到所有配置的目标会话
        from astrbot.api.event import MessageChain

        for target in self.forward_targets:
            try:
                message_chain = MessageChain().message(message)
                await self.context.send_message(target, message_chain)
                logger.debug(f"[MC适配器] 消息已转发到: {target}")
            except Exception as e:
                logger.error(f"[MC适配器] 转发消息到 {target} 失败: {e}")

    async def _status_check_loop(self):
        """定时检查服务器状态"""
        while self.running:
            await asyncio.sleep(self.status_check_interval)
            if self.authenticated:
                await self._send_ws_message({"type": "status_request"})

    async def _send_chat_to_mc(self, message: str, sender: str = None) -> bool:
        """发送聊天消息到 Minecraft"""
        if not self._is_ws_connected():
            logger.warning("[MC适配器] WebSocket 未连接，无法发送消息")
            return False

        if not self.authenticated:
            logger.warning(
                "[MC适配器] WebSocket 未认证，无法发送消息。请检查 websocket_token 配置是否正确。"
            )
            return False

        payload = {"type": "chat", "message": message}
        if sender:
            payload["sender"] = sender

        await self._send_ws_message(payload)
        return True

    async def _execute_mc_command(self, command: str) -> dict:
        """执行 Minecraft 指令"""
        if not self._is_ws_connected():
            return {"success": False, "error": "WebSocket 未连接"}

        if not self.authenticated:
            return {
                "success": False,
                "error": "WebSocket 未认证，请检查 websocket_token 配置",
            }

        await self._send_ws_message({"type": "command", "command": command})
        return {"success": True, "message": "指令已发送"}

    async def _get_server_status(self) -> dict:
        """获取服务器状态（通过 REST API）"""
        url = f"http://{self.rest_api_host}:{self.rest_api_port}/api/status"
        headers = {"Authorization": f"Bearer {self.rest_api_token}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        response = await resp.json()
                        if isinstance(response, dict) and "data" in response:
                            return response["data"]
                        return response
                    else:
                        return {"error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"error": str(e)}

    async def _get_players_info(self) -> dict:
        """获取玩家信息（通过 REST API）"""
        url = f"http://{self.rest_api_host}:{self.rest_api_port}/api/players"
        headers = {"Authorization": f"Bearer {self.rest_api_token}"}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as resp:
                    if resp.status == 200:
                        response = await resp.json()
                        if isinstance(response, dict) and "data" in response:
                            return response["data"]
                        return response
                    else:
                        return {"error": f"HTTP {resp.status}"}
        except Exception as e:
            return {"error": str(e)}

    def _format_status(self, status: dict) -> str:
        """格式化服务器状态信息"""
        if "error" in status:
            return f"❌ 获取状态失败: {status['error']}"

        lines = ["📊 Minecraft 服务器状态"]
        lines.append(f"🟢 在线: {status.get('online', False)}")

        if status.get("online"):
            lines.append(f"📦 版本: {status.get('minecraft_version', 'Unknown')}")
            lines.append(
                f"👥 玩家: {status.get('online_players', 0)}/{status.get('max_players', 0)}"
            )

            if "tps" in status:
                tps = status["tps"]
                lines.append(f"⚡ TPS: {tps[0]:.1f} / {tps[1]:.1f} / {tps[2]:.1f}")

            if "memory" in status:
                mem = status["memory"]
                lines.append(
                    f"💾 内存: {mem.get('used_mb', 0)}MB / {mem.get('max_mb', 0)}MB ({mem.get('usage_percent', 0):.1f}%)"
                )

            if "players" in status:
                players = status["players"]
                if players:
                    lines.append(f"👤 在线玩家: {', '.join(players)}")

        return "\n".join(lines)

    def _format_players(self, players_data: dict) -> str:
        """格式化玩家信息"""
        if "error" in players_data:
            return f"❌ 获取玩家信息失败: {players_data['error']}"

        lines = ["👥 玩家列表"]
        lines.append(
            f"在线: {players_data.get('online', 0)}/{players_data.get('max', 0)}"
        )

        players = players_data.get("list", [])
        if not players:
            lines.append("当前无玩家在线")
        else:
            for player in players:
                name = player.get("name", "Unknown")
                health = player.get("health", 0)
                max_health = player.get("max_health", 20)
                level = player.get("level", 0)
                gamemode = player.get("gamemode", "UNKNOWN")
                world = player.get("world", "unknown")
                ping = player.get("ping", 0)

                lines.append(
                    f"• {name} | ❤️{health:.0f}/{max_health:.0f} | Lv.{level} | {gamemode} | {world} | {ping}ms"
                )

        return "\n".join(lines)

    def _check_status(self) -> str | None:
        """检查插件状态，返回错误消息或 None"""
        if not self.enabled:
            return "❌ Minecraft 适配器未启用"
        return None

    async def _get_sender_display_name(self, event: AstrMessageEvent) -> str:
        """获取发送者的显示名称，优先使用群昵称（群名片）

        Returns:
            str: 发送者的显示名称，优先级: 群名片 > 群昵称 > QQ昵称 > "AstrBot"
        """
        # 默认值
        default_name = "AstrBot"

        # 尝试从 event 中获取基本昵称
        sender_name = event.get_sender_name()
        if sender_name:
            default_name = sender_name

        # 如果是 aiocqhttp 平台的群聊消息，尝试获取群名片
        try:
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
                AiocqhttpMessageEvent,
            )

            if not isinstance(event, AiocqhttpMessageEvent):
                return default_name

            # 检查是否是群聊
            group_id = event.get_group_id()
            if not group_id:
                return default_name

            # 获取 bot 实例
            bot = getattr(event, "bot", None)
            if not bot or not hasattr(bot, "call_action"):
                return default_name

            # 获取发送者的 QQ 号
            sender_id = event.get_sender_id()
            if not sender_id:
                return default_name

            # 调用 API 获取群成员信息
            try:
                member_info = await bot.call_action(
                    "get_group_member_info",
                    group_id=int(group_id),
                    user_id=int(sender_id),
                    no_cache=False,
                )

                # 优先使用群名片（card），如果没有则使用昵称（nickname）
                card = member_info.get("card", "")
                nickname = member_info.get("nickname", "")

                if card:
                    return card
                elif nickname:
                    return nickname
                else:
                    return default_name

            except Exception as e:
                logger.debug(f"[MC适配器] 获取群成员信息失败: {e}")
                return default_name

        except ImportError:
            # aiocqhttp 模块未安装，返回默认值
            return default_name
        except Exception as e:
            logger.debug(f"[MC适配器] 获取发送者显示名称时出错: {e}")
            return default_name

    @filter.command_group("mc")
    def mc_group(self):
        """Minecraft 服务器管理指令组"""
        pass

    @mc_group.command("status")
    async def mc_status(self, event: AstrMessageEvent):
        """查看 Minecraft 服务器状态"""
        error_msg = self._check_status()
        if error_msg:
            yield event.plain_result(error_msg)
            return

        status = await self._get_server_status()
        yield event.plain_result(self._format_status(status))

    @mc_group.command("players")
    async def mc_players(self, event: AstrMessageEvent):
        """查看在线玩家列表"""
        error_msg = self._check_status()
        if error_msg:
            yield event.plain_result(error_msg)
            return

        players = await self._get_players_info()
        yield event.plain_result(self._format_players(players))

    @mc_group.command("info")
    async def mc_info(self, event: AstrMessageEvent):
        """查看插件连接状态"""
        error_msg = self._check_status()
        if error_msg:
            yield event.plain_result(error_msg)
            return

        ws_status = "❌ 未连接"
        if self._is_ws_connected():
            if self.authenticated:
                ws_status = "✅ 已连接并认证"
            else:
                ws_status = "⚠️ 已连接但未认证"

        info_text = f"""🔌 Minecraft 适配器连接状态

WebSocket:
  地址: {self.ws_host}:{self.ws_port}
  状态: {ws_status}
  自动重连: {"开启" if self.auto_reconnect else "关闭"}

REST API:
  地址: {self.rest_api_host}:{self.rest_api_port}

消息转发:
  目标数量: {len(self.forward_targets)}
  转发聊天: {"开启" if self.forward_chat else "关闭"}
  转发进出: {"开启" if self.forward_join_leave else "关闭"}"""
        yield event.plain_result(info_text)

    @mc_group.command("say")
    async def mc_say(self, event: AstrMessageEvent, message: str):
        """向服务器发送消息

        Args:
            message(string): 要发送的消息内容
        """
        error_msg = self._check_status()
        if error_msg:
            yield event.plain_result(error_msg)
            return

        # 获取发送者名称，优先使用群昵称
        sender_name = await self._get_sender_display_name(event)
        success = await self._send_chat_to_mc(message, sender_name)

        if success:
            yield event.plain_result("✅ 消息已发送到 Minecraft")
        else:
            yield event.plain_result("❌ 发送失败，请检查连接状态")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @mc_group.command("cmd")
    async def mc_cmd(self, event: AstrMessageEvent):
        """执行服务器指令（仅管理员）

        用法: <prefix>mc cmd <完整的 Minecraft 指令>
        示例: /mc cmd weather clear
        """
        error_msg = self._check_status()
        if error_msg:
            yield event.plain_result(error_msg)
            return

        # 手动解析消息内容，获取 cmd 后的所有内容
        message_str = event.message_str.strip()

        # 从 "mc" 开始查找，支持任意前缀
        # 查找 "mc cmd " 或 "mc cmd" 的位置
        mc_index = message_str.lower().find("mc")
        if mc_index == -1:
            yield event.plain_result(
                "❌ 指令格式错误\n用法: <prefix>mc cmd <完整的 Minecraft 指令>\n示例: /mc cmd weather clear"
            )
            return

        # 从 "mc" 之后开始解析
        after_mc = message_str[mc_index + 2 :].strip()  # +2 跳过 "mc"

        # 检查是否以 "cmd" 开头
        if not after_mc.lower().startswith("cmd"):
            yield event.plain_result(
                "❌ 指令格式错误\n用法: <prefix>mc cmd <完整的 Minecraft 指令>\n示例: /mc cmd weather clear"
            )
            return

        # 获取 "cmd" 之后的内容
        command = after_mc[3:].strip()  # +3 跳过 "cmd"

        if not command:
            yield event.plain_result(
                "❌ 请输入要执行的指令\n用法: <prefix>mc cmd <完整的 Minecraft 指令>\n示例: /mc cmd weather clear"
            )
            return

        result = await self._execute_mc_command(command)

        if result.get("success"):
            yield event.plain_result(f"✅ 指令已执行: {command}")
        else:
            yield event.plain_result(f"❌ 执行失败: {result.get('error', '未知错误')}")

    @mc_group.command("reconnect")
    async def mc_reconnect(self, event: AstrMessageEvent):
        """重新连接到 Minecraft 服务器"""
        error_msg = self._check_status()
        if error_msg:
            yield event.plain_result(error_msg)
            return

        yield event.plain_result("🔄 正在重新连接...")

        # 如果已连接，先断开
        if self._is_ws_connected():
            await self.ws.close()

        # 等待短暂时间让连接完全关闭
        await asyncio.sleep(0.5)

        # 等待重新连接（最多等待10秒）
        max_wait = 10
        waited = 0
        reconnect_success = False

        while waited < max_wait:
            await asyncio.sleep(1)
            waited += 1

            # 检查是否已连接并认证
            if self._is_ws_connected() and self.authenticated:
                reconnect_success = True
                break

        if reconnect_success:
            yield event.plain_result("✅ 重新连接成功！")
        else:
            # 检查连接状态给出更详细的错误信息
            if self._is_ws_connected() and not self.authenticated:
                yield event.plain_result(
                    "⚠️ 连接已建立但认证失败，请检查 websocket_token 配置"
                )
            else:
                yield event.plain_result(
                    f"❌ 重新连接失败（等待 {max_wait} 秒超时），请检查服务器是否运行"
                )

    @mc_group.command("help")
    async def mc_help(self, event: AstrMessageEvent):
        """显示 Minecraft 适配器帮助信息"""
        help_text = """🎮 Minecraft 适配器帮助

指令列表:
  /mc status - 查看服务器状态
  /mc players - 查看在线玩家
  /mc info - 查看插件连接状态
  /mc say <消息> - 向服务器发送消息
  /mc cmd <指令> - 执行服务器指令（仅管理员）
  /mc reconnect - 重新连接服务器
  /mc help - 显示此帮助"""
        yield event.plain_result(help_text)

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def auto_forward_message(self, event: AstrMessageEvent):
        """自动转发消息到 Minecraft"""
        # 检查是否启用自动转发
        if not self.auto_forward_prefix:
            return

        # 检查插件状态
        if not self.enabled or not self._is_ws_connected() or not self.authenticated:
            return

        # 获取消息内容
        message_str = event.message_str.strip()

        # 检查是否以前缀开头
        if not message_str.startswith(self.auto_forward_prefix):
            return

        # 如果配置了监听会话列表，检查当前会话是否在列表中
        if self.auto_forward_sessions:
            current_session = event.unified_msg_origin
            if current_session not in self.auto_forward_sessions:
                return

        # 移除前缀，获取实际消息内容
        actual_message = message_str[len(self.auto_forward_prefix) :].strip()

        # 如果移除前缀后消息为空，不转发
        if not actual_message:
            return

        # 获取发送者名称
        sender_name = await self._get_sender_display_name(event)

        # 转发到 Minecraft
        try:
            success = await self._send_chat_to_mc(actual_message, sender_name)
            if success:
                logger.debug(
                    f"[MC适配器] 自动转发消息: [{sender_name}] {actual_message}"
                )
                # 发送成功提示
                yield event.plain_result(
                    f"✅ 已转发到 Minecraft: [{sender_name}] {actual_message}"
                )
                # 停止事件传播，避免被其他插件处理
                event.stop_event()
            else:
                # 发送失败提示
                yield event.plain_result("❌ 转发失败，请检查 Minecraft 服务器连接状态")
        except Exception as e:
            logger.error(f"[MC适配器] 自动转发消息失败: {e}")
            yield event.plain_result(f"❌ 转发失败: {str(e)}")

    async def terminate(self):
        """可选择实现 terminate 函数，当插件被卸载/停用时会调用。"""
        logger.info(f"[MC适配器] 正在停止插件实例: {id(self)}")
        self.running = False

        # 停止所有异步任务
        tasks_to_cancel = []
        if self.ws_task and not self.ws_task.done():
            tasks_to_cancel.append(self.ws_task)
        if self.status_task and not self.status_task.done():
            tasks_to_cancel.append(self.status_task)
        if self.reconnect_task and not self.reconnect_task.done():
            tasks_to_cancel.append(self.reconnect_task)

        for task in tasks_to_cancel:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # 关闭 WebSocket 连接
        if self._is_ws_connected():
            try:
                await self.ws.close()
            except Exception as e:
                logger.debug(f"[MC适配器] 关闭 WebSocket 时出错: {e}")

        self.ws = None
        self.authenticated = False
        logger.info("[MC适配器] 插件已停止")
