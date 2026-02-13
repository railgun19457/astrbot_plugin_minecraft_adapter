"""将服务器信息格式化为图片或文本的渲染服务"""

import html
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

from astrbot.api import logger
from astrbot.core.utils.t2i.renderer import HtmlRenderer

if TYPE_CHECKING:
    from ..core.models import PlayerDetail, PlayerInfo, ServerInfo, ServerStatus


def escape(text: str) -> str:
    """转义 HTML 特殊字符"""
    return html.escape(str(text))


@dataclass
class RenderResult:
    """渲染操作的结果

    属性:
        content: 渲染的内容，字符串或图片的 BytesIO
        is_image: True 表示内容是图片 (BytesIO)，False 表示文本 (str)
    """

    content: str | BytesIO
    is_image: bool

    @property
    def text(self) -> str:
        """获取文本形式的内容（如果 is_image 为 True 则抛出错误）"""
        if self.is_image:
            raise ValueError("无法从图片内容中获取文本")
        return str(self.content)

    @property
    def image(self) -> BytesIO:
        """获取图片字节（如果 is_image 为 False 则抛出错误）"""
        if not self.is_image:
            raise ValueError("无法从文本内容中获取图片")
        return self.content  # type: ignore


class InfoRenderer:
    """将服务器/玩家信息渲染为文本或 HTML 的服务

    注意：图片渲染由 Star 类的 html_render 方法处理。
    此类仅提供文本和 HTML 格式化。
    """

    def __init__(self, text2image_enabled: bool = True):
        self.text2image_enabled = text2image_enabled
        self._html_renderer: HtmlRenderer | None = None

    async def _ensure_renderer(self):
        """确保 HTML 渲染器已初始化"""
        if self._html_renderer is None:
            self._html_renderer = HtmlRenderer()
            await self._html_renderer.initialize()

    # 命令处理器调用的主入口方法

    async def render_server_status(
        self,
        server_info: "ServerInfo",
        server_status: "ServerStatus",
        as_image: bool = True,
    ) -> RenderResult:
        """将服务器状态渲染为图片或文本

        参数:
            server_info: 服务器信息
            server_status: 服务器状态指标
            as_image: 是否渲染为图片（需要启用 text2image）

        返回:
            RenderResult 包含渲染内容
        """
        if as_image and self.text2image_enabled:
            try:
                await self._ensure_renderer()
                html = self.render_server_status_html(server_info, server_status)
                image_path = await self._html_renderer.render_custom_template(
                    tmpl_str=html,
                    tmpl_data={},
                    return_url=False,
                )
                # 读取图片文件并作为 BytesIO 返回
                with open(image_path, "rb") as f:
                    return RenderResult(BytesIO(f.read()), is_image=True)
            except Exception as e:
                logger.warning(f"[Renderer] 渲染图片失败，回退到文本模式: {e}")

        return RenderResult(
            self.render_server_status_text(server_info, server_status), is_image=False
        )

    async def render_player_list(
        self,
        players: list["PlayerInfo"],
        total: int,
        server_name: str = "",
        as_image: bool = True,
    ) -> RenderResult:
        """将玩家列表渲染为图片或文本

        参数:
            players: 在线玩家列表
            total: 玩家总数
            server_name: 用于显示的服务器名称
            as_image: 是否渲染为图片（需要启用 text2image）

        返回:
            RenderResult 包含渲染内容
        """
        if as_image and self.text2image_enabled:
            try:
                await self._ensure_renderer()
                html = self.render_player_list_html(players, total, server_name)
                image_path = await self._html_renderer.render_custom_template(
                    tmpl_str=html,
                    tmpl_data={},
                    return_url=False,
                )
                # 读取图片文件并作为 BytesIO 返回
                with open(image_path, "rb") as f:
                    return RenderResult(BytesIO(f.read()), is_image=True)
            except Exception as e:
                logger.warning(f"[Renderer] 渲染图片失败，回退到文本模式: {e}")

        return RenderResult(
            self.render_player_list_text(players, total, server_name), is_image=False
        )

    async def render_player_detail(
        self,
        player: "PlayerDetail",
        as_image: bool = True,
    ) -> RenderResult:
        """将玩家详情渲染为图片或文本

        参数:
            player: 玩家详细信息
            as_image: 是否渲染为图片（需要启用 text2image）

        返回:
            RenderResult 包含渲染内容
        """
        if as_image and self.text2image_enabled:
            try:
                await self._ensure_renderer()
                html = self.render_player_detail_html(player)
                image_path = await self._html_renderer.render_custom_template(
                    tmpl_str=html,
                    tmpl_data={},
                    return_url=False,
                )
                # 读取图片文件并作为 BytesIO 返回
                with open(image_path, "rb") as f:
                    return RenderResult(BytesIO(f.read()), is_image=True)
            except Exception as e:
                logger.warning(f"[Renderer] 渲染图片失败，回退到文本模式: {e}")

        return RenderResult(self.render_player_detail_text(player), is_image=False)

    # 文本/HTML 渲染方法

    def render_server_status_text(
        self,
        server_info: "ServerInfo",
        server_status: "ServerStatus",
    ) -> str:
        """将服务器状态渲染为文本"""
        return self._format_server_status_text(server_info, server_status)

    def render_server_status_html(
        self,
        server_info: "ServerInfo",
        server_status: "ServerStatus",
    ) -> str:
        """将服务器状态渲染为 HTML 以便进行图片渲染"""
        return self._format_server_status_html(server_info, server_status)

    def render_player_list_text(
        self,
        players: list["PlayerInfo"],
        total: int,
        server_name: str = "",
    ) -> str:
        """将玩家列表渲染为文本"""
        return self._format_player_list_text(players, total, server_name)

    def render_player_list_html(
        self,
        players: list["PlayerInfo"],
        total: int,
        server_name: str = "",
    ) -> str:
        """将玩家列表渲染为 HTML 以便进行图片渲染"""
        return self._format_player_list_html(players, total, server_name)

    def render_player_detail_text(
        self,
        player: "PlayerDetail",
    ) -> str:
        """将玩家详情渲染为文本"""
        return self._format_player_detail_text(player)

    def render_player_detail_html(
        self,
        player: "PlayerDetail",
    ) -> str:
        """将玩家详情渲染为 HTML 以便进行图片渲染"""
        return self._format_player_detail_html(player)

    # 文本格式化器

    def _format_server_status_text(
        self, info: "ServerInfo", status: "ServerStatus"
    ) -> str:
        """将服务器状态格式化为文本"""
        online_count = info.online_count or status.online_players
        max_players = info.max_players or status.max_players
        uptime_formatted = info.uptime_formatted or status.uptime_formatted
        lines = [
            f"🖥️ 服务器状态 - {info.name}",
            "━━━━━━━━━━━━━━━━━━",
            f"平台: {info.platform} {info.minecraft_version}",
            f"在线玩家: {online_count}/{max_players}",
            f"运行时间: {uptime_formatted}",
            "",
            "📊 性能指标",
            f"TPS: {status.tps_1m:.1f} / {status.tps_5m:.1f} / {status.tps_15m:.1f}",
            f"内存: {status.memory_used}MB / {status.memory_max}MB "
            f"({status.memory_usage_percent:.1f}%)",
        ]

        if status.worlds:
            lines.append("")
            lines.append("🌍 世界信息")
            for world in status.worlds:
                lines.append(
                    f"  {world['name']}: {world.get('players', 0)}人, "
                    f"{world.get('entities', 0)}实体, "
                    f"{world.get('loadedChunks', 0)}区块"
                )

        return "\n".join(lines)

    def _format_player_list_text(
        self, players: list["PlayerInfo"], total: int, server_name: str
    ) -> str:
        """将玩家列表格式化为文本"""
        title = f"👥 在线玩家 ({total}人)"
        if server_name:
            title += f" - {server_name}"

        lines = [title, "━━━━━━━━━━━━━━━━━━"]

        if not players:
            lines.append("当前没有玩家在线")
        else:
            for p in players:
                modes = {
                    "SURVIVAL": ("生存", "⚔️"),
                    "CREATIVE": ("创造", "🎨"),
                    "ADVENTURE": ("冒险", "🗺️"),
                    "SPECTATOR": ("旁观", "👻"),
                }
                mode_name, mode_emoji = modes.get(p.game_mode, ("未知", "❓"))
                if not p.game_mode and (not p.world or p.world == "未知"):
                    lines.append(f"👤 {p.name} | {p.ping}ms")
                else:
                    lines.append(f"{mode_emoji} {p.name} | {p.world} | {p.ping}ms")

        return "\n".join(lines)

    def _format_player_detail_text(self, player: "PlayerDetail") -> str:
        """将玩家详情格式化为文本"""
        modes = {
            "SURVIVAL": "生存",
            "CREATIVE": "创造",
            "ADVENTURE": "冒险",
            "SPECTATOR": "旁观",
        }
        mode_name = modes.get(player.game_mode, player.game_mode)

        lines = [
            f"👤 玩家信息 - {player.name}",
            "━━━━━━━━━━━━━━━━━━",
            f"UUID: {player.uuid[:8]}...",
            f"世界: {player.world}",
            f"模式: {mode_name}",
            f"延迟: {player.ping}ms",
            "",
            f"❤️ 生命值: {player.health:.1f}/{player.max_health:.1f}",
            f"🍖 饥饿值: {player.food_level}/20",
            f"⭐ 等级: {player.level} ({player.exp * 100:.1f}%)",
            "",
            f"📍 位置: X={player.location.get('x', 0):.1f}, "
            f"Y={player.location.get('y', 0):.1f}, "
            f"Z={player.location.get('z', 0):.1f}",
            "",
            f"⏱️ 在线时长: {player.online_time_formatted or '未知'}",
        ]

        if player.is_op:
            lines.insert(2, "⚡ 管理员")

        return "\n".join(lines)

    # 用于图片渲染的 HTML 格式化器

    def _format_server_status_html(
        self, info: "ServerInfo", status: "ServerStatus"
    ) -> str:
        """将服务器状态格式化为 HTML 以便进行图片渲染"""
        online_count = info.online_count or status.online_players
        max_players = info.max_players or status.max_players
        uptime_formatted = info.uptime_formatted or status.uptime_formatted
        # 计算 TPS 颜色
        tps_color = (
            "#4caf50"
            if status.tps_1m >= 19
            else ("#ff9800" if status.tps_1m >= 15 else "#f44336")
        )

        # 计算内存颜色
        mem_color = (
            "#4caf50"
            if status.memory_usage_percent < 70
            else ("#ff9800" if status.memory_usage_percent < 90 else "#f44336")
        )

        worlds_html = ""
        for world in status.worlds:
            worlds_html += f"""
            <div class="world-item">
                <span class="world-name">{escape(world.get("name", ""))}</span>
                <span class="world-info">
                    {world.get("players", 0)}人 |
                    {world.get("entities", 0)}实体 |
                    {world.get("loadedChunks", 0)}区块
                </span>
            </div>
            """

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: 'Microsoft YaHei', sans-serif;
                    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    color: #ffffff;
                    padding: 20px;
                    margin: 0;
                    min-width: 400px;
                }}
                .card {{
                    background: rgba(255,255,255,0.1);
                    border-radius: 12px;
                    padding: 20px;
                    margin-bottom: 15px;
                }}
                .header {{
                    font-size: 24px;
                    font-weight: bold;
                    margin-bottom: 5px;
                }}
                .subheader {{
                    color: #888;
                    font-size: 14px;
                }}
                .stat-row {{
                    display: flex;
                    justify-content: space-between;
                    margin: 10px 0;
                }}
                .stat-label {{
                    color: #aaa;
                }}
                .stat-value {{
                    font-weight: bold;
                }}
                .tps-value {{
                    color: {tps_color};
                }}
                .mem-value {{
                    color: {mem_color};
                }}
                .world-item {{
                    padding: 8px;
                    background: rgba(255,255,255,0.05);
                    border-radius: 6px;
                    margin: 5px 0;
                }}
                .world-name {{
                    font-weight: bold;
                }}
                .world-info {{
                    color: #888;
                    font-size: 12px;
                }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="header">🖥️ {escape(info.name)}</div>
                <div class="subheader">{escape(info.platform)} {escape(info.minecraft_version)}</div>
            </div>
            <div class="card">
                <div class="stat-row">
                    <span class="stat-label">在线玩家</span>
                    <span class="stat-value">{online_count}/{max_players}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">运行时间</span>
                    <span class="stat-value">{escape(uptime_formatted)}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">TPS (1m/5m/15m)</span>
                    <span class="stat-value tps-value">
                        {status.tps_1m:.1f} / {status.tps_5m:.1f} / {status.tps_15m:.1f}
                    </span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">内存使用</span>
                    <span class="stat-value mem-value">
                        {status.memory_used}MB / {status.memory_max}MB
                        ({status.memory_usage_percent:.1f}%)
                    </span>
                </div>
            </div>
            {f'<div class="card"><div class="header">🌍 世界</div>{worlds_html}</div>' if worlds_html else ""}
        </body>
        </html>
        """

    def _format_player_list_html(
        self, players: list["PlayerInfo"], total: int, server_name: str
    ) -> str:
        """将玩家列表格式化为 HTML"""
        players_html = ""
        for p in players:
            modes = {
                "SURVIVAL": ("生存", "⚔️"),
                "CREATIVE": ("创造", "🎨"),
                "ADVENTURE": ("冒险", "🗺️"),
                "SPECTATOR": ("旁观", "👻"),
            }
            mode_name, mode_emoji = modes.get(p.game_mode, ("未知", "❓"))

            if not p.game_mode and (not p.world or p.world == "未知"):
                players_html += f"""
                <div class="player-item">
                    <span class="player-icon">👤</span>
                    <span class="player-name">{escape(p.name)}</span>
                    <span class="player-info">{p.ping}ms</span>
                </div>
                """
            else:
                players_html += f"""
                <div class="player-item">
                    <span class="player-icon">{mode_emoji}</span>
                    <span class="player-name">{escape(p.name)}</span>
                    <span class="player-info">{escape(p.world)} | {p.ping}ms</span>
                </div>
                """

        if not players_html:
            players_html = '<div class="no-players">当前没有玩家在线</div>'

        title = f"👥 在线玩家 ({total}人)"
        if server_name:
            title += f" - {escape(server_name)}"

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: 'Microsoft YaHei', sans-serif;
                    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    color: #ffffff;
                    padding: 20px;
                    margin: 0;
                    min-width: 350px;
                }}
                .header {{
                    font-size: 20px;
                    font-weight: bold;
                    margin-bottom: 15px;
                }}
                .player-item {{
                    display: flex;
                    align-items: center;
                    padding: 10px;
                    background: rgba(255,255,255,0.1);
                    border-radius: 8px;
                    margin: 8px 0;
                }}
                .player-icon {{
                    font-size: 20px;
                    margin-right: 10px;
                }}
                .player-name {{
                    font-weight: bold;
                    flex: 1;
                }}
                .player-info {{
                    color: #888;
                    font-size: 12px;
                }}
                .no-players {{
                    text-align: center;
                    color: #888;
                    padding: 20px;
                }}
            </style>
        </head>
        <body>
            <div class="header">{title}</div>
            {players_html}
        </body>
        </html>
        """

    def _format_player_detail_html(self, player: "PlayerDetail") -> str:
        """将玩家详情格式化为 HTML。"""
        # 计算生命值条
        health_percent = (player.health / player.max_health) * 100
        health_color = (
            "#4caf50"
            if health_percent > 50
            else ("#ff9800" if health_percent > 25 else "#f44336")
        )

        # 计算饱食度条
        food_percent = (player.food_level / 20) * 100

        op_badge = '<span class="op-badge">⚡ 管理员</span>' if player.is_op else ""

        modes = {
            "SURVIVAL": "生存",
            "CREATIVE": "创造",
            "ADVENTURE": "冒险",
            "SPECTATOR": "旁观",
        }
        mode_name = modes.get(player.game_mode, player.game_mode)

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <style>
                body {{
                    font-family: 'Microsoft YaHei', sans-serif;
                    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                    color: #ffffff;
                    padding: 20px;
                    margin: 0;
                    min-width: 350px;
                }}
                .card {{
                    background: rgba(255,255,255,0.1);
                    border-radius: 12px;
                    padding: 15px;
                    margin-bottom: 12px;
                }}
                .header {{
                    font-size: 22px;
                    font-weight: bold;
                    display: flex;
                    align-items: center;
                    gap: 10px;
                }}
                .op-badge {{
                    background: #ffd700;
                    color: #000;
                    font-size: 12px;
                    padding: 2px 8px;
                    border-radius: 4px;
                }}
                .uuid {{
                    color: #888;
                    font-size: 12px;
                }}
                .stat-row {{
                    display: flex;
                    justify-content: space-between;
                    margin: 8px 0;
                }}
                .stat-label {{
                    color: #aaa;
                }}
                .progress-bar {{
                    height: 8px;
                    background: rgba(255,255,255,0.1);
                    border-radius: 4px;
                    margin-top: 5px;
                    overflow: hidden;
                }}
                .progress-fill {{
                    height: 100%;
                    border-radius: 4px;
                }}
                .health-fill {{
                    background: {health_color};
                    width: {health_percent}%;
                }}
                .food-fill {{
                    background: #ff9800;
                    width: {food_percent}%;
                }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="header">
                    👤 {escape(player.name)}
                    {op_badge}
                </div>
                <div class="uuid">{escape(player.uuid)}</div>
            </div>
            <div class="card">
                <div class="stat-row">
                    <span class="stat-label">❤️ 生命值</span>
                    <span>{player.health:.1f}/{player.max_health:.1f}</span>
                </div>
                <div class="progress-bar"><div class="progress-fill health-fill"></div></div>

                <div class="stat-row">
                    <span class="stat-label">🍖 饥饿值</span>
                    <span>{player.food_level}/20</span>
                </div>
                <div class="progress-bar"><div class="progress-fill food-fill"></div></div>
            </div>
            <div class="card">
                <div class="stat-row">
                    <span class="stat-label">🌍 世界</span>
                    <span>{escape(player.world)}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">🎮 模式</span>
                    <span>{escape(mode_name)}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">⭐ 等级</span>
                    <span>{player.level} ({player.exp * 100:.1f}%)</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">📡 延迟</span>
                    <span>{player.ping}ms</span>
                </div>
            </div>
            <div class="card">
                <div class="stat-row">
                    <span class="stat-label">📍 位置</span>
                    <span>X={player.location.get("x", 0):.0f} Y={player.location.get("y", 0):.0f} Z={player.location.get("z", 0):.0f}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">⏱️ 在线时长</span>
                    <span>{escape(player.online_time_formatted or "未知")}</span>
                </div>
            </div>
        </body>
        </html>
        """
