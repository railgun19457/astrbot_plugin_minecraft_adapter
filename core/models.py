"""Minecraft 适配器插件的数据模型"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar

E = TypeVar("E", bound=Enum)


def safe_enum(enum_class: type[E], value: str, default: E) -> E:
    """安全地解析枚举值，如果无效则返回默认值"""
    try:
        return enum_class(value)
    except ValueError:
        return default


class MessageType(str, Enum):
    """根据协议定义的 WebSocket 消息类型"""

    HEARTBEAT = "HEARTBEAT"
    HEARTBEAT_ACK = "HEARTBEAT_ACK"
    CONNECTION_ACK = "CONNECTION_ACK"
    CHAT_REQUEST = "CHAT_REQUEST"
    CHAT_RESPONSE = "CHAT_RESPONSE"
    MESSAGE_FORWARD = "MESSAGE_FORWARD"
    MESSAGE_INCOMING = "MESSAGE_INCOMING"
    PLAYER_JOIN = "PLAYER_JOIN"
    PLAYER_QUIT = "PLAYER_QUIT"
    COMMAND_REQUEST = "COMMAND_REQUEST"
    COMMAND_RESPONSE = "COMMAND_RESPONSE"
    STATUS_UPDATE = "STATUS_UPDATE"
    ERROR = "ERROR"
    DISCONNECT = "DISCONNECT"


class SourceType(str, Enum):
    """消息源类型"""

    PLAYER = "PLAYER"
    SERVER = "SERVER"
    SYSTEM = "SYSTEM"


class TargetType(str, Enum):
    """消息目标类型"""

    PLAYER = "PLAYER"
    BROADCAST = "BROADCAST"
    SERVER = "SERVER"


class ChatMode(str, Enum):
    """聊天模式（用于 AI 聊天）"""

    GROUP = "GROUP"
    PRIVATE = "PRIVATE"


class ErrorCode(int, Enum):
    """根据协议定义的错误码"""

    SUCCESS = 0
    AUTH_INVALID = 1001
    AUTH_EXPIRED = 1002
    AUTH_MISSING = 1003
    PARAM_ERROR = 2001
    FORMAT_ERROR = 2002
    PARAM_MISSING = 2003
    INTERNAL_ERROR = 3001
    SERVICE_UNAVAILABLE = 3002
    NOT_FOUND = 4001
    PLAYER_OFFLINE = 4002
    FEATURE_DISABLED = 4003
    COMMAND_FAILED = 5001
    COMMAND_FILTERED = 5002
    NO_PERMISSION = 5003


@dataclass
class ServerInfo:
    """来自连接或 API 的服务器信息"""

    name: str = ""
    platform: str = ""
    platform_version: str = ""
    minecraft_version: str = ""
    motd: str = ""
    max_players: int = 0
    online_count: int = 0
    uptime: int = 0
    uptime_formatted: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "ServerInfo":
        return cls(
            name=data.get("name", ""),
            platform=data.get("platform", ""),
            platform_version=data.get("platformVersion", ""),
            minecraft_version=data.get("minecraftVersion", ""),
            motd=data.get("motd", ""),
            max_players=data.get("maxPlayers", 0),
            online_count=data.get("onlineCount", 0),
            uptime=data.get("uptime", 0),
            uptime_formatted=data.get("uptimeFormatted", ""),
        )


@dataclass
class PlayerInfo:
    """基本玩家信息"""

    uuid: str = ""
    name: str = ""
    display_name: str = ""
    ping: int = 0
    world: str = ""
    game_mode: str = ""
    is_op: bool = False

    @classmethod
    def from_dict(cls, data: dict) -> "PlayerInfo":
        return cls(
            uuid=data.get("uuid", ""),
            name=data.get("name", ""),
            display_name=data.get("displayName", ""),
            ping=data.get("ping", 0),
            world=data.get("world", ""),
            game_mode=data.get("gameMode", ""),
            is_op=data.get("isOp", False),
        )


@dataclass
class PlayerDetail(PlayerInfo):
    """详细玩家信息"""

    health: float = 20.0
    max_health: float = 20.0
    food_level: int = 20
    level: int = 0
    exp: float = 0.0
    total_exp: int = 0
    location: dict = field(default_factory=dict)
    is_flying: bool = False
    online_time: int = 0
    online_time_formatted: str = ""
    first_played: int = 0
    last_played: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "PlayerDetail":
        return cls(
            uuid=data.get("uuid", ""),
            name=data.get("name", ""),
            display_name=data.get("displayName", ""),
            ping=data.get("ping", 0),
            world=data.get("world", ""),
            game_mode=data.get("gameMode", ""),
            is_op=data.get("isOp", False),
            health=data.get("health", 20.0),
            max_health=data.get("maxHealth", 20.0),
            food_level=data.get("foodLevel", 20),
            level=data.get("level", 0),
            exp=data.get("exp", 0.0),
            total_exp=data.get("totalExp", 0),
            location=data.get("location", {}),
            is_flying=data.get("isFlying", False),
            online_time=data.get("onlineTime", 0),
            online_time_formatted=data.get("onlineTimeFormatted", ""),
            first_played=data.get("firstPlayed", 0),
            last_played=data.get("lastPlayed", 0),
        )


@dataclass
class MCMessageSource:
    """消息源信息"""

    type: SourceType = SourceType.PLAYER
    server_name: str = ""
    server_platform: str = ""
    player_uuid: str = ""
    player_name: str = ""
    player_display_name: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "MCMessageSource":
        server = data.get("server", {})
        player = data.get("player", {})
        return cls(
            type=safe_enum(SourceType, data.get("type", "PLAYER"), SourceType.PLAYER),
            server_name=server.get("name", ""),
            server_platform=server.get("platform", ""),
            player_uuid=player.get("uuid", ""),
            player_name=player.get("name", ""),
            player_display_name=player.get("displayName", ""),
        )


@dataclass
class MCMessageTarget:
    """消息目标信息"""

    type: TargetType = TargetType.BROADCAST
    player_uuid: str = ""
    player_name: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "MCMessageTarget":
        return cls(
            type=safe_enum(
                TargetType, data.get("type", "BROADCAST"), TargetType.BROADCAST
            ),
            player_uuid=data.get("playerUuid", ""),
            player_name=data.get("playerName", ""),
        )

    def to_dict(self) -> dict:
        result = {"type": self.type.value}
        if self.player_uuid:
            result["playerUuid"] = self.player_uuid
        if self.player_name:
            result["playerName"] = self.player_name
        return result


@dataclass
class MCMessage:
    """用于 WebSocket 通信的统一消息结构"""

    type: MessageType
    id: str = ""
    source: MCMessageSource | None = None
    target: MCMessageTarget | None = None
    payload: dict = field(default_factory=dict)
    timestamp: int = 0
    reply_to: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "MCMessage":
        source = None
        target = None
        if "source" in data:
            source = MCMessageSource.from_dict(data["source"])
        if "target" in data:
            target = MCMessageTarget.from_dict(data["target"])

        return cls(
            type=safe_enum(MessageType, data.get("type", "ERROR"), MessageType.ERROR),
            id=data.get("id", ""),
            source=source,
            target=target,
            payload=data.get("payload", {}),
            timestamp=data.get("timestamp", 0),
            reply_to=data.get("replyTo", ""),
        )

    def to_dict(self) -> dict:
        result: dict[str, Any] = {
            "type": self.type.value,
            "id": self.id,
            "timestamp": self.timestamp,
        }
        if self.target:
            result["target"] = self.target.to_dict()
        if self.payload:
            result["payload"] = self.payload
        if self.reply_to:
            result["replyTo"] = self.reply_to
        return result


@dataclass
class ServerConfig:
    """服务器连接配置"""

    enabled: bool = True
    server_id: str = ""
    host: str = "localhost"
    port: int = 8765
    token: str = ""
    enable_ai_chat: bool = True
    text2image: bool = True
    # 消息转发配置
    forward_chat_to_astrbot: bool = True
    forward_chat_format: str = "<{player}> {message}"
    forward_join_leave_to_astrbot: bool = False
    forward_target_session: list[str] = field(default_factory=list)
    auto_forward_prefix: str = "*"
    auto_forward_sessions: list[str] = field(default_factory=list)
    mark_option: str = "emoji"
    # 命令配置
    cmd_enabled: bool = True
    cmd_white_black_list: str = "white"
    cmd_list: list[str] = field(default_factory=list)
    bind_enable: bool = True
    custom_cmd_list: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "ServerConfig":
        server = data.get("server", {})
        message = data.get("message", {})
        cmd = data.get("cmd", {})  # cmd 与 message 处于同一层级，不是嵌套关系

        return cls(
            enabled=data.get("enabled", True),
            server_id=server.get("server_id", ""),
            host=server.get("host", "localhost"),
            port=server.get("port", 8765),
            token=server.get("token", ""),
            enable_ai_chat=data.get("enable_ai_chat", True),
            text2image=data.get("text2image", True),
            forward_chat_to_astrbot=message.get("forward_chat_to_astrbot", True),
            forward_chat_format=message.get(
                "forward_chat_format", "<{player}> {message}"
            ),
            forward_join_leave_to_astrbot=message.get(
                "forward_join_leave_to_astrbot", False
            ),
            forward_target_session=message.get("forward_target_session", []),
            auto_forward_prefix=message.get("auto_forward_prefix", "*"),
            auto_forward_sessions=message.get("auto_forward_sessions", []),
            mark_option=message.get("mark_option", "emoji"),
            cmd_enabled=cmd.get("enabled", True),
            cmd_white_black_list=cmd.get("cmd_white_black_list", "white"),
            cmd_list=cmd.get("cmd_list", []),
            bind_enable=cmd.get("bind_enable", True),
            custom_cmd_list=cmd.get("custom_cmd_list", []),
        )


@dataclass
class ServerStatus:
    """服务器状态信息"""

    online: bool = False
    tps_1m: float = 0.0
    tps_5m: float = 0.0
    tps_15m: float = 0.0
    memory_used: int = 0
    memory_max: int = 0
    memory_free: int = 0
    memory_usage_percent: float = 0.0
    worlds: list[dict] = field(default_factory=list)
    plugins_total: int = 0
    plugins_enabled: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "ServerStatus":
        tps = data.get("tps", {})
        memory = data.get("memory", {})
        plugins = data.get("plugins", {})

        return cls(
            online=True,
            tps_1m=tps.get("tps1m", 0.0),
            tps_5m=tps.get("tps5m", 0.0),
            tps_15m=tps.get("tps15m", 0.0),
            memory_used=memory.get("used", 0),
            memory_max=memory.get("max", 0),
            memory_free=memory.get("free", 0),
            memory_usage_percent=memory.get("usagePercent", 0.0),
            worlds=data.get("worlds", []),
            plugins_total=plugins.get("total", 0),
            plugins_enabled=plugins.get("enabled", 0),
        )


@dataclass
class LogEntry:
    """服务器日志条目"""

    timestamp: int = 0
    level: str = ""
    logger: str = ""
    message: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "LogEntry":
        return cls(
            timestamp=data.get("timestamp", 0),
            level=data.get("level", ""),
            logger=data.get("logger", ""),
            message=data.get("message", ""),
        )


@dataclass
class ApiResponse:
    """REST API 响应结构"""

    code: int = 0
    message: str = ""
    data: Any = None
    timestamp: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "ApiResponse":
        return cls(
            code=data.get("code", 0),
            message=data.get("message", ""),
            data=data.get("data"),
            timestamp=data.get("timestamp", 0),
        )

    @property
    def success(self) -> bool:
        return self.code == 0
