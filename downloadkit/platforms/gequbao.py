"""歌曲宝下载源 -- https://www.gequbao.com"""

import re
import httpx

SEARCH_URL = "https://www.gequbao.com/s/{keyword}"
MUSIC_URL = "https://www.gequbao.com/music/{aid}"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.gequbao.com/",
}


async def search_and_get_url(title: str, artist: str) -> str | None:
    """在歌曲宝搜索歌曲，返回下载链接。"""
    keyword = f"{title} {artist}"
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        # Step 1: Search
        resp = await client.get(SEARCH_URL.format(keyword=keyword), headers=HEADERS)
        print(f"  [gequbao debug] Search status: {resp.status_code}, size={len(resp.text)}", flush=True)
        if resp.status_code != 200:
            return None
        html = resp.text

        # Dump search results for debugging
        _dump_debug("gequbao_search.html", html)

        # Step 2: Find all candidate aids
        aids = re.findall(r'data-aid="(\d+)"', html)
        print(f"  [gequbao debug] Found {len(aids)} data-aid entries", flush=True)

        # Also look for song links
        song_links = re.findall(r'<a[^>]*href="(/music/\d+)"[^>]*>(.*?)</a>', html)
        print(f"  [gequbao debug] Found {len(song_links)} song links", flush=True)
        for href, text in song_links[:5]:
            print(f"    {text.strip()[:50]} -> {href}", flush=True)

        # Step 3: Find matching song
        aid = _find_aid(html, title, artist)
        if not aid and aids:
            print(f"  [gequbao debug] No exact match, trying first result", flush=True)
            aid = aids[0] if aids else None

        if not aid:
            print(f"  [gequbao debug] No aid found at all", flush=True)
            return None

        print(f"  [gequbao debug] Using aid={aid}", flush=True)

        # Step 4: Get music page
        resp = await client.get(MUSIC_URL.format(aid=aid), headers=HEADERS)
        print(f"  [gequbao debug] Music page status: {resp.status_code}, size={len(resp.text)}", flush=True)
        if resp.status_code != 200:
            return None

        _dump_debug("gequbao_music.html", resp.text)

        # Step 5: Extract download URL
        url = _extract_download_url(resp.text)
        if url:
            print(f"  [gequbao debug] Download URL found: {url[:100]}", flush=True)
        else:
            print(f"  [gequbao debug] No download URL found in music page", flush=True)
            # Print all hrefs for debugging
            hrefs = re.findall(r'href="([^"]+)"', resp.text)
            mp3_links = [h for h in hrefs if '.mp3' in h.lower()]
            if mp3_links:
                print(f"    MP3 links in page: {mp3_links[:5]}", flush=True)

        return url


def _dump_debug(filename: str, html: str):
    """Save HTML for debugging."""
    try:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(html[:50000])  # First 50KB
    except Exception:
        pass


def _find_aid(html: str, title: str, artist: str) -> str | None:
    clean_title = title.strip().lower()
    clean_artist = artist.split("/")[0].strip().lower()

    # Strategy 1: Find song links and match by title text
    song_pattern = re.compile(
        r'<a[^>]*href="(/music/(\d+))"[^>]*>\s*(.*?)\s*</a>',
        re.DOTALL | re.I,
    )
    for m in song_pattern.finditer(html):
        aid = m.group(2)
        link_text = re.sub(r'<[^>]+>', '', m.group(3)).strip().lower()
        if clean_title in link_text and (not clean_artist or clean_artist in link_text):
            return aid

    # Strategy 2: Fallback - just match title
    for m in song_pattern.finditer(html):
        aid = m.group(2)
        link_text = re.sub(r'<[^>]+>', '', m.group(3)).strip().lower()
        if clean_title in link_text:
            return aid

    return None


def _extract_download_url(html: str) -> str | None:
    # Strategy 1: Direct MP3 links
    m = re.search(r'(?:href|src)=["\']([^"\']*\.mp3[^"\']*)["\']', html, re.I)
    if m:
        url = m.group(1)
        if url.startswith("//"):
            url = "https:" + url
        return url

    # Strategy 2: window.open or JavaScript redirects
    m = re.search(r"window\.(?:open|location)\s*[=\(]\s*['\"]([^'\"]+)['\"]", html, re.I)
    if m:
        return m.group(1)

    # Strategy 3: data-url or url attributes
    m = re.search(r'data-(?:url|src|mp3)\s*=\s*["\']([^"\']+)["\']', html, re.I)
    if m:
        return m.group(1)

    # Strategy 4: Any link containing 'down' or 'play'
    m = re.search(r'href=["\']([^"\']*(?:down|play|get)\w*\.php\?[^"\']*)["\']', html, re.I)
    if m:
        return m.group(1)

    return None
