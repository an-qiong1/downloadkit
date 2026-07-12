from .base import BasePlatform
from .netease import NeteasePlatform
from .qqmusic import QQMusicPlatform

PLATFORMS: list[BasePlatform] = [NeteasePlatform(), QQMusicPlatform()]
PLATFORM_MAP: dict[str, BasePlatform] = {p.name: p for p in PLATFORMS}


def detect_platform(url: str) -> BasePlatform | None:
    for p in PLATFORMS:
        if p.match_url(url):
            return p
    return None
