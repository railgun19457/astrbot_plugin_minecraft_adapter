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
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
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
        self.mc_command_prefix = config.get("mc_command_prefix", "/mc")
        self.admin_only = config.get("admin_only", False)

        # 解析转发目标会话
        forward_target = config.get("forward_target_session", "")
        self.forward_targets = []
        if forward_target:
            # 支持多行配置
            for line in forward_target.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    self.forward_targets.append(line)

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
                logger.info("[MC适配器] ✅ 认证成功")

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
                        return await resp.json()
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
                        return await resp.json()
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

    @filter.command("mc")
    async def handle_mc_command(self, event: AstrMessageEvent):
        """处理 Minecraft 指令"""
        # 检查权限
        if self.admin_only and not event.is_admin():
            return MessageEventResult().message("❌ 此功能仅限管理员使用")

        # 检查插件状态
        if not self.enabled:
            return MessageEventResult().message("❌ Minecraft 适配器未启用")

        # 解析指令
        message_str = event.message_str.strip()
        parts = message_str.split(maxsplit=1)

        if len(parts) < 2:
            help_text = """🎮 Minecraft 适配器帮助

指令列表:
  /mc status - 查看服务器状态
  /mc players - 查看在线玩家
  /mc info - 查看插件连接状态
  /mc say <消息> - 向服务器发送消息
  /mc cmd <指令> - 执行服务器指令
  /mc reconnect - 重新连接服务器
  /mc help - 显示此帮助
"""
            return MessageEventResult().message(help_text)

        subcommand = parts[1].split()[0].lower()

        # info - 查看插件连接状态
        if subcommand == "info":
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
            return MessageEventResult().message(info_text)

        # status - 查看服务器状态
        if subcommand == "status":
            status = await self._get_server_status()
            return MessageEventResult().message(self._format_status(status))

        # players - 查看玩家列表
        elif subcommand == "players":
            players = await self._get_players_info()
            return MessageEventResult().message(self._format_players(players))

        # say - 发送消息到 MC
        elif subcommand == "say":
            if len(parts[1].split(maxsplit=1)) < 2:
                return MessageEventResult().message("❌ 请输入要发送的消息")

            message = parts[1].split(maxsplit=1)[1]
            sender_name = event.get_sender_name() or "AstrBot"

            success = await self._send_chat_to_mc(message, sender_name)
            if success:
                return MessageEventResult().message("✅ 消息已发送到 Minecraft")
            else:
                return MessageEventResult().message("❌ 发送失败，请检查连接状态")

        # cmd - 执行指令
        elif subcommand == "cmd":
            if len(parts[1].split(maxsplit=1)) < 2:
                return MessageEventResult().message("❌ 请输入要执行的指令")

            command = parts[1].split(maxsplit=1)[1]
            result = await self._execute_mc_command(command)

            if result.get("success"):
                return MessageEventResult().message(f"✅ 指令已执行: {command}")
            else:
                return MessageEventResult().message(
                    f"❌ 执行失败: {result.get('error', '未知错误')}"
                )

        # reconnect - 重新连接
        elif subcommand == "reconnect":
            if self._is_ws_connected():
                await self.ws.close()

            return MessageEventResult().message("🔄 正在重新连接...")

        # help - 帮助
        elif subcommand == "help":
            help_text = """🎮 Minecraft 适配器帮助

指令列表:
  /mc status - 查看服务器状态
  /mc players - 查看在线玩家
  /mc info - 查看插件连接状态
  /mc say <消息> - 向服务器发送消息
  /mc cmd <指令> - 执行服务器指令
  /mc reconnect - 重新连接服务器
  /mc help - 显示此帮助
"""
            return MessageEventResult().message(help_text)

        else:
            return MessageEventResult().message(
                f"❌ 未知子指令: {subcommand}\n使用 /mc help 查看帮助"
            )

    async def __del__(self):
        """清理资源"""
        self.running = False
        if self._is_ws_connected():
            await self.ws.close()
        if self.ws_task:
            self.ws_task.cancel()
        if self.status_task:
            self.status_task.cancel()
        logger.info("[MC适配器] 插件已停止")
