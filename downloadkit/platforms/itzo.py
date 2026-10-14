"""itzo.cn download source -- https://music.itzo.cn (JSON API)"""

import json, httpx

SEARCH_URL = "https://music.itzo.cn/a.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://music.itzo.cn",
    "Referer": "https://music.itzo.cn/",
}


async def search_and_get_url(title: str, artist: str,
                             types: tuple[str, ...] = ("qq", "netease")) -> str | None:
    """Search itzo.cn and return best-match download URL.

    ``types`` 按优先级依次尝试。默认先 qq：``type=netease`` 返回的就是
    ``music.163.com/song/media/outer/url``，与下载引擎 Step 1 完全同源，
    VIP 歌曲必然和 Step 1 一起吃 HTML，等于白跑一级；而 ``type=qq`` 返回
    带 vkey 的真实 QQ 直链（m4a），是真正独立的兜底。netease 留作第二顺位，
    万一 Step 1 只是偶发网络失败还能再试一次。
    """
    keyword = f"{title} {artist}"

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for src_type in types:
            data = {"input": keyword, "filter": "name", "type": src_type, "page": "1"}
            url = await _search_one(client, data, title, artist, src_type)
            if url:
                return url
    return None


async def _search_one(client: httpx.AsyncClient, data: dict, title: str,
                      artist: str, src_type: str) -> str | None:
    try:
        resp = await client.post(SEARCH_URL, data=data, headers=HEADERS)
        if resp.status_code != 200:
            return None

        result = resp.json()
    except Exception:
        return None

    items = result.get("data", [])
    if not items:
        return None

    # Match by title + artist
    clean_title = title.strip().lower()
    clean_artist = artist.split("/")[0].strip().lower()
    best = items[0]  # default: first result

    for item in items:
        item_title = item.get("title", "").strip().lower()
        item_artist = item.get("author", "").split(",")[0].strip().lower()
        if clean_title in item_title and clean_artist in item_artist:
            best = item
            break
        # Fallback: title match only
        if clean_title in item_title and best == items[0]:
            best = item

    url = best.get("url", "")
    if url:
        url = url.replace("http:", "https:")
    return url or None
