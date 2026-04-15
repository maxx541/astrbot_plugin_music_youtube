"""Data models for music and platform information"""

from dataclasses import dataclass


@dataclass(slots=True)
class Song:
    """Song data model"""
    
    id: str
    """Song unique identifier (e.g., YouTube video ID)"""

    name: str | None = None
    """Song original name"""

    artists: str | None = None
    """Artist/performer name"""

    duration: int | None = None
    """Duration in milliseconds"""

    title: str | None = None
    """Supplementary display name"""

    author: str | None = None
    """Supplementary author/artist name"""

    cover_url: str | None = None
    """Cover image URL"""

    audio_url: str | None = None
    """Audio playback URL"""

    path: str | None = None
    """Local audio file path (reserved for persistence)"""

    lyrics: str | None = None
    """Song lyrics or CC subtitles"""

    comments: list | None = None
    """Comments list"""

    note: str | None = None
    """Note (e.g., source or extra information)"""

    def to_lines(self) -> str:
        """Format song information into multi-line text"""
        lines = [
            f"ID: {self.id}",
            f"名称: {self.name or self.title or '未知'}",
            f"艺人: {self.artists or self.author or '未知'}",
        ]
        if self.duration:
            mins, secs = divmod(self.duration // 1000, 60)
            lines.append(f"时长: {mins}:{secs:02d}")
        if self.audio_url:
            lines.append(f"播放链接: {self.audio_url}")
        if self.cover_url:
            lines.append(f"封面: {self.cover_url}")
        if self.note:
            lines.append(f"备注: {self.note}")
        return "\n".join(lines)


@dataclass(slots=True)
class Platform:
    """Platform information model"""

    name: str
    """Platform internal name"""
    
    display_name: str
    """Platform display name"""
    
    keywords: list[str]
    """Platform trigger keywords"""
