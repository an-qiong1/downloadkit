"""
BT 磁力搜索引擎模块
聚合多个 BT 搜索引擎来源，返回磁力链接和元数据
"""
import re
import httpx
from typing import Optional
from pydantic import BaseModel


class TorrentResult(BaseModel):
    title: str
    magnet: str
    size: str = ""
    seeders: int = 0
    leechers: int = 0
    source: str = ""


async def search_btmet(keyword: str) -> list[TorrentResult]:
    """搜索 btmet.com"""
    results = []
    try:
        url = f"https://btmet.com/search/{keyword}/1/1/0"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        }
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return results

            html = resp.text
            magnet_pattern = r'magnet:\?xt=urn:btih:[a-zA-Z0-9]+'
            title_pattern = r'<a[^>]+rel="bookmark"[^>]*>([^<]+)</a>'
            size_pattern = r'<td[^>]*>(\d+\.?\d*\s*(?:GB|MB|KB))</td>'
            magnets = re.findall(magnet_pattern, html)
            titles = re.findall(title_pattern, html)
            sizes = re.findall(size_pattern, html)

            for i, magnet in enumerate(magnets):
                title = titles[i].strip() if i < len(titles) else f"BT资源 {i}"
                size = sizes[i] if i < len(sizes) else ""
                title = re.sub(r'<[^>]+>', '', title)
                title = title.replace('&#038;', '&').replace('&#39;', "'")
                results.append(TorrentResult(title=title, magnet=magnet, size=size, source="btmet"))
    except Exception:
        pass
    return results


async def search_btsow(keyword: str) -> list[TorrentResult]:
    results = []
    try:
        url = f"https://btsow.buzz/search/{keyword}"
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "text/html,application/xhtml+xml"}
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return results
            html = resp.text
            magnet_pattern = r'href="(magnet:\?xt=urn:btih:[a-zA-Z0-9]+)"'
            title_pattern2 = r'<a[^>]+href="magnet:[^"]*"[^>]*>([^<]+)</a>'
            magnets = re.findall(magnet_pattern, html)
            titles = re.findall(title_pattern2, html)
            for i, magnet in enumerate(magnets):
                title = titles[i].strip() if i < len(titles) else f"BT资源 {i}"
                title = re.sub(r'<[^>]+>', '', title).replace('&#038;', '&').replace('&#39;', "'")
                results.append(TorrentResult(title=title, magnet=magnet, source="btsow"))
    except Exception:
        pass
    return results


async def search_torlock(keyword: str) -> list[TorrentResult]:
    results = []
    try:
        url = f"https://www.torlock.com/torrents/{keyword}.html"
        headers = {"User-Agent": "Mozilla/5.0"}
        async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return results
            html = resp.text
            magnet_pattern = r'(magnet:\?xt=urn:btih:[a-zA-Z0-9]+)'
            magnets = re.findall(magnet_pattern, html)
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
            for i, row in enumerate(rows):
                if i >= len(magnets):
                    break
                title_m = re.search(r'<a[^>]+href="/torrent/\d+/[^"]*"[^>]*>([^<]+)</a>', row)
                size_m = re.search(r'<td[^>]*>(\d+\.?\d*\s*(?:GB|MB|KB))</td>', row)
                seeds_m = re.search(r'<td[^>]*class="[^"]*s"[^>]*>(\d+)</td>', row)
                title = title_m.group(1).strip() if title_m else f"BT资源 {i}"
                title = re.sub(r'<[^>]+>', '', title)
                results.append(TorrentResult(
                    title=title, magnet=magnets[i],
                    size=size_m.group(1) if size_m else "",
                    seeders=int(seeds_m.group(1)) if seeds_m else 0,
                    source="torlock",
                ))
    except Exception:
        pass
    return results


async def search_torrents(keyword: str, sources: Optional[list[str]] = None) -> list[TorrentResult]:
    """
    聚合搜索所有 BT 来源
    sources: 指定搜索源，默认搜索全部
    """
    import asyncio

    source_map = {
        "btmet": search_btmet,
        "btsow": search_btsow,
        "torlock": search_torlock,
    }

    if sources:
        sources_to_search = [s for s in sources if s in source_map]
    else:
        sources_to_search = list(source_map.keys())

    tasks = []
    for src in sources_to_search:
        tasks.append(source_map[src](keyword))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_results = []
    seen_magnets = set()
    for result_list in results:
        if isinstance(result_list, Exception):
            continue
        for r in result_list:
            if r.magnet not in seen_magnets:
                seen_magnets.add(r.magnet)
                all_results.append(r)

    # 按种子数排序（如果有）
    all_results.sort(key=lambda x: x.seeders, reverse=True)
    return all_results
