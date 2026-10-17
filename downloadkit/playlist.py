from .platforms import detect_platform
from .platforms.base import PlaylistInfo
from .platforms.soda import parse_playlist as soda_parse_playlist

# 汽水歌单 URL 模式
_SODA_PLAYLIST_PATTERNS = [
    "qishui.douyin.com/s/",
    "www.douyin.com/qishui/",
]


async def parse_playlist(url: str) -> PlaylistInfo:
    """解析歌单链接，返回歌单信息"""
    platform = detect_platform(url)
    if platform:
        try:
            playlist_id = platform.extract_playlist_id(url)
        except ValueError as e:
            if "single song" in str(e).lower():
                raise ValueError("检测到单曲链接，请使用单曲解析功能")
            raise ValueError(f"无法提取歌单ID: {str(e)}")
        try:
            return await platform.get_playlist(playlist_id)
        except Exception as e:
            error_msg = str(e)
            if "Failed" in error_msg or "Unknown error" in error_msg:
                raise ValueError(f"歌单解析失败，可能原因：歌单不存在、需要登录、或网络问题。原始错误：{error_msg}")
            raise ValueError(f"歌单解析失败: {error_msg}")

    # 兜底：汽水歌单（不通过 BasePlatform，直接调用独立函数）
    if any(p in url for p in _SODA_PLAYLIST_PATTERNS):
        return await _parse_soda_playlist(url)

    raise ValueError(f"不支持的歌单链接格式。支持：music.163.com、y.qq.com、qishui.douyin.com")


async def _parse_soda_playlist(url: str) -> PlaylistInfo:
    """解析汽水歌单，转换为标准 PlaylistInfo。"""
    from .platforms.base import SongInfo
    result = await soda_parse_playlist(url)
    if not result:
        raise ValueError("无法解析该汽水歌单，可能歌单不存在或已失效")

    songs = []
    for s in result.get("songs", []):
        songs.append(SongInfo(
            title=s.get("name") or "",
            artist=s.get("artist") or "",
            album=s.get("album") or "",
            platform="soda",
            song_id=s.get("track_id") or "",
        ))

    return PlaylistInfo(
        name=result.get("name") or "汽水歌单",
        platform="soda",
        song_count=result.get("song_count") or len(songs),
        songs=songs,
    )
