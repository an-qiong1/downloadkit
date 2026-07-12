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


async def search_and_get_url(title: str, artist: str) -> str | None:
    """Search itzo.cn and return best-match download URL."""
    keyword = f"{title} {artist}"
    data = {"input": keyword, "filter": "name", "type": "netease", "page": "1"}

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        resp = await client.post(SEARCH_URL, data=data, headers=HEADERS)
        if resp.status_code != 200:
            return None

        try:
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
