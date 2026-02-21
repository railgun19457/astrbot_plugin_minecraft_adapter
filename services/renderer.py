"""将服务器信息格式化为图片或文本的渲染服务"""

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING

from jinja2 import Environment, FileSystemLoader

from astrbot.api import logger
from astrbot.core.utils.t2i.renderer import HtmlRenderer

if TYPE_CHECKING:
    from ..core.models import (
        PlayerDetail,
        PlayerInfo,
        ServerInfo,
        ServerStatus,
    )


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

        # 初始化 Jinja2 环境
        template_dir = Path(__file__).parent.parent / "templates"
        self.env = Environment(loader=FileSystemLoader(str(template_dir)))

    async def _ensure_renderer(self):
        """确保 HTML 渲染器已初始化"""
        if self._html_renderer is None:
            self._html_renderer = HtmlRenderer()
            await self._html_renderer.initialize()

    @staticmethod
    def _is_supported_image_bytes(data: bytes) -> bool:
        """Check whether bytes look like a supported image payload."""
        if not data:
            return False
        if data.startswith(b"\xff\xd8\xff"):  # JPEG
            return True
        if data.startswith(b"\x89PNG\r\n\x1a\n"):  # PNG
            return True
        if data.startswith((b"GIF87a", b"GIF89a")):  # GIF
            return True
        if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            return True
        return False

    # 命令处理器调用的主入口方法

    async def _render_as_image(self, html_content: str) -> RenderResult | None:
        """Render HTML content to image. Returns RenderResult or None on failure."""
        try:
            await self._ensure_renderer()
            options = {
                "quality": 100,
                "device_scale_factor_level": "normal",
                "full_page": True,
                "omit_background": False,
                "type": "jpeg",
            }
            image_path = await self._html_renderer.render_custom_template(
                tmpl_str=html_content, tmpl_data={}, return_url=False, options=options
            )
            with open(image_path, "rb") as f:
                image_bytes = f.read()

            if not self._is_supported_image_bytes(image_bytes):
                preview = image_bytes[:80].decode("utf-8", errors="ignore").strip()
                logger.warning(
                    "[Renderer] t2i endpoint returned non-image payload, "
                    f"fallback to text. preview={preview!r}"
                )
                return None

            return RenderResult(BytesIO(image_bytes), is_image=True)
        except Exception as e:
            logger.warning(f"[Renderer] 渲染图片失败，回退到文本模式: {e}")
            return None

    async def render_server_status(
        self,
        server_info: "ServerInfo",
        server_status: "ServerStatus",
        as_image: bool = True,
    ) -> RenderResult:
        """将服务器状态渲染为图片或文本"""
        if as_image and self.text2image_enabled:
            html_content = self.render_server_status_html(server_info, server_status)
            result = await self._render_as_image(html_content)
            if result:
                return result

        return RenderResult(
            self._format_server_status_text(server_info, server_status), is_image=False
        )

    async def render_player_list(
        self,
        players: list["PlayerInfo"],
        total: int,
        server_name: str = "",
        as_image: bool = True,
    ) -> RenderResult:
        """将玩家列表渲染为图片或文本"""
        if as_image and self.text2image_enabled:
            html_content = self.render_player_list_html(players, total, server_name)
            result = await self._render_as_image(html_content)
            if result:
                return result

        return RenderResult(
            self._format_player_list_text(players, total, server_name), is_image=False
        )

    async def render_player_detail(
        self,
        player: "PlayerDetail",
        as_image: bool = True,
    ) -> RenderResult:
        """将玩家详情渲染为图片或文本"""
        if as_image and self.text2image_enabled:
            html_content = self.render_player_detail_html(player)
            result = await self._render_as_image(html_content)
            if result:
                return result

        return RenderResult(self._format_player_detail_text(player), is_image=False)

    # HTML 渲染方法

    def render_server_status_html(
        self,
        server_info: "ServerInfo",
        server_status: "ServerStatus",
    ) -> str:
        """将服务器状态渲染为 HTML 以便进行图片渲染"""

        # 辅助函数
        def tps_class(val):
            if val >= 19:
                return "tps-good"
            if val >= 15:
                return "tps-warn"
            return "tps-bad"

        def memory_class(percent):
            if percent < 70:
                return "tps-good"
            if percent < 90:
                return "tps-warn"
            return "tps-bad"

        def memory_color(percent):
            if percent < 70:
                return "#4caf50"
            if percent < 90:
                return "#ff9800"
            return "#f44336"

        online_count = server_info.online_count or server_status.online_players
        max_players = server_info.max_players or server_status.max_players
        uptime_formatted = (
            server_info.uptime_formatted or server_status.uptime_formatted
        )

        template = self.env.get_template("server_status.html")
        return template.render(
            info=server_info,
            status=server_status,
            online_count=online_count,
            max_players=max_players,
            uptime=uptime_formatted,
            is_proxy=server_info.is_proxy,
            backends=server_status.backends,
            aggregate_online=server_info.aggregate_online,
            aggregate_max=server_info.aggregate_max,
            tps_class=tps_class,
            memory_class=memory_class,
            memory_color=memory_color,
        )

    def render_player_list_html(
        self,
        players: list["PlayerInfo"],
        total: int,
        server_name: str = "",
    ) -> str:
        """将玩家列表渲染为 HTML 以便进行图片渲染"""

        def ping_class(ms):
            if ms < 100:
                return "ping-good"
            if ms < 200:
                return "ping-fair"
            return "ping-bad"

        # Check if players have backend server info (proxy mode)
        has_server_field = any(p.server for p in players)
        grouped: dict[str, list] = {}
        if has_server_field:
            for p in players:
                srv = p.server or "未知"
                if srv not in grouped:
                    grouped[srv] = []
                grouped[srv].append(p)

        template = self.env.get_template("player_list.html")
        return template.render(
            players=players,
            total=total,
            server_name=server_name,
            ping_class=ping_class,
            has_server_field=has_server_field,
            grouped=grouped,
        )

    def render_player_detail_html(
        self,
        player: "PlayerDetail",
    ) -> str:
        """将玩家详情渲染为 HTML 以便进行图片渲染"""
        template = self.env.get_template("player_detail.html")
        return template.render(player=player)

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
        ]

        # If proxy with backends, show aggregate info
        if info.is_proxy and info.aggregate_online > 0:
            lines.append(f"总在线: {info.aggregate_online}/{info.aggregate_max}")

        # Show proxy's own performance if available (non-proxy)
        if not status.is_proxy:
            lines.append("")
            lines.append("📊 性能指标")
            lines.append(
                f"TPS: {status.tps_1m:.1f} / {status.tps_5m:.1f} / {status.tps_15m:.1f}"
            )
            lines.append(
                f"内存: {status.memory_used}MB / {status.memory_max}MB "
                f"({status.memory_usage_percent:.1f}%)"
            )
        else:
            # Proxy server memory
            if status.memory_max > 0:
                lines.append("")
                lines.append("📊 代理端内存")
                lines.append(
                    f"内存: {status.memory_used}MB / {status.memory_max}MB "
                    f"({status.memory_usage_percent:.1f}%)"
                )

        if status.worlds:
            lines.append("")
            lines.append("🌍 世界信息")
            for world in status.worlds:
                lines.append(
                    f"  {world['name']}: {world.get('players', 0)}人, "
                    f"{world.get('entities', 0)}实体, "
                    f"{world.get('loadedChunks', 0)}区块"
                )

        # Backend server details for proxy mode
        if status.is_proxy:
            for backend in status.backends:
                lines.append("")
                lines.append(f"🔹 后端: {backend.name}")
                lines.append(f"  平台: {backend.platform} {backend.version}")
                lines.append(f"  在线: {backend.online_players}/{backend.max_players}")
                lines.append(
                    f"  TPS: {backend.tps_1m:.1f} / {backend.tps_5m:.1f} / {backend.tps_15m:.1f}"
                )
                lines.append(
                    f"  内存: {backend.memory_used}MB / {backend.memory_max}MB "
                    f"({backend.memory_usage_percent:.1f}%)"
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
            # Check if any player has a server field (proxy mode)
            has_server_field = any(p.server for p in players)

            if has_server_field:
                # Group players by backend server
                grouped: dict[str, list[PlayerInfo]] = {}
                for p in players:
                    srv = p.server or "未知"
                    if srv not in grouped:
                        grouped[srv] = []
                    grouped[srv].append(p)

                for srv_name, srv_players in grouped.items():
                    lines.append(f"\n🔹 {srv_name} ({len(srv_players)}人)")
                    for p in srv_players:
                        lines.append(self._format_player_line(p))
            else:
                for p in players:
                    lines.append(self._format_player_line(p))

        return "\n".join(lines)

    def _format_player_line(self, p: "PlayerInfo") -> str:
        """Format a single player line for text output"""
        modes = {
            "SURVIVAL": ("生存", "⚔️"),
            "CREATIVE": ("创造", "🎨"),
            "ADVENTURE": ("冒险", "🗺️"),
            "SPECTATOR": ("旁观", "👻"),
        }
        mode_name, mode_emoji = modes.get(p.game_mode, ("未知", "❓"))
        if not p.game_mode and (not p.world or p.world == "未知"):
            return f"👤 {p.name} | {p.ping}ms"
        return f"{mode_emoji} {p.name} | {p.world} | {p.ping}ms"

    def _format_player_detail_text(self, player: "PlayerDetail") -> str:
        """将玩家详情格式化为文本"""
        modes = {
            "SURVIVAL": "生存",
            "CREATIVE": "创造",
            "ADVENTURE": "冒险",
            "SPECTATOR": "旁观",
        }
        mode_name = modes.get(player.game_mode, player.game_mode or "未知")

        lines = [
            f"👤 玩家信息 - {player.name}",
            "━━━━━━━━━━━━━━━━━━",
            f"UUID: {player.uuid[:8]}...",
            f"世界: {player.world or '未知'}",
            f"模式: {mode_name}",
            f"延迟: {player.ping}ms",
            "",
            f"❤️ 生命值: {player.health:.1f}/{player.max_health:.1f}",
            f"🍖 饥饿值: {player.food_level}/20",
            f"⭐ 等级: {player.level} ({player.exp * 100:.1f}%)",
        ]

        if player.location:
            lines.append("")
            lines.append(
                f"📍 位置: X={player.location.get('x', 0):.1f}, "
                f"Y={player.location.get('y', 0):.1f}, "
                f"Z={player.location.get('z', 0):.1f}"
            )

        lines.append("")
        lines.append(f"⏱️ 在线时长: {player.online_time_formatted or '未知'}")

        if player.is_op:
            lines.insert(2, "⚡ 管理员")

        return "\n".join(lines)
