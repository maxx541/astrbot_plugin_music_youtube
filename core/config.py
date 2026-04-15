"""Plugin configuration management"""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from pathlib import Path
from types import MappingProxyType, UnionType
from typing import Any, Union, get_args, get_origin, get_type_hints

from astrbot.api import logger
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.star.context import Context
from astrbot.core.utils.astrbot_path import (
    get_astrbot_plugin_data_path,
    get_astrbot_plugin_path,
)


class ConfigNode:
    """Configuration node that converts dict to strongly-typed objects"""
    
    _SCHEMA_CACHE: dict[type, dict[str, type]] = {}
    _FIELDS_CACHE: dict[type, set[str]] = {}

    @classmethod
    def _schema(cls) -> dict[str, type]:
        return cls._SCHEMA_CACHE.setdefault(cls, get_type_hints(cls))

    @classmethod
    def _fields(cls) -> set[str]:
        return cls._FIELDS_CACHE.setdefault(
            cls,
            {k for k in cls._schema() if not k.startswith("_")},
        )

    @staticmethod
    def _is_optional(tp: type) -> bool:
        if get_origin(tp) in (Union, UnionType):
            return type(None) in get_args(tp)
        return False

    def __init__(self, data: MutableMapping[str, Any]):
        object.__setattr__(self, "_data", data)
        object.__setattr__(self, "_children", {})
        for key, tp in self._schema().items():
            if key.startswith("_"):
                continue
            if key in data:
                continue
            if hasattr(self.__class__, key):
                continue
            if self._is_optional(tp):
                continue
            logger.warning(f"[config:{self.__class__.__name__}] Missing field: {key}")

    def __getattr__(self, key: str) -> Any:
        if key in self._fields():
            value = self._data.get(key)
            tp = self._schema().get(key)

            if isinstance(tp, type) and issubclass(tp, ConfigNode):
                children: dict[str, ConfigNode] = self.__dict__["_children"]
                if key not in children:
                    if not isinstance(value, MutableMapping):
                        raise TypeError(
                            f"[config:{self.__class__.__name__}] "
                            f"Field {key} expects dict, got {type(value).__name__}"
                        )
                    children[key] = tp(value)
                return children[key]

            return value

        if key in self.__dict__:
            return self.__dict__[key]

        raise AttributeError(key)

    def __setattr__(self, key: str, value: Any) -> None:
        if key in self._fields():
            self._data[key] = value
            return
        object.__setattr__(self, key, value)

    def raw_data(self) -> Mapping[str, Any]:
        """Get read-only view of underlying config dict"""
        return MappingProxyType(self._data)

    def save_config(self) -> None:
        """Save config to disk (only call from root node)"""
        if not isinstance(self._data, AstrBotConfig):
            raise RuntimeError(
                f"{self.__class__.__name__}.save_config() "
                "can only be called from root config node"
            )
        self._data.save_config()


class PluginConfig(ConfigNode):
    """Music plugin configuration schema"""
    
    # Basic settings
    default_player_name: str
    song_limit: int
    select_mode: str
    send_modes: list[str]
    record_supported: list[str]
    file_supported: list[str]
    enable_lyrics: bool
    timeout: int
    timeout_recall: bool
    clear_cache: bool
    playlist_limit: int
    proxy: str
    
    # YouTube subtitle settings (new)
    youtube_enable_subtitle: bool
    youtube_subtitle_priority: list[str]

    _plugin_name: str = "astrbot_plugin_music"

    def __init__(self, config: AstrBotConfig, context: Context):
        super().__init__(config)
        self.context = context

        # Font path for lyrics rendering
        self.font_path = (
            Path(get_astrbot_plugin_path()) 
            / self._plugin_name 
            / "fonts" 
            / "simhei.ttf"
        )
        
        # Data directory paths
        self.data_dir = (
            Path(get_astrbot_plugin_data_path()) / self._plugin_name
        )
        self.songs_dir = self.data_dir / "songs"
        self.songs_dir.mkdir(parents=True, exist_ok=True)
        
        self.playlist_dir = self.data_dir / "playlist"
        self.playlist_dir.mkdir(parents=True, exist_ok=True)
        
        self.db_path = self.data_dir / "playlist.db"
        
        # YouTube subtitle cache directory (new)
        self.youtube_subtitle_cache_dir = (
            self.data_dir / "youtube_subtitles"
        )
        self.youtube_subtitle_cache_dir.mkdir(parents=True, exist_ok=True)

        # Parse send modes
        self._send_modes = [
            m.split("(", 1)[0].strip() for m in self.send_modes
        ]

    @property
    def http_proxy(self) -> str | None:
        """Get HTTP proxy URL or None if empty"""
        return self.proxy or None

    @property
    def real_send_modes(self) -> list[str]:
        """Get parsed send modes list"""
        return self._send_modes

    @property
    def real_song_limit(self) -> int:
        """Get effective song limit based on select mode"""
        return 1 if "single" in self.select_mode else self.song_limit
