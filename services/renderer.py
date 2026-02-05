"""Renderer service for formatting server info as images or text."""

import html
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

from astrbot.api import logger
from astrbot.core.utils.t2i.renderer import HtmlRenderer

if TYPE_CHECKING:
    from ..core.models import PlayerDetail, PlayerInfo, ServerInfo, ServerStatus


def escape(text: str) -> str:
    """Escape HTML special characters."""
    return html.escape(str(text))


@dataclass
class RenderResult:
    """Result of a render operation.

    Attributes:
        content: The rendered content as string or BytesIO for images
        is_image: True if content is an image (BytesIO), False for text (str)
    """

    content: str | BytesIO
    is_image: bool

    @property
    def text(self) -> str:
        """Get content as text (raises error if is_image is True)."""
        if self.is_image:
            raise ValueError("Cannot get text from image content")
        return str(self.content)

    @property
    def image(self) -> BytesIO:
        """Get content as image bytes (raises error if is_image is False)."""
        if not self.is_image:
            raise ValueError("Cannot get image from text content")
        return self.content  # type: ignore


class InfoRenderer:
    """Service for rendering server/player info to text or HTML.

    Note: Image rendering is handled by the Star class's html_render method.
    This class only provides text and HTML formatting.
    """

    def __init__(self, text2image_enabled: bool = True):
        self.text2image_enabled = text2image_enabled
        self._html_renderer: HtmlRenderer | None = None

    async def _ensure_renderer(self):
        """Ensure HTML renderer is initialized."""
        if self._html_renderer is None:
            self._html_renderer = HtmlRenderer()
            await self._html_renderer.initialize()

    # Main entry methods that commands.py calls

    async def render_server_status(
        self,
        server_info: "ServerInfo",
        server_status: "ServerStatus",
        as_image: bool = True,
    ) -> RenderResult:
        """Render server status as image or text.

        Args:
            server_info: Server information
            server_status: Server status metrics
            as_image: Whether to render as image (requires text2image_enabled)

        Returns:
            RenderResult containing rendered content
        """
        if as_image and self.text2image_enabled:
            try:
                await self._ensure_renderer()
                html = self.render_server_status_html(server_info, server_status)
                image_path = await self._html_renderer.render_t2i(html, use_network=False)
                # Read the image file and return as BytesIO
                with open(image_path, "rb") as f:
                    return RenderResult(BytesIO(f.read()), is_image=True)
            except Exception as e:
                logger.warning(
                    f"[Renderer] Failed to render image, fallback to text: {e}"
                )

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
        """Render player list as image or text.

        Args:
            players: List of online players
            total: Total player count
            server_name: Server name for display
            as_image: Whether to render as image (requires text2image_enabled)

        Returns:
            RenderResult containing rendered content
        """
        if as_image and self.text2image_enabled:
            try:
                await self._ensure_renderer()
                html = self.render_player_list_html(players, total, server_name)
                image_path = await self._html_renderer.render_t2i(html, use_network=False)
                # Read the image file and return as BytesIO
                with open(image_path, "rb") as f:
                    return RenderResult(BytesIO(f.read()), is_image=True)
            except Exception as e:
                logger.warning(
                    f"[Renderer] Failed to render image, fallback to text: {e}"
                )

        return RenderResult(
            self.render_player_list_text(players, total, server_name), is_image=False
        )

    async def render_player_detail(
        self,
        player: "PlayerDetail",
        as_image: bool = True,
    ) -> RenderResult:
        """Render player detail as image or text.

        Args:
            player: Player detail information
            as_image: Whether to render as image (requires text2image_enabled)

        Returns:
            RenderResult containing rendered content
        """
        if as_image and self.text2image_enabled:
            try:
                await self._ensure_renderer()
                html = self.render_player_detail_html(player)
                image_path = await self._html_renderer.render_t2i(html, use_network=False)
                # Read the image file and return as BytesIO
                with open(image_path, "rb") as f:
                    return RenderResult(BytesIO(f.read()), is_image=True)
            except Exception as e:
                logger.warning(
                    f"[Renderer] Failed to render image, fallback to text: {e}"
                )

        return RenderResult(self.render_player_detail_text(player), is_image=False)

    # Text/HTML rendering methods

    def render_server_status_text(
        self,
        server_info: "ServerInfo",
        server_status: "ServerStatus",
    ) -> str:
        """Render server status as text."""
        return self._format_server_status_text(server_info, server_status)

    def render_server_status_html(
        self,
        server_info: "ServerInfo",
        server_status: "ServerStatus",
    ) -> str:
        """Render server status as HTML for image rendering."""
        return self._format_server_status_html(server_info, server_status)

    def render_player_list_text(
        self,
        players: list["PlayerInfo"],
        total: int,
        server_name: str = "",
    ) -> str:
        """Render player list as text."""
        return self._format_player_list_text(players, total, server_name)

    def render_player_list_html(
        self,
        players: list["PlayerInfo"],
        total: int,
        server_name: str = "",
    ) -> str:
        """Render player list as HTML for image rendering."""
        return self._format_player_list_html(players, total, server_name)

    def render_player_detail_text(
        self,
        player: "PlayerDetail",
    ) -> str:
        """Render player detail as text."""
        return self._format_player_detail_text(player)

    def render_player_detail_html(
        self,
        player: "PlayerDetail",
    ) -> str:
        """Render player detail as HTML for image rendering."""
        return self._format_player_detail_html(player)

    # Text formatters

    def _format_server_status_text(
        self, info: "ServerInfo", status: "ServerStatus"
    ) -> str:
        """Format server status as text."""
        lines = [
            f"🖥️ 服务器状态 - {info.name}",
            "━━━━━━━━━━━━━━━━━━",
            f"平台: {info.platform} {info.minecraft_version}",
            f"在线玩家: {info.online_count}/{info.max_players}",
            f"运行时间: {info.uptime_formatted}",
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
        """Format player list as text."""
        title = f"👥 在线玩家 ({total}人)"
        if server_name:
            title += f" - {server_name}"

        lines = [title, "━━━━━━━━━━━━━━━━━━"]

        if not players:
            lines.append("当前没有玩家在线")
        else:
            for p in players:
                gamemode_emoji = {
                    "SURVIVAL": "⚔️",
                    "CREATIVE": "🎨",
                    "ADVENTURE": "🗺️",
                    "SPECTATOR": "👻",
                }.get(p.game_mode, "❓")
                lines.append(f"{gamemode_emoji} {p.name} | {p.world} | {p.ping}ms")

        return "\n".join(lines)

    def _format_player_detail_text(self, player: "PlayerDetail") -> str:
        """Format player detail as text."""
        lines = [
            f"👤 玩家信息 - {player.name}",
            "━━━━━━━━━━━━━━━━━━",
            f"UUID: {player.uuid[:8]}...",
            f"世界: {player.world}",
            f"模式: {player.game_mode}",
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
            f"⏱️ 在线时长: {player.online_time_formatted}",
        ]

        if player.is_op:
            lines.insert(2, "⚡ 管理员")

        return "\n".join(lines)

    # HTML formatters for image rendering

    def _format_server_status_html(
        self, info: "ServerInfo", status: "ServerStatus"
    ) -> str:
        """Format server status as HTML for image rendering."""
        # Calculate TPS color
        tps_color = (
            "#4caf50"
            if status.tps_1m >= 19
            else ("#ff9800" if status.tps_1m >= 15 else "#f44336")
        )

        # Calculate memory color
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
                    <span class="stat-value">{info.online_count}/{info.max_players}</span>
                </div>
                <div class="stat-row">
                    <span class="stat-label">运行时间</span>
                    <span class="stat-value">{escape(info.uptime_formatted)}</span>
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
        """Format player list as HTML."""
        players_html = ""
        for p in players:
            gamemode_emoji = {
                "SURVIVAL": "⚔️",
                "CREATIVE": "🎨",
                "ADVENTURE": "🗺️",
                "SPECTATOR": "👻",
            }.get(p.game_mode, "❓")

            players_html += f"""
            <div class="player-item">
                <span class="player-icon">{gamemode_emoji}</span>
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
        """Format player detail as HTML."""
        # Calculate health bar
        health_percent = (player.health / player.max_health) * 100
        health_color = (
            "#4caf50"
            if health_percent > 50
            else ("#ff9800" if health_percent > 25 else "#f44336")
        )

        # Calculate food bar
        food_percent = (player.food_level / 20) * 100

        op_badge = '<span class="op-badge">⚡ 管理员</span>' if player.is_op else ""

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
                    <span>{escape(player.game_mode)}</span>
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
                    <span>{escape(player.online_time_formatted)}</span>
                </div>
            </div>
        </body>
        </html>
        """
