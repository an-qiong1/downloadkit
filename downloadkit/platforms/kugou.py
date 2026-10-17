"""酷狗音乐下载源 -- http://www.kugou.com/

搜索接口：https://songsearch.kugou.com/song_search_v2
直链获取：通过 FileHash 查询 getSongInfo.php + 第三方 API 回退
"""

import logging

import httpx

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://songsearch.kugou.com/song_search_v2"
_SONG_INFO_URL = "https://m.kugou.com/app/i/getSongInfo.php"
_BAKA_API = "https://api.baka.plus/meting/"
_LZMHHH_API = "https://music.lzmhhh.com/api/music/url"
_GDSTUDIO_API = "https://music-api.gdstudio.xyz/api.php"


def _find_hash(items: list[dict], title: str, artist: str) -> str | None:
    """在搜索结果中匹配歌曲，返回 FileHash。"""
    clean_title = title.strip().lower()
    clean_artist = artist.split("/")[0].strip().lower()

    for item in items:
        song_name = (item.get("FileName") or item.get("SongName") or "").strip().lower()
        singer_name = (item.get("SingerName") or item.get("singername") or "").strip().lower()
        if clean_title in song_name and (not clean_artist or clean_artist in singer_name):
            return item.get("FileHash") or item.get("hash")
        if clean_title in song_name:
            return item.get("FileHash") or item.get("hash")

    if items:
        return items[0].get("FileHash") or items[0].get("hash")
    return None


async def _try_baka_api(file_hash: str) -> str | None:
    """尝试 baka.plus 第三方 API。"""
    url = (
        f"{_BAKA_API}meting/?server=kugou&type=url&id={file_hash}&br=2000"
    )
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, trust_env=False) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
            # baka 返回重定向，最终 URL 即为直链
            final_url = str(r.url)
            if final_url.startswith("http") and "error" not in final_url.lower():
                # 验证链接可达
                r2 = await c.head(final_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                if r2.status_code in (200, 206):
                    return final_url
    except Exception as e:
        logger.debug(f"[kugou] baka failed: {e}")
    return None


async def _try_lzmhhh_api(file_hash: str) -> str | None:
    """尝试 lzmhhh.com 第三方 API。"""
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, trust_env=False) as c:
            r = await c.post(
                _LZMHHH_API,
                json={"id": file_hash, "type": "kg"},
                headers={
                    "User-Agent": "Mozilla/5.0",
                    "Referer": "https://music.lzmhhh.com/",
                    "Origin": "https://music.lzmhhh.com",
                },
            )
            if r.status_code == 200:
                data = r.json()
                dl_url = data.get("data") or ""
                if dl_url and dl_url.startswith("http"):
                    return dl_url
    except Exception as e:
        logger.debug(f"[kugou] lzmhhh failed: {e}")
    return None


async def _try_gdstudio_api(file_hash: str) -> str | None:
    """尝试 gdstudio.xyz 第三方 API。"""
    url = f"{_GDSTUDIO_API}?types=url&id={file_hash}&source=kugou&br=999"
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, trust_env=False) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                data = r.json()
                dl_url = data.get("url") or ""
                if dl_url and dl_url.startswith("http"):
                    return dl_url
    except Exception as e:
        logger.debug(f"[kugou] gdstudio failed: {e}")
    return None


async def search_and_get_url(title: str, artist: str) -> str | None:
    """搜索酷狗音乐并返回最佳匹配下载 URL。取不到时返回 None。"""
    keyword = f"{title} {artist}"

    async with httpx.AsyncClient(timeout=12, follow_redirects=True, trust_env=False) as c:
        # Step 1: 搜索
        try:
            r = await c.get(
                _SEARCH_URL,
                params={
                    "keyword": keyword,
                    "platform": "WebFilter",
                    "page": "1",
                    "pagesize": "10",
                },
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            if r.status_code != 200:
                return None
            data = r.json()
            items = data.get("data", {}).get("lists") or []
        except Exception as e:
            logger.info(f"[kugou] 搜索失败: {e}")
            return None

        file_hash = _find_hash(items, title, artist)
        if not file_hash:
            logger.info(f"[kugou] 未找到匹配歌曲: {keyword}")
            return None

        logger.info(f"[kugou] 找到歌曲 FileHash={file_hash}")

        # Step 2: 依次尝试各下载源
        for try_fn in [_try_baka_api, _try_lzmhhh_api, _try_gdstudio_api]:
            url = await try_fn(file_hash)
            if url:
                return url

        logger.info(f"[kugou] 所有下载源均不可用，跳过")
        return None
