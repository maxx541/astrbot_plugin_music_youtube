"""Base class for music platform implementations"""

import json
from abc import ABC, abstractmethod
from typing import ClassVar

import aiohttp

from astrbot.api import logger

from ..config import PluginConfig
from ..model import Platform, Song


class BaseMusicPlayer(ABC):
    """
    Base class for music platforms with HTTP support.
    
    Subclasses must implement:
    - platform: Platform info (name, display_name, keywords)
    - fetch_songs: Search for songs
    """

    _registry: ClassVar[list[type["BaseMusicPlayer"]]] = []
    """Store all registered player classes"""

    platform: ClassVar[Platform]
    """Platform information"""

    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; WOW64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/55.0.2883.87 Safari/537.36"
        )
    }

    def __init__(self, config: PluginConfig):
        self.cfg = config
        self.session = aiohttp.ClientSession(proxy=self.cfg.http_proxy)

    def __init_subclass__(cls, **kwargs):
        """Auto-register subclasses to _registry"""
        super().__init_subclass__(**kwargs)
        if ABC not in cls.__bases__:  # Skip abstract classes
            BaseMusicPlayer._registry.append(cls)

    @classmethod
    def get_all_subclass(cls) -> list[type["BaseMusicPlayer"]]:
        """Get all registered player classes"""
        return cls._registry

    # ---------- Subclasses must implement ----------

    @abstractmethod
    async def fetch_songs(
        self, keyword: str, limit: int, extra: str | None = None
    ) -> list[Song]:
        """
        Search for songs.
        
        Args:
            keyword: Search keyword
            limit: Maximum number of results
            extra: Extra parameters
        
        Returns:
            List of Song objects
        """
        raise NotImplementedError

    # ---------- Reusable methods ----------
    
    async def fetch_extra(self, song: Song) -> Song:
        """Get additional song information (default implementation)"""
        url = f"https://api.qijieya.cn/meting/?type=song&id={song.id}"

        result = await self._request(url)

        if result and isinstance(result, list) and len(result) > 0:
            data = result[0]
            if not song.audio_url:
                song.audio_url = data.get("url")
            if not song.cover_url:
                song.cover_url = data.get("pic")
            if not song.lyrics:
                song.lyrics = data.get("lrc")
        return song

    async def fetch_comments(self, song: Song) -> Song:
        """Get song comments (default implementation - not used for YouTube)"""
        if song.comments:
            return song

        try:
            result = await self._request(
                url="https://music.163.com/weapi/v1/resource/hotcomments/"
                    f"R_SO_4_{song.id}?csrf_token=",
                method="POST",
                data={
                    "params": getattr(self.cfg, "enc_params", ""),
                    "encSecKey": getattr(self.cfg, "enc_sec_key", ""),
                },
            )
        except Exception as e:
            logger.warning(
                f"{self.__class__.__name__} fetch_comments failed: {e}"
            )
            return song

        comments = result.get("hotComments") if isinstance(result, dict) else []

        if comments:
            song.comments = comments

        return song

    async def fetch_lyrics(self, song: Song) -> Song:
        """Get song lyrics (default implementation)"""
        if song.lyrics:
            return song
        url = (
            f"https://api.qijieya.cn/meting/?server=netease"
            f"&type=lrc&id={song.id}"
        )
        try:
            result = await self._request(url)
            lyrics = (
                result.get("lyric") 
                if isinstance(result, dict) 
                else str(result)
            )
            song.lyrics = lyrics
            return song
        except Exception as e:
            logger.warning(
                f"{self.__class__.__name__} fetch_lyrics failed: {e}"
            )
            return song

    async def close(self):
        """Release session"""
        if not self.session.closed:
            await self.session.close()

    # ---------- Internal HTTP methods ----------

    async def _request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: dict | None = None,
        headers: dict | None = None,
        cookies: dict | None = None,
        ssl: bool = True,
    ):
        """Make HTTP request"""
        headers = headers or self.HEADERS

        if method.upper() == "POST":
            async with self.session.post(
                url, data=data, headers=headers, cookies=cookies, ssl=ssl
            ) as resp:
                return await self._parse_response(resp)

        async with self.session.get(
            url, headers=headers, cookies=cookies, ssl=ssl
        ) as resp:
            return await self._parse_response(resp)

    async def _parse_response(self, resp: aiohttp.ClientResponse):
        """Parse HTTP response"""
        try:
            resp_text = await resp.text()

            if resp.status != 200:
                logger.warning(
                    f"HTTP request returned {resp.status}: "
                    f"{resp_text[:200]}"
                )
                return None

            if not resp_text.strip():
                logger.warning("HTTP response empty")
                return None

            try:
                return json.loads(resp_text)
            except json.JSONDecodeError:
                return resp_text

        except Exception as e:
            logger.warning(f"Parse response failed: {e}")
            return None
