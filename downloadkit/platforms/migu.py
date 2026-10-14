"""咪咕音乐下载源 -- 搜索 API 并返回直链。

2026-10-14 现状：``scr_search_tag`` 已于改版后 301 到 ``/v5`` SPA 壳，
所有已知搜索接口（remoting/*、v5/api/*、app.c.migu.cn/*）一律返回 HTML
或域名已不解析，拿不到 JSON。这里不再让 ``resp.json()`` 抛
``JSONDecodeError`` 每首歌刷一条 ERROR，而是识别非 JSON 响应后直接返回
None，把这一级让给后面的 yt-dlp。若将来接口恢复，下面的解析逻辑无需改动。
"""

import logging

import httpx

logger = logging.getLogger(__name__)

MIGU_SEARCH = "https://m.music.migu.cn/migu/remoting/scr_search_tag"


def _clean_artist(artist: str) -> str:
    """提取第一个歌手名。"""
    return artist.split("/")[0].strip()


async def search_and_get_url(title: str, artist: str) -> str | None:
    """搜索咪咕音乐并返回最佳匹配下载 URL。取不到时返回 None。"""
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

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, trust_env=False) as client:
            resp = await client.get(MIGU_SEARCH, params=params, headers=headers)
    except Exception as e:  # noqa: BLE001 - 网络异常交给上层换源
        logger.info(f"[migu] 请求失败，跳过该源: {type(e).__name__}: {e}")
        return None

    # 改版后这里会 301 到 /v5 并返回 SPA 壳，不是 JSON
    if "json" not in resp.headers.get("content-type", "").lower() and not resp.text.lstrip()[:1] in "{[":
        logger.info(
            f"[migu] 搜索接口返回非 JSON (status={resp.status_code}, "
            f"ct={resp.headers.get('content-type', '-')})，该源已失效，跳过"
        )
        return None

    try:
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        logger.info(f"[migu] 响应无法解析为 JSON，跳过该源: {e}")
        return None

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
