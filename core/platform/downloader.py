"""Audio file downloader with caching support"""

import shutil
import uuid
from pathlib import Path

import aiofiles
import aiohttp

from astrbot.api import logger

from .config import PluginConfig


class Downloader:
    """Download and cache audio files"""

    def __init__(self, config: PluginConfig):
        self.cfg = config
        self.songs_dir = self.cfg.songs_dir
        self.session = aiohttp.ClientSession(
            proxy=self.cfg.http_proxy
        )

    async def initialize(self):
        """Initialize downloader (clear cache if configured)"""
        if self.cfg.clear_cache:
            self._ensure_cache_dir()

    async def close(self):
        """Close HTTP session"""
        await self.session.close()

    def _ensure_cache_dir(self) -> None:
        """Rebuild cache directory: clear if exists, create if not"""
        if self.songs_dir.exists():
            shutil.rmtree(self.songs_dir)
        self.songs_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Cache directory rebuilt: {self.songs_dir}")

    async def download_image(
        self, url: str, close_ssl: bool = True
    ) -> bytes | None:
        """Download image file"""
        url = (
            url.replace("https://", "http://") 
            if close_ssl 
            else url
        )
        try:
            async with self.session.get(url) as response:
                img_bytes = await response.read()
                return img_bytes
        except Exception as e:
            logger.error(f"Image download failed: {e}")

    async def download_song(self, url: str) -> Path | None:
        """
        Download audio file and return save path.
        
        Args:
            url: Audio file URL
        
        Returns:
            Path to saved file, or None if failed
        """
        song_uuid = uuid.uuid4().hex
        file_path = self.songs_dir / f"{song_uuid}.mp3"
        try:
            async with self.session.get(url) as response:
                if response.status != 200:
                    logger.error(
                        f"Audio download failed, HTTP {response.status}"
                    )
                    return None
                # Stream write
                async with aiofiles.open(file_path, "wb") as f:
                    async for chunk in response.content.iter_chunked(1024):
                        await f.write(chunk)

            logger.debug(f"Audio download complete: {file_path}")
            return file_path

        except Exception as e:
            logger.error(f"Audio download error: {e}")
            return None
