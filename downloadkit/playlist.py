from .platforms import detect_platform
from .platforms.base import PlaylistInfo


async def parse_playlist(url: str) -> PlaylistInfo:
    """解析歌单链接，返回歌单信息"""
    platform = detect_platform(url)
    if not platform:
        raise ValueError(f"不支持的歌单链接格式。支持：music.163.com 和 y.qq.com")
    
    try:
        playlist_id = platform.extract_playlist_id(url)
    except ValueError as e:
        # 如果是单曲链接，给出明确提示
        if "single song" in str(e).lower():
            raise ValueError("检测到单曲链接，请使用单曲解析功能")
        raise ValueError(f"无法提取歌单ID: {str(e)}")
    
    try:
        return await platform.get_playlist(playlist_id)
    except Exception as e:
        # 提供更友好的错误信息
        error_msg = str(e)
        if "Failed" in error_msg or "Unknown error" in error_msg:
            raise ValueError(f"歌单解析失败，可能原因：歌单不存在、需要登录、或网络问题。原始错误：{error_msg}")
        raise ValueError(f"歌单解析失败: {error_msg}")
