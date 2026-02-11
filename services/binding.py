"""用户绑定服务，用于将外部平台用户与 MC 玩家关联"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from astrbot.api import logger


@dataclass
class UserBinding:
    """表示外部用户与 MC 玩家之间的绑定"""

    # 外部平台信息
    platform: str  # 例如 "aiocqhttp", "telegram"
    user_id: str  # 外部平台用户 ID
    # MC 玩家信息
    mc_player_name: str
    mc_player_uuid: str = ""
    # 元数据
    created_at: int = 0
    server_id: str = ""  # 可选：特定服务器绑定

    def to_dict(self) -> dict:
        return {
            "platform": self.platform,
            "user_id": self.user_id,
            "mc_player_name": self.mc_player_name,
            "mc_player_uuid": self.mc_player_uuid,
            "created_at": self.created_at,
            "server_id": self.server_id,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "UserBinding":
        return cls(
            platform=data.get("platform", ""),
            user_id=data.get("user_id", ""),
            mc_player_name=data.get("mc_player_name", ""),
            mc_player_uuid=data.get("mc_player_uuid", ""),
            created_at=data.get("created_at", 0),
            server_id=data.get("server_id", ""),
        )


@dataclass
class BindingStorage:
    """用户绑定的存储"""

    # 键: "platform:user_id", 值: UserBinding
    bindings: dict[str, UserBinding] = field(default_factory=dict)
    # 反向索引: 键: mc_player_name (小写), 值: 绑定键列表
    mc_name_index: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "bindings": {k: v.to_dict() for k, v in self.bindings.items()},
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BindingStorage":
        storage = cls()
        for key, binding_data in data.get("bindings", {}).items():
            binding = UserBinding.from_dict(binding_data)
            storage.bindings[key] = binding
            # 构建索引
            mc_name_lower = binding.mc_player_name.lower()
            if mc_name_lower not in storage.mc_name_index:
                storage.mc_name_index[mc_name_lower] = []
            storage.mc_name_index[mc_name_lower].append(key)
        return storage


class BindingService:
    """用户绑定管理服务"""

    def __init__(self, data_dir: str | Path):
        """初始化绑定服务

        参数:
            data_dir: 存储绑定数据的目录
        """
        self.data_dir = Path(data_dir)
        self.data_file = self.data_dir / "mc_bindings.json"
        self._storage = BindingStorage()
        self._load()

    def _load(self):
        """从文件加载绑定"""
        if self.data_file.exists():
            try:
                with open(self.data_file, encoding="utf-8") as f:
                    data = json.load(f)
                self._storage = BindingStorage.from_dict(data)
                logger.info(
                    f"[BindingService] 已加载 {len(self._storage.bindings)} 个绑定"
                )
            except Exception as e:
                logger.error(f"[BindingService] 加载绑定失败: {e}")
                self._storage = BindingStorage()
        else:
            logger.info("[BindingService] 绑定文件不存在")

    def _save(self):
        """保存绑定到文件"""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self._storage.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[BindingService] 保存绑定失败: {e}")

    def _make_key(self, platform: str, user_id: str) -> str:
        """创建用户的唯一键"""
        return f"{platform}:{user_id}"

    def bind(
        self,
        platform: str,
        user_id: str,
        mc_player_name: str,
        mc_player_uuid: str = "",
        server_id: str = "",
    ) -> tuple[bool, str]:
        """将外部用户绑定到 MC 玩家

        返回:
            tuple: (成功, 消息)
        """
        import time

        key = self._make_key(platform, user_id)

        # 检查是否已绑定
        if key in self._storage.bindings:
            existing = self._storage.bindings[key]
            return (
                False,
                f"你已经绑定了玩家 {existing.mc_player_name}，请先解绑",
            )

        # 创建绑定
        binding = UserBinding(
            platform=platform,
            user_id=user_id,
            mc_player_name=mc_player_name,
            mc_player_uuid=mc_player_uuid,
            created_at=int(time.time()),
            server_id=server_id,
        )

        # 存储绑定
        self._storage.bindings[key] = binding

        # 更新索引
        mc_name_lower = mc_player_name.lower()
        if mc_name_lower not in self._storage.mc_name_index:
            self._storage.mc_name_index[mc_name_lower] = []
        self._storage.mc_name_index[mc_name_lower].append(key)

        self._save()
        logger.info(f"[BindingService] 已绑定 {platform}:{user_id} -> {mc_player_name}")
        return True, f"成功绑定玩家 {mc_player_name}"

    def unbind(self, platform: str, user_id: str) -> tuple[bool, str]:
        """解绑外部用户

        返回:
            tuple: (成功, 消息)
        """
        key = self._make_key(platform, user_id)

        if key not in self._storage.bindings:
            return False, "你还没有绑定任何玩家"

        binding = self._storage.bindings[key]
        mc_name_lower = binding.mc_player_name.lower()

        # 从索引中移除
        if mc_name_lower in self._storage.mc_name_index:
            self._storage.mc_name_index[mc_name_lower] = [
                k for k in self._storage.mc_name_index[mc_name_lower] if k != key
            ]
            if not self._storage.mc_name_index[mc_name_lower]:
                del self._storage.mc_name_index[mc_name_lower]

        # 移除绑定
        del self._storage.bindings[key]

        self._save()
        logger.info(
            f"[BindingService] 已解绑 {platform}:{user_id} (原绑定玩家: {binding.mc_player_name})"
        )
        return True, f"成功解绑玩家 {binding.mc_player_name}"

    def get_binding(self, platform: str, user_id: str) -> UserBinding | None:
        """获取用户的绑定"""
        key = self._make_key(platform, user_id)
        return self._storage.bindings.get(key)

    def get_bindings_by_mc_name(self, mc_player_name: str) -> list[UserBinding]:
        """获取 MC 玩家名称的所有绑定。

        参数:
            mc_player_name: Minecraft 玩家名称（不区分大小写）

        返回:
            该玩家的 UserBinding 对象列表
        """
        mc_name_lower = mc_player_name.lower()
        keys = self._storage.mc_name_index.get(mc_name_lower, [])
        return [
            self._storage.bindings[key] for key in keys if key in self._storage.bindings
        ]

    def get_all_bindings(self) -> list[UserBinding]:
        """获取所有绑定。

        返回:
            所有 UserBinding 对象的列表
        """
        return list(self._storage.bindings.values())

    def get_mc_player_name(self, platform: str, user_id: str) -> str | None:
        """获取用户的 MC 玩家名称（便捷方法）。

        参数:
            platform: 平台名称
            user_id: 平台上的用户 ID

        返回:
            如果已绑定则返回 MC 玩家名称，否则返回 None
        """
        binding = self.get_binding(platform, user_id)
        return binding.mc_player_name if binding else None
