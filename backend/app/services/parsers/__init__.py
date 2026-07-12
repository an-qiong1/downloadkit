from app.services.parsers.base import BaseParser
from app.services.parsers.netease import NeteaseParser
from app.services.parsers.qqmusic import QQMusicParser
from app.services.parsers.spotify import SpotifyParser
from app.services.parsers.douyin import DouyinParser
from app.services.parsers.youtube import YouTubeParser
from app.services.parsers.bilibili import BilibiliParser

__all__ = ["BaseParser", "NeteaseParser", "QQMusicParser", "SpotifyParser", "DouyinParser",
           "YouTubeParser", "BilibiliParser"]
