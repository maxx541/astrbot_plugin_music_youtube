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
            yield event.plain_result("未指定歌名")
            return
        # Search songs
        logger.debug(f"Searching songs: {song_name}")
        songs = await player.fetch_songs(
            keyword=song_name, limit=self.cfg.real_song_limit, extra=cmd
        )
        if not songs:
            yield event.plain_result(f"搜索【{song_name}】无结果")
            return

        # Single song mode
        if len(songs) == 1:
            index = 1

        # Direct send if index specified
        if index and 0 <= index <= len(songs):
            selected_song = songs[int(index) - 1]
            await self.sender.send_song(event, player, selected_song)

        # Wait for user selection
        else:
            title = f"【{player.platform.display_name}】"
            asyncio.create_task(
                self.sender.send_song_selection(event=event, songs=songs, title=title)
            )

            @session_waiter(timeout=self.cfg.timeout)
            async def song_selection_waiter(
                controller: SessionController, event: AstrMessageEvent
            ):
                arg = event.message_str.strip()
                arg_lower = arg.lower()
                for kw in self.keywords:
                    if kw in arg_lower:
                        controller.stop()
                        return
                # Parse user input
                index, modes, error = parse_user_input(arg)
                if error:
                    await event.send(event.plain_result(error))
                    return
                if index == 0:
                    return
                if index < 1 or index > len(songs):
                    controller.stop()
                    return
                selected_song = songs[index - 1]
                await self.sender.send_song(event, player, selected_song, modes=modes)
                controller.stop()

            try:
                await song_selection_waiter(event)
            except TimeoutError:
                yield event.plain_result("点歌超时！")
            except Exception as e:
                logger.error(traceback.format_exc())
                logger.error("Song request error: " + str(e))

        event.stop_event()

    @filter.command("查歌词")
    async def query_lyrics(self, event: AstrMessageEvent, song_name: str):
        """Query and display song lyrics"""
        player = self.get_player(default=True)
        if not player:
            yield event.plain_result("无可用播放器")
            return
        songs = await player.fetch_songs(keyword=song_name, limit=1)
        if not songs:
            yield event.plain_result("没找到相关歌曲")
            return
        await self.sender.send_lyrics(event, player, songs[0])

    @filter.llm_tool()
    async def play_song_by_name(self, event: AstrMessageEvent, song_name: str) -> str:
        """
        当用户想听歌时，根据歌名搜索并播放音乐。
        
        :param song_name: 歌曲名称或歌手名字
        :return: 播放状态或错误信息
        """
        player = self.get_player(default=True)
        if not player:
            return "无可用播放器"
        
        try:
            logger.debug(f"Searching for: {song_name}")
            songs = await player.fetch_songs(keyword=song_name, limit=1)
            
            if not songs:
                return f"没找到'{song_name}'"
            
            song = songs[0]
            await self.sender.send_song(event, player, song)
            return f"正在播放: {song.name} - {song.artists}"
            
        except Exception as e:
            logger.error(f"Play song error: {e}")
            return "播放失败，请稍后重试"
            
    @filter.command("歌单收藏")
    async def collect_song(self, event: AstrMessageEvent, song_name: str):
        """Add song to user's personal playlist"""
        user_id = event.get_sender_id()
        player = self.get_player(default=True)
        if not player:
            yield event.plain_result("无可用播放器")
            return

        # Search song
        songs = await player.fetch_songs(keyword=song_name, limit=1)
        if not songs:
            yield event.plain_result(f"搜索【{song_name}】无结果")
            return

        song = songs[0]
        platform = player.platform.name

        # Add to playlist
        success = await self.playlist.add_song(user_id, song, platform)
        if success:
            yield event.plain_result(f"已收藏【{song.name}_{song.artists}】")
        else:
            yield event.plain_result(f"【{song.name}】已在你的歌单中")

    @filter.command("歌单取藏")
    async def uncollect_song(self, event: AstrMessageEvent, song_name: str):
        """Remove song from user's personal playlist"""
        user_id = event.get_sender_id()
        player = self.get_player(default=True)
        if not player:
            yield event.plain_result("无可用播放器")
            return

        # Search song
        songs = await player.fetch_songs(keyword=song_name, limit=1)
        if not songs:
            yield event.plain_result(f"搜索【{song_name}】无结果")
            return

        song = songs[0]
        platform = player.platform.name

        # Remove from playlist
        success = await self.playlist.remove_song(user_id, song.id, platform)
        if success:
            yield event.plain_result(f"已取消收藏【{song.name}_{song.artists}】")
        else:
            yield event.plain_result(f"【{song.name}】不在你的歌单中")

    @filter.command("歌单列表")
    async def view_playlist(self, event: AstrMessageEvent):
        """Display user's saved playlist"""
        user_id = event.get_sender_id()
        user_name = event.get_sender_name()

        # Check if playlist is empty
        if await self.playlist.is_empty(user_id):
            yield event.plain_result("你的歌单是空的，使用「歌单收藏 <歌名>」来添加歌曲")
            return

        # Get playlist
        songs_with_platform = await self.playlist.get_songs(user_id)
        if not songs_with_platform:
            yield event.plain_result("获取歌单失败")
            return

        # Format playlist
        playlist_text = f"【{user_name}的歌单】\n"
        for i, (song, platform) in enumerate(songs_with_platform, 1):
            playlist_text += f"{i}. {song.name} - {song.artists}\n"

        yield event.plain_result(playlist_text.strip())

    @filter.command("歌单点歌")
    async def play_from_playlist(self, event: AstrMessageEvent, index: str):
        """Play song from user's saved playlist by index"""
        user_id = event.get_sender_id()

        # Validate index
        if not index.isdigit():
            yield event.plain_result("请输入有效的序号")
            return

        idx = int(index)
        if idx < 1:
            yield event.plain_result("序号必须大于0")
            return

        # Get playlist
        songs_with_platform = await self.playlist.get_songs(user_id)
        if not songs_with_platform:
            yield event.plain_result("你的歌单是空的")
            return

        if idx > len(songs_with_platform):
            yield event.plain_result(
                f"序号超出范围，你的歌单只有{len(songs_with_platform)}首歌"
            )
            return

        # Get specified song
        song, platform_name = songs_with_platform[idx - 1]

        # Find corresponding player
        player = self.get_player(name=platform_name)
        if not player:
            player = self.get_player(default=True)

        if not player:
            yield event.plain_result("无可用播放器")
            return

        # Send song
        await self.sender.send_song(event, player, song)
