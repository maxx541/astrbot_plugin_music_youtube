"""Message sending with auto-degradation strategy"""

import asyncio
import random

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent
from astrbot.core.message.components import File, Image, Record
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
    AiocqhttpMessageEvent,
)

from .config import PluginConfig
from .downloader import Downloader
from .model import Song
from .platform import BaseMusicPlayer
from .renderer import MusicRenderer


class MusicSender:
    """Send music messages with auto-degradation"""
    
    def __init__(
        self,
        config: PluginConfig,
        renderer: MusicRenderer,
        downloader: Downloader
    ):
        self.cfg = config
        self.renderer = renderer
        self.downloader = downloader

    @staticmethod
    def _format_time(duration_ms: int) -> str:
        """Format duration from milliseconds"""
        duration = duration_ms // 1000

        hours = duration // 3600
        minutes = (duration % 3600) // 60
        seconds = duration % 60

        if hours > 0:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"

    @staticmethod
    async def send_msg(
        event: AiocqhttpMessageEvent, payloads: dict
    ) -> int | None:
        """Send message via QQ platform"""
        if event.is_private_chat():
            payloads["user_id"] = event.get_sender_id()
            result = await event.bot.api.call_action(
                "send_private_msg", **payloads
            )
        else:
            payloads["group_id"] = event.get_group_id()
            result = await event.bot.api.call_action(
                "send_group_msg", **payloads
            )
        return result.get("message_id")

    async def send_song_selection(
        self,
        event: AstrMessageEvent,
        songs: list[Song],
        title: str | None = None
    ) -> None:
        """Send song selection list"""
        formatted_songs = [
            f"{index + 1}. {song.name} - {song.artists}"
            for index, song in enumerate(songs)
        ]
        if title:
            formatted_songs.insert(0, title)

        msg = "\n".join(formatted_songs)
        if isinstance(event, AiocqhttpMessageEvent):
            payloads = {
                "message": [{"type": "text", "data": {"text": msg}}]
            }
            message_id = await self.send_msg(event, payloads)
            if message_id and self.cfg.timeout_recall:
                await asyncio.sleep(self.cfg.timeout)
                await event.bot.delete_msg(message_id=message_id)
        else:
            await event.send(event.plain_result(msg))

    async def send_comment(
        self,
        event: AstrMessageEvent,
        player: BaseMusicPlayer,
        song: Song
    ) -> bool:
        """Send song comment"""
        if not song.comments:
            await player.fetch_comments(song)
        if not song.comments:
            return False
        try:
            content = random.choice(song.comments).get("content")
            await event.send(event.plain_result(content))
            return True
        except Exception:
            return False

    async def send_lyrics(
        self,
        event: AstrMessageEvent,
        player: BaseMusicPlayer,
        song: Song
    ) -> bool:
        """Send lyrics/subtitles as image"""
        if not self.cfg.enable_lyrics:
            return False
        
        if not song.lyrics:
            # YouTube special handling
            if (hasattr(player, '_fetch_youtube_captions') 
                    and self.cfg.youtube_enable_subtitle):
                await player.fetch_lyrics(song)
            else:
                await player.fetch_lyrics(song)
        
        if not song.lyrics:
            logger.debug(
                f"【{song.name}】Lyrics/subtitles not found"
            )
            return False
        
        try:
            image = self.renderer.draw_lyrics(song.lyrics)
            await event.send(
                MessageChain(chain=[Image.fromBytes(image)])
            )
            return True
        except Exception as e:
            logger.error(
                f"【{song.name}】Lyrics rendering/sending failed: {e}"
            )
            return False

    async def send_record(
        self,
        event: AstrMessageEvent,
        player: BaseMusicPlayer,
        song: Song
    ) -> bool:
        """Send audio as voice message"""
        if not song.audio_url:
            song = await player.fetch_extra(song)
        if not song.audio_url:
            await event.send(
                event.plain_result(f"【{song.name}】Audio retrieval failed")
            )
            return False
        try:
            logger.debug(
                f"Sending 【{song.name}】audio: {song.audio_url}"
            )
            seg = Record.fromURL(song.audio_url)
            await event.send(event.chain_result([seg]))
            return True
        except Exception as e:
            logger.error(
                f"【{song.name}】Audio sending failed: {e}"
            )
            return False

    async def send_file(
        self,
        event: AstrMessageEvent,
        player: BaseMusicPlayer,
        song: Song
    ) -> bool:
        """Send audio as file"""
        if not song.audio_url:
            song = await player.fetch_extra(song)
        if not song.audio_url:
            await event.send(
                event.plain_result(
                    f"【{song.name}】Audio retrieval failed"
                )
            )
            return False

        file_path = await self.downloader.download_song(
            song.audio_url
        )

        async def send_by_url() -> bool:
            """Fallback: send by URL"""
            try:
                file_name_url = (
                    f"{song.name}_{song.artists}.mp3"
                )
                if song.audio_url:
                    seg_url = File(
                        name=file_name_url,
                        url=song.audio_url
                    )
                    await event.send(event.chain_result([seg_url]))
                    return True
            except Exception as e_url:
                logger.error(f"URL sending failed: {e_url}")
                return False

        if not file_path:
            logger.warning(
                f"【{song.name}】Download failed, trying URL"
            )
            if await send_by_url():
                return True
            await event.send(
                event.plain_result(
                    f"【{song.name}】Download and send failed"
                )
            )
            return False

        try:
            file_name = f"{song.name}_{song.artists}{file_path.suffix}"
            seg = File(
                name=file_name,
                file=str(file_path.resolve())
            )
            await event.send(event.chain_result([seg]))
            return True
        except Exception as e:
            logger.warning(
                f"【{song.name}】Local file send failed: {e}, "
                "trying URL"
            )
            if await send_by_url():
                return True

            await event.send(
                event.plain_result(
                    f"【{song.name}】File send failed: {e}"
                )
            )
            return False

    async def send_text(
        self,
        event: AstrMessageEvent,
        player: BaseMusicPlayer,
        song: Song
    ) -> bool:
        """Send song info as text"""
        try:
            song = await player.fetch_extra(song)
            info = song.to_lines()
            await event.send(event.plain_result(info))
            return True
        except Exception as e:
            logger.error(f"Send song info failed: {e}")
            return False

    def _get_sender(self, mode: str):
        """Get sender function for mode"""
        return {
            "record": self.send_record,
            "file": self.send_file,
            "text": self.send_text,
        }.get(mode)

    def _is_mode_supported(
        self,
        mode: str,
        event: AstrMessageEvent,
        player: BaseMusicPlayer
    ) -> bool:
        """Check if platform supports send mode"""
        platform = event.get_platform_name()
        match mode:
            case "text":
                return True
            case "card":
                # Card mode not supported for YouTube
                return False
            case "record":
                return platform in self.cfg.record_supported
            case "file":
                return platform in self.cfg.file_supported
            case _:
                return False

    async def send_song(
        self,
        event: AstrMessageEvent,
        player: BaseMusicPlayer,
        song: Song,
        modes: list[str] | None = None,
    ) -> None:
        """
        Send song with auto-degradation.
        
        Tries modes in order:
        1. Voice message
        2. File message
        3. Text link
        """
        logger.debug(
            f"{event.get_sender_name()}({event.get_sender_id()}) "
            f"playing: {player.platform.display_name} → "
            f"{song.name}_{song.artists}"
        )

        sent = False
        target_modes = (
            modes if modes is not None else self.cfg.real_send_modes
        )

        for mode in target_modes:
            if not self._is_mode_supported(mode, event, player):
                logger.debug(f"{mode} not supported, skip")
                continue

            sender = self._get_sender(mode)
            if not sender:
                continue

            try:
                ok = await sender(event, player, song)
            except Exception as e:
                logger.error(f"{mode} send error: {e}")
                ok = False

            if ok:
                logger.debug(f"{mode} send success")
                sent = True
                break
            else:
                logger.debug(f"{mode} send failed, try next")

        if not sent:
            await event.send(
                event.plain_result("Song send failed")
            )

        # Attach extras (don't affect main flow)
        if sent and self.cfg.enable_lyrics:
            await self.send_lyrics(event, player, song)
