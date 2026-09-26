"""元数据补全引擎 -- 下载后从平台拉取完整的歌曲元数据（详情、歌词、封面）。"""

import logging
from typing import Optional

from .platforms.base import SongInfo, BasePlatform
from .platforms import PLATFORM_MAP

logger = logging.getLogger(__name__)

# fallback 匹配时允许的时长误差（秒）
_DURATION_TOLERANCE = 3


async def enrich_metadata(song: SongInfo) -> SongInfo:
    """补全歌曲元数据。

    流程:
      1. 如果 song 已有 song_id → 直接调 get_song_detail + get_lyrics
      2. 如果没有 song_id → 搜索平台匹配 → 用匹配到的 song_id 补全
      3. 将补全的数据合并到原 SongInfo 返回

    Args:
        song: 原始 SongInfo（至少包含 title 和 artist）

    Returns:
        补全后的 SongInfo（缺失的字段留空，不阻塞）。
    """
    platform = _get_platform(song.platform)
    if not platform:
        return song

    enriched = SongInfo(
        title=song.title,
        artist=song.artist,
        platform=song.platform,
        url=song.url,
        song_id=song.song_id,
    )

    # ── 有 song_id：直接补全 ──────────────────────────────────
    if song.song_id:
        detail = await platform.get_song_detail(song.song_id)
        if detail:
            _merge_detail(enriched, detail)

        lyrics = await platform.get_lyrics(song.song_id)
        if lyrics:
            enriched.lyrics, enriched.lyrics_trans = lyrics
        return enriched

    # ── 无 song_id：搜索匹配 ────────────────────────────────────
    matched = await _search_and_match(platform, song.title, song.artist, song.duration)
    if matched and matched.song_id:
        enriched.song_id = matched.song_id
        # 补全详情
        detail = await platform.get_song_detail(matched.song_id)
        if detail:
            _merge_detail(enriched, detail)
        # 补全歌词
        lyrics = await platform.get_lyrics(matched.song_id)
        if lyrics:
            enriched.lyrics, enriched.lyrics_trans = lyrics
        logger.info(f"[enricher] fallback 匹配成功: {song.title} - {song.artist} → {matched.song_id}")
    else:
        # fallback 匹配失败：只写基础信息，不上封面/歌词
        logger.info(f"[enricher] fallback 匹配失败，写基础标签: {song.title} - {song.artist}")

    return enriched


def _get_platform(name: str) -> Optional[BasePlatform]:
    """按名称获取平台实例。"""
    if not name:
        return None
    return PLATFORM_MAP.get(name)


def _merge_detail(target: SongInfo, detail: SongInfo):
    """将 detail 的非空字段合并到 target。"""
    if detail.title and not target.title:
        target.title = detail.title
    if detail.artist and not target.artist:
        target.artist = detail.artist
    if detail.album:
        target.album = detail.album
    if detail.cover:
        target.cover = detail.cover
    if detail.duration:
        target.duration = detail.duration
    if detail.track_number:
        target.track_number = detail.track_number
    if detail.year:
        target.year = detail.year
    if detail.genre:
        target.genre = detail.genre
    if detail.song_id and not target.song_id:
        target.song_id = detail.song_id


async def _search_and_match(
    platform: BasePlatform, title: str, artist: str, duration: int,
) -> Optional[SongInfo]:
    """搜索平台并用 duration 交叉验证，返回最佳匹配。

    逻辑:
      1. 用 title + artist 搜索，取前 5 个结果
      2. 如果有 duration，选差值 < _DURATION_TOLERANCE 的第一个
      3. 没有 duration 或没匹配上，选第一个结果
      4. 搜索不到返回 None
    """
    keyword = f"{title} {artist}"
    try:
        results = await platform.search(keyword, limit=5)
    except Exception as e:
        logger.debug(f"[enricher] 搜索失败: {e}")
        return None

    if not results:
        return None

    if duration > 0:
        for r in results:
            if r.duration > 0 and abs(r.duration - duration) <= _DURATION_TOLERANCE:
                return r

    # 没有 duration 或没有精确匹配 → 返回第一个结果
    return results[0]
