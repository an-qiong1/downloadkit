"""咪咕音乐下载源 -- 搜索 API 并返回直链。"""

import re
import httpx

MIGU_SEARCH = "https://m.music.migu.cn/migu/remoting/scr_search_tag"


def _clean_artist(artist: str) -> str:
    """提取第一个歌手名。"""
    return artist.split("/")[0].strip()


async def search_and_get_url(title: str, artist: str) -> str | None:
    """搜索咪咕音乐并返回最佳匹配下载 URL。"""
    keyword = f"{title} {_clean_artist(artist)}"
    params = {
        "keyword": keyword,
        "type": 2,
        "pgc": 1,
        "rows": 10,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://m.music.migu.cn/",
    }

    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
        resp = await client.get(MIGU_SEARCH, params=params, headers=headers)
        data = resp.json()

    songs = data.get("musics", [])
    if not songs:
        return None

    # Try to find an exact match first, then fall back to first result
    best = None
    clean_title = title.strip().lower()
    clean_artist = _clean_artist(artist).strip().lower()

    for song in songs:
        s_title = song.get("songName", "").strip().lower()
        s_artist = song.get("singerName", "").strip().lower()
        if best is None:
            best = song
        if s_title == clean_title and s_artist == clean_artist:
            best = song
            break

    if not best:
        return None

    # Extract download URL
    rate_list = best.get("rateFormats", []) or best.get("newRateFormats", [])
    if rate_list:
        # Prefer highest quality: flac > 320k > 128k
        for fmt in rate_list:
            url = fmt.get("url") or fmt.get("androidUrl") or fmt.get("iosUrl")
            if url:
                return url

    # Fallback: try old format fields
    for field in ["mp3", "songUrl", "listenUrl"]:
        url = best.get(field)
        if url:
            return url

    return None
