import asyncio
from .platforms import PLATFORMS
from .platforms.base import SongInfo

# 平台优先级：QQ音乐 > 网易云 > 其他
PLATFORM_PRIORITY = {
    'qqmusic': 0,
    'netease': 1,
}


def _match_score(keyword: str, title: str, artist: str) -> int:
    """计算关键词匹配度，分数越高越匹配。"""
    kw = keyword.strip().lower()
    t = title.strip().lower()
    a = artist.strip().lower()
    
    # 完全匹配标题
    if kw == t:
        return 100
    # 标题包含关键词
    if kw in t:
        return 80
    # 歌手包含关键词
    if kw in a:
        return 60
    # 标题或歌手部分匹配
    for word in kw.split():
        if word in t or word in a:
            return 40
    return 0


async def search_all(keyword: str, limit: int = 20) -> list[SongInfo]:
    tasks = [p.search(keyword, limit) for p in PLATFORMS]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_songs: list[SongInfo] = []
    seen: set[tuple[str, str]] = set()
    for songs in results:
        if isinstance(songs, Exception):
            continue
        for song in songs:
            key = (song.title.strip().lower(), song.artist.strip().lower())
            if key not in seen:
                seen.add(key)
                all_songs.append(song)
    
    # 排序：平台优先级 + 关键词匹配度
    all_songs.sort(key=lambda s: (
        PLATFORM_PRIORITY.get(s.platform, 99),
        -_match_score(keyword, s.title, s.artist),
    ))
    
    return all_songs
