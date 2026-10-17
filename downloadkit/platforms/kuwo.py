"""酷我音乐下载源 -- http://www.kuwo.cn/

搜索接口：http://search.kuwo.cn/r.s （JSON 格式，字段含 DC_TARGETID）
直链获取：尝试官方 convert_url2 接口 + 第三方 API 回退（lxmusic / nxinxz）
"""

import logging
import re
import urllib.parse

import httpx

logger = logging.getLogger(__name__)

_SEARCH_URL = "http://search.kuwo.cn/r.s"
_OFFICIAL_DL_URL = "http://mobi.kuwo.cn/mobi.s"
_LX_MUSIC_API = "https://lxmusicapi.onrender.com/url/kw/{song_id}/flac"
_NXINXZ_API = "http://music.nxinxz.com/kw.php?id={song_id}&level=lossless&type=json"


def _encrypt_kuwo_query(query: str) -> str:
    """酷我官方接口的简单旋转加密。"""
    raw = query.encode()
    enc = []
    for i, b in enumerate(raw):
        enc.append(chr((b + i) % 128))
    return urllib.parse.quote("".join(enc))


def _parse_search_result(resp_text: str) -> list[dict] | None:
    """解析酷我搜索响应（可能是 JSON 也可能是 GB2312 文本）。"""
    # 先尝试 JSON
    try:
        import json
        d = json.loads(resp_text)
        return d.get("abslist") or []
    except Exception:
        pass
    # 尝试从 text/plain 格式解析
    items = []
    current: dict = {}
    for line in resp_text.strip().split("\n"):
        if "=" in line:
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip()
            if key == "RN" or key in ("PN", "SHOW", "TOTAL", "HIT"):
                if current and current.get("SONGNAME"):
                    items.append(current)
                current = {}
            current[key] = val
    if current and current.get("SONGNAME"):
        items.append(current)
    return items


def _find_song_id(items: list[dict], title: str, artist: str) -> str | None:
    """在搜索结果中匹配歌曲，返回 DC_TARGETID。"""
    clean_title = title.strip().lower()
    clean_artist = artist.split("/")[0].strip().lower()

    for item in items:
        song_name = (item.get("SONGNAME") or item.get("NAME") or "").strip().lower()
        artist_name = (item.get("AARTIST") or item.get("ARTIST") or "").strip().lower()
        if clean_title in song_name and (not clean_artist or clean_artist in artist_name):
            return item.get("DC_TARGETID") or item.get("MUSICID") or item.get("SONGID")
        if clean_title in song_name:
            return item.get("DC_TARGETID") or item.get("MUSICID") or item.get("SONGID")

    # 兜底：返回第一个结果的 ID
    if items:
        return items[0].get("DC_TARGETID") or items[0].get("MUSICID")
    return None


async def _try_official_dl(song_id: str) -> str | None:
    """尝试酷我官方 convert_url2 接口。"""
    query = (
        "user=0&corp=kuwo&source=kwplayer_ar_5.1.0.0_B_jiakong_vh.apk"
        "&p2p=1&type=convert_url2&sig=0&format=mp3&rid=" + str(song_id)
    )
    encrypted = _encrypt_kuwo_query(query)
    url = f"{_OFFICIAL_DL_URL}?f=kuwo&q={encrypted}"
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, trust_env=False) as c:
            r = await c.get(url, headers={"user-agent": "okhttp/3.10.0"})
            if r.status_code != 200:
                return None
            m = re.search(r"https?://[^\s$\"]+", r.text)
            if m:
                dl_url = m.group(0)
                # 验证链接可达
                r2 = await c.head(dl_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
                if r2.status_code in (200, 206):
                    return dl_url
    except Exception as e:
        logger.debug(f"[kuwo] official dl failed: {e}")
    return None


async def _try_lxmusic_dl(song_id: str) -> str | None:
    """尝试 lxmusic API（第三方）。"""
    url = _LX_MUSIC_API.format(song_id=song_id)
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, trust_env=False) as c:
            r = await c.get(
                url,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "lx-music-request/2.6.0",
                    "X-Request-Key": "share-v3",
                },
            )
            if r.status_code == 200:
                data = r.json()
                dl_url = data.get("url") or ""
                if dl_url and dl_url.startswith("http"):
                    return dl_url
    except Exception as e:
        logger.debug(f"[kuwo] lxmusic failed: {e}")
    return None


async def _try_nxinxz_dl(song_id: str) -> str | None:
    """尝试 nxinxz API（第三方）。"""
    url = _NXINXZ_API.format(song_id=song_id)
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, trust_env=False) as c:
            r = await c.get(url, headers={"User-Agent": "Mozilla/5.0"})
            if r.status_code == 200:
                data = r.json()
                dl_url = (data.get("data") or {}).get("url") or ""
                if dl_url and dl_url.startswith("http"):
                    return dl_url
    except Exception as e:
        logger.debug(f"[kuwo] nxinxz failed: {e}")
    return None


async def search_and_get_url(title: str, artist: str) -> str | None:
    """搜索酷我音乐并返回最佳匹配下载 URL。取不到时返回 None。"""
    keyword = f"{title} {artist}"

    async with httpx.AsyncClient(timeout=12, follow_redirects=True, trust_env=False) as c:
        # Step 1: 搜索
        try:
            r = await c.get(
                _SEARCH_URL,
                params={
                    "pn": "0", "rn": "10", "all": keyword,
                    "client": "kt", "ft": "music", "rformat": "json",
                    "encoding": "utf8",
                },
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            )
            if r.status_code != 200:
                return None
            items = _parse_search_result(r.text)
        except Exception as e:
            logger.info(f"[kuwo] 搜索失败: {e}")
            return None

        song_id = _find_song_id(items, title, artist)
        if not song_id:
            logger.info(f"[kuwo] 未找到匹配歌曲: {keyword}")
            return None

        logger.info(f"[kuwo] 找到歌曲 DC_TARGETID={song_id}")

        # Step 2: 依次尝试各下载源
        for try_fn in [_try_official_dl, _try_lxmusic_dl, _try_nxinxz_dl]:
            url = await try_fn(song_id)
            if url:
                return url

        logger.info(f"[kuwo] 所有下载源均不可用，跳过")
        return None
