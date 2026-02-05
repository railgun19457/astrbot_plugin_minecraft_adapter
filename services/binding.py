"""User binding service for linking external platform users to MC players."""

import json
from dataclasses import dataclass, field
from pathlib import Path

from astrbot.api import logger


@dataclass
class UserBinding:
    """Represents a binding between an external user and MC player."""

    # External platform info
    platform: str  # e.g., "aiocqhttp", "telegram"
    user_id: str  # External platform user ID
    # MC player info
    mc_player_name: str
    mc_player_uuid: str = ""
    # Metadata
    created_at: int = 0
    server_id: str = ""  # Optional: specific server binding

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
    """Storage for user bindings."""

    # Key: "platform:user_id", Value: UserBinding
    bindings: dict[str, UserBinding] = field(default_factory=dict)
    # Reverse index: Key: mc_player_name (lowercase), Value: list of binding keys
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
            # Build index
            mc_name_lower = binding.mc_player_name.lower()
            if mc_name_lower not in storage.mc_name_index:
                storage.mc_name_index[mc_name_lower] = []
            storage.mc_name_index[mc_name_lower].append(key)
        return storage


class BindingService:
    """Service for managing user bindings."""

    def __init__(self, data_dir: str | Path):
        """Initialize binding service.

        Args:
            data_dir: Directory to store binding data
        """
        self.data_dir = Path(data_dir)
        self.data_file = self.data_dir / "mc_bindings.json"
        self._storage = BindingStorage()
        self._load()

    def _load(self):
        """Load bindings from file."""
        if self.data_file.exists():
            try:
                with open(self.data_file, encoding="utf-8") as f:
                    data = json.load(f)
                self._storage = BindingStorage.from_dict(data)
                logger.info(
                    f"[BindingService] Loaded {len(self._storage.bindings)} bindings"
                )
            except Exception as e:
                logger.error(f"[BindingService] Failed to load bindings: {e}")
                self._storage = BindingStorage()
        else:
            logger.info("[BindingService] No existing bindings file")

    def _save(self):
        """Save bindings to file."""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            with open(self.data_file, "w", encoding="utf-8") as f:
                json.dump(self._storage.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"[BindingService] Failed to save bindings: {e}")

    def _make_key(self, platform: str, user_id: str) -> str:
        """Create a unique key for a user."""
        return f"{platform}:{user_id}"

    def bind(
        self,
        platform: str,
        user_id: str,
        mc_player_name: str,
        mc_player_uuid: str = "",
        server_id: str = "",
    ) -> tuple[bool, str]:
        """Bind an external user to a MC player.

        Returns:
            tuple: (success, message)
        """
        import time

        key = self._make_key(platform, user_id)

        # Check if already bound
        if key in self._storage.bindings:
            existing = self._storage.bindings[key]
            return (
                False,
                f"你已经绑定了玩家 {existing.mc_player_name}，请先解绑",
            )

        # Create binding
        binding = UserBinding(
            platform=platform,
            user_id=user_id,
            mc_player_name=mc_player_name,
            mc_player_uuid=mc_player_uuid,
            created_at=int(time.time()),
            server_id=server_id,
        )

        # Store binding
        self._storage.bindings[key] = binding

        # Update index
        mc_name_lower = mc_player_name.lower()
        if mc_name_lower not in self._storage.mc_name_index:
            self._storage.mc_name_index[mc_name_lower] = []
        self._storage.mc_name_index[mc_name_lower].append(key)

        self._save()
        logger.info(f"[BindingService] Bound {platform}:{user_id} -> {mc_player_name}")
        return True, f"成功绑定玩家 {mc_player_name}"

    def unbind(self, platform: str, user_id: str) -> tuple[bool, str]:
        """Unbind an external user.

        Returns:
            tuple: (success, message)
        """
        key = self._make_key(platform, user_id)

        if key not in self._storage.bindings:
            return False, "你还没有绑定任何玩家"

        binding = self._storage.bindings[key]
        mc_name_lower = binding.mc_player_name.lower()

        # Remove from index
        if mc_name_lower in self._storage.mc_name_index:
            self._storage.mc_name_index[mc_name_lower] = [
                k for k in self._storage.mc_name_index[mc_name_lower] if k != key
            ]
            if not self._storage.mc_name_index[mc_name_lower]:
                del self._storage.mc_name_index[mc_name_lower]

        # Remove binding
        del self._storage.bindings[key]

        self._save()
        logger.info(
            f"[BindingService] Unbound {platform}:{user_id} from {binding.mc_player_name}"
        )
        return True, f"成功解绑玩家 {binding.mc_player_name}"

    def get_binding(self, platform: str, user_id: str) -> UserBinding | None:
        """Get binding for a user."""
        key = self._make_key(platform, user_id)
        return self._storage.bindings.get(key)

    def get_bindings_by_mc_name(self, mc_player_name: str) -> list[UserBinding]:
        """Get all bindings for a MC player name.

        Args:
            mc_player_name: Minecraft player name (case-insensitive)

        Returns:
            List of UserBinding objects for this player
        """
        mc_name_lower = mc_player_name.lower()
        keys = self._storage.mc_name_index.get(mc_name_lower, [])
        return [
            self._storage.bindings[key] for key in keys if key in self._storage.bindings
        ]

    def get_all_bindings(self) -> list[UserBinding]:
        """Get all bindings.

        Returns:
            List of all UserBinding objects
        """
        return list(self._storage.bindings.values())

    def get_mc_player_name(self, platform: str, user_id: str) -> str | None:
        """Get MC player name for a user (convenience method).

        Args:
            platform: Platform name
            user_id: User ID on the platform

        Returns:
            MC player name if bound, None otherwise
        """
        binding = self.get_binding(platform, user_id)
        return binding.mc_player_name if binding else None
