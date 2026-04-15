"""YouTube Music Song Request Plugin for AstrBot"""

import asyncio
import traceback

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.config.astrbot_config import AstrBotConfig
from astrbot.core.utils.session_waiter import (
    SessionController,
    session_waiter,
)

from .core.config import PluginConfig
from .core.downloader import Downloader
from .core.platform import BaseMusicPlayer
from .core.playlist import Playlist
from .core.renderer import MusicRenderer
from .core.sender import MusicSender
from .core.utils import parse_user_input


class MusicPlugin(Star):
    """YouTube Music Song Request Plugin for AstrBot"""
    
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.cfg = PluginConfig(config, context)
        self.players: list[BaseMusicPlayer] = []
        self.keywords: list[str] = []

    async def initialize(self):
        """Initialize plugin on load"""
        self._register_player()
        self.downloader = Downloader(self.cfg)
        await self.downloader.initialize()
        self.renderer = MusicRenderer(self.cfg)
        self.sender = MusicSender(self.cfg, self.renderer, self.downloader)

        # Playlist manager
        self.playlist = Playlist(self.cfg)
        await self.playlist.initialize()

    async def terminate(self):
        """Clean up resources on plugin unload"""
        await self.downloader.close()
        for player in self.players:
            await player.close()
        await self.playlist.close()

    def get_player(
        self, name: str | None = None, word: str | None = None, default: bool = False
    ) -> BaseMusicPlayer | None:
        """Get music player by name, keyword, or default"""
        if default:
            word = self.cfg.default_player_name
        for player in self.players:
            if name:
                name_ = name.strip().lower()
                p = player.platform
                if p.display_name.lower() == name_ or p.name.lower() == name_:
                    return player
            elif word:
                word_ = word.strip().lower()
                for keyword in player.platform.keywords:
                    if keyword.lower() in word_:
                        return player

    def _register_player(self):
        """Register music players"""
        all_subclass = BaseMusicPlayer.get_all_subclass()
        for _cls in all_subclass:
            player = _cls(self.cfg)
            self.players.append(player)
            self.keywords.extend(player.platform.keywords)
        logger.debug(f"Registered keywords: {self.keywords}")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_search_song(self, event: AstrMessageEvent):
        """
        Handle song request commands.
        Supports: "点歌 <song_name>" or "<platform>点歌 <song_name>"
        Users can also specify song index: "点歌 <song_name> <index>"
        """
        # Parse parameters
        if not event.is_at_or_wake_command:
            return
        cmd, _, arg = event.message_str.partition(" ")
        if not arg:
            return
        player = self.get_player(word=cmd)
        if "点歌" == cmd:
            player = self.get_player(default=True)
        if not player:
            return
        args = arg.split()
        index: int = int(args[-1]) if args[-1].isdigit() else 0
        song_name = arg.removesuffix(str(index))
        if not song_name:
            yield event.plain_result

