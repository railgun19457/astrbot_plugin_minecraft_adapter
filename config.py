"""配置管理模块"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MinecraftAdapterConfig:
    """Minecraft 适配器配置"""

    enabled: bool = False
    websocket_host: str = "localhost"
    websocket_port: int = 8765
    websocket_token: str = ""
    rest_api_host: str = "localhost"
    rest_api_port: int = 8766
    rest_api_token: str = ""
    auto_reconnect: bool = True
    reconnect_interval: int = 5
    forward_chat_to_astrbot: bool = True
    forward_join_leave_to_astrbot: bool = True
    forward_target_session: list[str] = field(default_factory=list)
    status_check_interval: int = 300
    auto_forward_prefix: str = ""
    auto_forward_sessions: list[str] = field(default_factory=list)

    # AI 对话配置
    ai_chat_prefix: str = "!ai"  # 触发 AI 对话的前缀
    enable_ai_chat: bool = True  # 是否启用 AI 对话功能

    def __post_init__(self):
        """初始化后处理"""
        self.forward_target_session = self._parse_list(self.forward_target_session)
        self.auto_forward_sessions = self._parse_list(self.auto_forward_sessions)

    @staticmethod
    def _parse_list(value) -> list[str]:
        """解析列表配置（支持字符串多行格式）"""
        if isinstance(value, list):
            return value
        if isinstance(value, str) and value.strip():
            return [
                line.strip()
                for line in value.split("\n")
                if line.strip() and not line.startswith("#")
            ]
        return []

    @classmethod
    def from_dict(cls, config: dict) -> MinecraftAdapterConfig:
        """从字典创建配置对象"""
        return cls(**{k: v for k, v in config.items() if k in cls.__annotations__})

    @property
    def ws_uri(self) -> str:
        return f"ws://{self.websocket_host}:{self.websocket_port}"

    @property
    def rest_api_base_url(self) -> str:
        return f"http://{self.rest_api_host}:{self.rest_api_port}"
