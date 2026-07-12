from typing import Optional
from app.services.parsers.base import BaseParser
from app.services.parsers.netease import NeteaseParser
from app.services.parsers.qqmusic import QQMusicParser
from app.services.parsers.spotify import SpotifyParser
from app.services.parsers.douyin import DouyinParser
from app.services.parsers.youtube import YouTubeParser
from app.services.parsers.bilibili import BilibiliParser


_registry: dict[str, type[BaseParser]] = {}


def register_parser(parser_class: type[BaseParser]):
    instance = parser_class()
    _registry[instance.platform] = parser_class


def get_parser(platform: str) -> Optional[BaseParser]:
    cls = _registry.get(platform)
    if cls:
        return cls()
    return None


def get_parser_for_url(url: str) -> Optional[BaseParser]:
    for cls in _registry.values():
        if cls.can_handle(url):
            return cls()
    return None


def all_parsers() -> list[BaseParser]:
    return [cls() for cls in _registry.values()]


# 注册所有解析器
register_parser(NeteaseParser)
register_parser(QQMusicParser)
register_parser(SpotifyParser)
register_parser(DouyinParser)
register_parser(YouTubeParser)
register_parser(BilibiliParser)
