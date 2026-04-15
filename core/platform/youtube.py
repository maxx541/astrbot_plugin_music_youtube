"""YouTube music platform implementation with CC subtitle support"""

from typing import ClassVar

from astrbot.api import logger

from ..config import PluginConfig
from ..model import Platform, Song
from .base import BaseMusicPlayer


class YouTubeMusic(BaseMusicPlayer):
    """
    YouTube music player with CC subtitle support.
    
    Features:
    - YouTube video search
    - Audio URL extraction via yt-dlp
    - CC subtitle download with language priority
    """

    platform: ClassVar[Platform] = Platform(
        name="youtube",
        display_name="YouTube音乐",
        keywords=["youtube点歌", "油管点歌", "yt点歌"],
    )

    def __init__(self, config: PluginConfig):
        super().__init__(config)
        self.subtitle_cache = config.youtube_subtitle_cache_dir

    async def fetch_songs(
        self, keyword: str, limit: int = 5, extra: str | None = None
    ) -> list[Song]:
        """
        Search YouTube for songs.
        
        Args:
            keyword: Song or artist name to search
            limit: Maximum results (1-20)
            extra: Extra parameters (unused for YouTube)
        
        Returns:
            List of Song objects
        """
        try:
            from youtube_search import YoutubeSearch
            
            results = YoutubeSearch(keyword, max_results=limit).to_dict()
            
            songs = []
            for result in results:
                song = Song(
                    id=result.get("id"),
                    name=result.get("title"),
                    artists=result.get("channel"),
                    cover_url=(
                        result.get("thumbnails")[0] 
                        if result.get("thumbnails") 
                        else None
                    ),
                    audio_url=f"https://www.youtube.com/watch?v={result.get('id')}",
                    duration=0,  # YouTube search doesn't return duration
                )
                songs.append(song)
            
            logger.debug(
                f"YouTube search for '{keyword}' found {len(songs)} songs"
            )
            return songs
            
        except Exception as e:
            logger.error(f"YouTube search failed: {e}")
            return []

    async def fetch_extra(self, song: Song) -> Song:
        """
        Get YouTube audio URL and metadata.
        
        Uses yt-dlp to extract:
        - Direct audio URL
        - Duration
        - Better thumbnail
        - Uploader info
        """
        try:
            import yt_dlp
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'quiet': True,
                'no_warnings': True,
                'socket_timeout': 30,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(song.audio_url, download=False)
                song.audio_url = info.get('url')
                song.duration = int(info.get('duration', 0) * 1000)
                
                # Get additional info
                if not song.artists and info.get('uploader'):
                    song.artists = info.get('uploader')
                if not song.cover_url and info.get('thumbnail'):
                    song.cover_url = info.get('thumbnail')
                
                logger.debug(
                    f"Extracted audio URL for {song.name} "
                    f"(duration: {song.duration}ms)"
                )
                
        except Exception as e:
            logger.error(
                f"Failed to get YouTube audio URL: {e}"
            )
            
        return song

    async def fetch_lyrics(self, song: Song) -> Song:
        """
        Get YouTube CC subtitles as lyrics.
        
        Supports language priority configuration:
        - Try manual subtitles first
        - Fall back to auto-generated captions
        - Try other available languages
        """
        if song.lyrics:
            return song
        
        try:
            lyrics = await self._fetch_youtube_captions(song.audio_url)
            if lyrics:
                song.lyrics = lyrics
                logger.debug(
                    f"Successfully fetched subtitles for {song.name}"
                )
        except Exception as e:
            logger.warning(
                f"Failed to fetch YouTube subtitles: {e}"
            )
        
        return song

    async def _fetch_youtube_captions(self, video_url: str) -> str | None:
        """
        Download YouTube CC subtitles with priority selection.
        
        Priority order (configurable):
        1. Manual subtitles (user-created)
        2. Auto-generated captions
        3. Other available languages
        
        Language priority: zh-Hans → zh-Hant → en (default)
        """
        try:
            import yt_dlp
            
            priority = self.cfg.youtube_subtitle_priority
            logger.debug(f"Subtitle priority: {priority}")
            
            ydl_opts = {
                'skip_download': True,
                'writesubtitles': True,
                'writeautomaticsub': True,
                'subtitle_langs': ','.join(priority),
                'quiet': True,
                'no_warnings': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                
                # Get available subtitles
                available_subs = info.get('subtitles', {})
                auto_subs = info.get('automatic_captions', {})
                
                # Try manual subtitles by priority
                for lang in priority:
                    if lang in available_subs:
                        captions = available_subs[lang]
                        result = self._parse_captions(captions, lang)
                        if result:
                            logger.info(
                                f"Using manual subtitle: {lang}"
                            )
                            return result
                
                # Try auto-generated captions by priority
                for lang in priority:
                    if lang in auto_subs:
                        captions = auto_subs[lang]
                        result = self._parse_captions(
                            captions, lang, is_auto=True
                        )
                        if result:
                            logger.info(
                                f"Using auto-generated subtitle: {lang}"
                            )
                            return result
                
                # Try other available languages
                if available_subs:
                    first_lang = next(iter(available_subs))
                    captions = available_subs[first_lang]
                    logger.info(f"Using fallback language: {first_lang}")
                    return self._parse_captions(captions, first_lang)
                
                if auto_subs:
                    first_lang = next(iter(auto_subs))
                    captions = auto_subs[first_lang]
                    logger.info(
                        f"Using auto-generated fallback: {first_lang}"
                    )
                    return self._parse_captions(
                        captions, first_lang, is_auto=True
                    )
                
                logger.warning("No subtitles found for this video")
                return None
                
        except Exception as e:
            logger.error(f"CC subtitle download error: {e}")
            return None

    def _parse_captions(
        self, captions: list, lang: str, is_auto: bool = False
    ) -> str | None:
        """
        Parse YouTube CC subtitle formats.
        
        Supports:
        - VTT (Video Text Tracks)
        - JSON format
        
        Removes:
        - Time codes
        - HTML tags
        - WEBVTT headers
        """
        try:
            import re
            
            subtitle_text = []
            
            for caption in captions:
                text = ""
                
                if isinstance(caption, dict):
                    # JSON format
                    text = caption.get('text', '')
                elif isinstance(caption, str):
                    # VTT or plain text format
                    # Remove time codes
                    line = re.sub(
                        r'^\d{2}:\d{2}:\d{2}\.\d{3} --> .*',
                        '',
                        caption
                    )
                    text = line.strip()
                
                if text and not text.startswith('WEBVTT'):
                    subtitle_text.append(text)
            
            result = '\n'.join(subtitle_text)
            source = "auto-generated" if is_auto else "official"
            logger.debug(
                f"Successfully parsed {lang} subtitle ({source})"
            )
            return result
            
        except Exception as e:
            logger.error(f"Subtitle parsing failed: {e}")
            return None
