"""Music platform abstraction layer"""

from .base import BaseMusicPlayer
from .youtube import YouTubeMusic

__all__ = ["YouTubeMusic", "BaseMusicPlayer"]
