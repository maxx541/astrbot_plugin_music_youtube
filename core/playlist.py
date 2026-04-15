"""User playlist management with SQLite storage"""

import asyncio
import sqlite3

from astrbot.api import logger

from .config import PluginConfig
from .model import Song


class Playlist:
    """User playlist manager with SQLite backend"""

    def __init__(self, config: PluginConfig):
        """
        Initialize playlist manager.
        
        Args:
            config: Plugin configuration
        """
        self.cfg = config
        self.playlist_dir = self.cfg.playlist_dir
        self.db_path = self.cfg.db_path
        self.limit = self.cfg.playlist_limit

        self._conn: sqlite3.Connection = None  # type: ignore
        self._lock = asyncio.Lock()

    async def initialize(self):
        """Initialize database table"""
        async with self._lock:
            self._conn = sqlite3.connect(str(self.db_path))
            self._conn.row_factory = sqlite3.Row
            cursor = self._conn.cursor()

            # Create playlist table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS playlist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    song_id TEXT NOT NULL,
                    song_name TEXT,
                    artists TEXT,
                    duration INTEGER,
                    cover_url TEXT,
                    audio_url TEXT,
                    platform TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, song_id, platform)
                )
            """)

            # Create index
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_id 
                ON playlist(user_id)
            """)

            self._conn.commit()
            logger.info("Playlist database initialized")

    async def close(self):
        """Close database connection"""
        async with self._lock:
            if self._conn:
                self._conn.close()
                self._conn = None  # type: ignore

    async def add_song(
        self, user_id: str, song: Song, platform: str
    ) -> bool:
        """
        Add song to playlist.
        
        Args:
            user_id: User ID
            song: Song object
            platform: Platform name
        
        Returns:
            True if added successfully, False if already exists
        """
        async with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO playlist
                    (user_id, song_id, song_name, artists, 
                     duration, cover_url, audio_url, platform)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        user_id,
                        song.id,
                        song.name,
                        song.artists,
                        song.duration,
                        song.cover_url,
                        song.audio_url,
                        platform,
                    ),
                )
                self._conn.commit()
                logger.debug(
                    f"User {user_id} added song: {song.name}"
                )
                return True
            except sqlite3.IntegrityError:
                logger.debug(
                    f"Song {song.name} already in user {user_id} playlist"
                )
                return False
            except Exception as e:
                logger.error(f"Add song to playlist failed: {e}")
                return False

    async def remove_song(
        self, user_id: str, song_id: str, platform: str
    ) -> bool:
        """
        Remove song from playlist.
        
        Args:
            user_id: User ID
            song_id: Song ID
            platform: Platform name
        
        Returns:
            True if removed, False if not found
        """
        async with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute(
                    """
                    DELETE FROM playlist
                    WHERE user_id = ? AND song_id = ? AND platform = ?
                """,
                    (user_id, song_id, platform),
                )
                self._conn.commit()

                if cursor.rowcount > 0:
                    logger.debug(
                        f"User {user_id} removed song: {song_id}"
                    )
                    return True
                else:
                    logger.debug(
                        f"Song {song_id} not in user {user_id} playlist"
                    )
                    return False
            except Exception as e:
                logger.error(f"Remove song from playlist failed: {e}")
                return False

    async def get_songs(
        self, user_id: str, limit: int | None = None
    ) -> list[tuple[Song, str]]:
        """
        Get user's playlist.
        
        Args:
            user_id: User ID
            limit: Result limit (uses config limit if None)
        
        Returns:
            List of (Song, platform_name) tuples
        """
        if limit is None:
            limit = self.limit

        async with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute(
                    """
                    SELECT song_id, song_name, artists, duration, 
                           cover_url, audio_url, platform
                    FROM playlist
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """,
                    (user_id, limit),
                )

                rows = cursor.fetchall()
                result = []
                for row in rows:
                    song = Song(
                        id=row["song_id"],
                        name=row["song_name"],
                        artists=row["artists"],
                        duration=row["duration"],
                        cover_url=row["cover_url"],
                        audio_url=row["audio_url"],
                    )
                    platform = row["platform"]
                    result.append((song, platform))

                return result
            except Exception as e:
                logger.error(f"Get user playlist failed: {e}")
                return []

    async def has_song(
        self, user_id: str, song_id: str, platform: str
    ) -> bool:
        """
        Check if song is in playlist.
        
        Args:
            user_id: User ID
            song_id: Song ID
            platform: Platform name
        
        Returns:
            True if exists, False otherwise
        """
        async with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute(
                    """
                    SELECT COUNT(*) as count FROM playlist
                    WHERE user_id = ? AND song_id = ? AND platform = ?
                """,
                    (user_id, song_id, platform),
                )

                row = cursor.fetchone()
                return row["count"] > 0
            except Exception as e:
                logger.error(f"Check song in playlist failed: {e}")
                return False

    async def get_count(self, user_id: str) -> int:
        """
        Get playlist song count.
        
        Args:
            user_id: User ID
        
        Returns:
            Number of songs
        """
        async with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute(
                    """
                    SELECT COUNT(*) as count FROM playlist
                    WHERE user_id = ?
                """,
                    (user_id,),
                )

                row = cursor.fetchone()
                return row["count"]
            except Exception as e:
                logger.error(f"Get playlist count failed: {e}")
                return 0

    async def is_empty(self, user_id: str) -> bool:
        """
        Check if playlist is empty.
        
        Args:
            user_id: User ID
        
        Returns:
            True if empty, False otherwise
        """
        async with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute(
                    """
                    SELECT 1 FROM playlist WHERE user_id = ? LIMIT 1
                """,
                    (user_id,),
                )

                row = cursor.fetchone()
                return row is None
            except Exception as e:
                logger.error(f"Check playlist empty failed: {e}")
                return True  # Default to empty on error

    async def clear(self, user_id: str) -> bool:
        """
        Clear user's playlist.
        
        Args:
            user_id: User ID
        
        Returns:
            True if cleared successfully
        """
        async with self._lock:
            try:
                cursor = self._conn.cursor()
                cursor.execute(
                    """
                    DELETE FROM playlist WHERE user_id = ?
                """,
                    (user_id,),
                )
                self._conn.commit()
                logger.debug(f"User {user_id} cleared playlist")
                return True
            except Exception as e:
                logger.error(f"Clear playlist failed: {e}")
                return False
