"""酷狗音乐下载源 -- http://www.kugou.com/

搜索接口：https://songsearch.kugou.com/song_search_v2
直链获取：官方 trackercdn（实测可用）+ 官方 getSongInfo + 第三方兜底

2026-10-17 实测（原实现三个源全是第三方，且全部已失效）：
  - api.baka.plus        → SSL 证书主机名不匹配
  - music.lzmhhh.com     → 500
  - music-api.gdstudio.xyz → 连不上
  而官方源一直是好的，只是从没被接进来：
  - trackercdn.kugou.com/i/v2（key=md5(hash+"kgcloudv2")）→ 返回真 MP3
  - m.kugou.com/app/i/getSongInfo.php（模块里定义了却从未调用）→ 返回真 MP3

**关键前提：必须优先挑免费曲**。酷狗搜索结果里 VIP 曲的
`Privilege=10 / PayType=3`，官方接口对它们返回 `status:2`（无 url）或
`error:"需要付费"`。原实现 `_find_hash` 直接取 `items[0]`，命中的往往正是
VIP 曲，于是"每首歌都拿不到直链"。实测同一关键词里免费曲（Privilege=0）
的直链稳定可用（6/6 全部拿到 ID3 音频）。
"""

import hashlib
import logging

import httpx

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://songsearch.kugou.com/song_search_v2"
_SONG_INFO_URL = "https://m.kugou.com/app/i/getSongInfo.php"
_TRACKER_CDN_URL = "http://trackercdn.kugou.com/i/v2/"
_BAKA_API = "https://api.baka.plus/meting/"
_LZMHHH_API = "https://music.lzmhhh.com/api/music/url"
_GDSTUDIO_API = "https://music-api.gdstudio.xyz/api.php"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _is_free(item: dict) -> bool:
    """判断搜索结果是否免费可下载。

    酷狗用 Privilege/SQPrivilege 表示权限（0=免费，10=付费），
    PayType=3 表示付费曲。字段缺失时不算免费（宁可漏选不可错选）。
    """
    pay = item.get("PayType")
    priv = item.get("Privilege")
    if pay is not None and pay != 0:
        return False
    if priv is not None:
        try:
            return int(priv) == 0
        except (TypeError, ValueError):
            return False
    return pay == 0


def _find_hash(items: list[dict], title: str, artist: str) -> str | None:
    """在搜索结果中匹配歌曲，返回 FileHash。

    匹配分两轮：先只找**免费**曲（否则会挑中 VIP 曲，官方接口必然拿不到
    直链），免费曲里没命中才退回任意匹配并记 warning —— 让"这首要付费"
    在日志里可见，而不是伪装成"源全挂"。
    """
    clean_title = title.strip().lower()
    clean_artist = artist.split("/")[0].strip().lower()

    def _hash_of(item: dict) -> str | None:
        return item.get("FileHash") or item.get("hash")

    def _names(item: dict):
        name = (item.get("FileName") or item.get("SongName") or "").strip().lower()
        singer = (item.get("SingerName") or item.get("singername") or "").strip().lower()
        return name, singer

    free_items = [i for i in items if _is_free(i)]
    paid_items = [i for i in items if not _is_free(i)]

    # 第一轮：免费曲里做精确/宽松标题匹配
    for pool in (free_items, paid_items):
        for item in pool:
            name, singer = _names(item)
            if clean_title in name and (not clean_artist or clean_artist in singer):
                h = _hash_of(item)
                if h:
                    if pool is paid_items:
                        logger.warning(
                            f"[kugou] 只找到付费曲目（可能拿不到直链）: "
                            f"{item.get('FileName')!r}"
                        )
                    return h

    for pool in (free_items, paid_items):
        for item in pool:
            name, _singer = _names(item)
            if clean_title in name:
                h = _hash_of(item)
                if h:
                    if pool is paid_items:
                        logger.warning(
                            f"[kugou] 只找到付费曲目（可能拿不到直链）: "
                            f"{item.get('FileName')!r}"
                        )
                    return h

    # 兜底：优先免费曲的第一条
    for pool in (free_items, paid_items):
        if pool:
            h = _hash_of(pool[0])
            if h:
                if pool is paid_items:
                    logger.warning(
                        f"[kugou] 只找到付费曲目（可能拿不到直链）: "
                        f"{pool[0].get('FileName')!r}"
                    )
                return h
    return None


async def _try_trackercdn_dl(file_hash: str) -> str | None:
    """官方 trackercdn v2 接口（2026-10-17 实测免费曲可用）。

    VIP 曲会返回 ``{"status": 2, ...}``（没有 url 字段），此时不算成功。
    """
    key = hashlib.md5((file_hash + "kgcloudv2").encode()).hexdigest()
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, trust_env=False) as c:
            for br in ("hq", "320", "128"):
                r = await c.get(
                    _TRACKER_CDN_URL,
                    params={"key": key, "hash": file_hash, "br": br,
                            "appid": "1005", "pid": "2", "cmd": "25",
                            "behavior": "play"},
                    headers={"User-Agent": _UA},
                )
                if r.status_code != 200:
                    logger.warning(f"[kugou] trackercdn ({br}) 返回 {r.status_code}")
                    continue
                try:
                    data = r.json()
                except Exception:
                    continue
                urls = data.get("url") or []
                if isinstance(urls, str):
                    urls = [urls]
                if urls:
                    logger.info(f"[kugou] trackercdn ({br}) 命中")
                    return urls[0]
                # status=2 通常是需要付费
                if data.get("status") == 2:
                    logger.warning(
                        f"[kugou] trackercdn ({br}) 无 url（该曲可能需要付费）"
                    )
    except Exception as e:
        logger.warning(f"[kugou] trackercdn 失败: {type(e).__name__}: {e}")
    return None


async def _try_official_song_info(file_hash: str) -> str | None:
    """官方 getSongInfo 接口（模块里原先定义了这个常量却没接进兜底链）。"""
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, trust_env=False) as c:
            r = await c.get(
                _SONG_INFO_URL,
                params={"cmd": "playInfo", "hash": file_hash},
                headers={"User-Agent": _UA},
            )
            if r.status_code != 200:
                logger.warning(f"[kugou] getSongInfo 返回 {r.status_code}")
                return None
            data = r.json()
            url = data.get("url") or ""
            if url.startswith("http"):
                logger.info("[kugou] getSongInfo 命中")
                return url
            err = data.get("error") or ""
            logger.warning(f"[kugou] getSongInfo 无 url: error={err!r}")
    except Exception as e:
        logger.warning(f"[kugou] getSongInfo 失败: {type(e).__name__}: {e}")
    return None


async def _try_baka_api(file_hash: str) -> str | None:
    """尝试 baka.plus 第三方 API（2026-10-17 实测 SSL 证书不匹配，已失效）。"""
    url = (
        f"{_BAKA_API}meting/?server=kugou&type=url&id={file_hash}&br=2000"
    )
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, trust_env=False) as c:
            r = await c.get(url, headers={"User-Agent": _UA})
            # baka 返回重定向，最终 URL 即为直链
            final_url = str(r.url)
            if final_url.startswith("http") and "error" not in final_url.lower():
                # 验证链接可达
                r2 = await c.head(final_url, headers={"User-Agent": _UA}, timeout=8)
                if r2.status_code in (200, 206):
                    return final_url
    except Exception as e:
        logger.warning(f"[kugou] baka 失败: {type(e).__name__}: {e}")
    return None


async def _try_lzmhhh_api(file_hash: str) -> str | None:
    """尝试 lzmhhh.com 第三方 API（2026-10-17 实测 500，已失效）。"""
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, trust_env=False) as c:
            r = await c.post(
                _LZMHHH_API,
                json={"id": file_hash, "type": "kg"},
                headers={
                    "User-Agent": _UA,
                    "Referer": "https://music.lzmhhh.com/",
                    "Origin": "https://music.lzmhhh.com",
                },
            )
            if r.status_code == 200:
                data = r.json()
                dl_url = data.get("data") or ""
                if dl_url and dl_url.startswith("http"):
                    return dl_url
            else:
                logger.warning(f"[kugou] lzmhhh 返回 {r.status_code}")
    except Exception as e:
        logger.warning(f"[kugou] lzmhhh 失败: {type(e).__name__}: {e}")
    return None


async def _try_gdstudio_api(file_hash: str) -> str | None:
    """尝试 gdstudio.xyz 第三方 API（2026-10-17 实测连不上）。"""
    url = f"{_GDSTUDIO_API}?types=url&id={file_hash}&source=kugou&br=999"
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, trust_env=False) as c:
            r = await c.get(url, headers={"User-Agent": _UA})
            if r.status_code == 200:
                data = r.json()
                dl_url = data.get("url") or ""
                if dl_url and dl_url.startswith("http"):
                    return dl_url
    except Exception as e:
        logger.warning(f"[kugou] gdstudio 失败: {type(e).__name__}: {e}")
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
                headers={"User-Agent": _UA},
            )
            if r.status_code != 200:
                logger.warning(f"[kugou] 搜索返回 {r.status_code}")
                return None
            data = r.json()
            items = data.get("data", {}).get("lists") or []
        except Exception as e:
            logger.warning(f"[kugou] 搜索失败: {type(e).__name__}: {e}")
            return None

        file_hash = _find_hash(items, title, artist)
        if not file_hash:
            logger.warning(f"[kugou] 未找到匹配歌曲: {keyword}")
            return None

        logger.info(f"[kugou] 找到歌曲 FileHash={file_hash}")

        # Step 2: 依次尝试各下载源（官方源在前，实测可用）
        for try_fn in [_try_trackercdn_dl, _try_official_song_info,
                       _try_baka_api, _try_lzmhhh_api, _try_gdstudio_api]:
            url = await try_fn(file_hash)
            if url:
                return url

        logger.warning(f"[kugou] 所有下载源均不可用，跳过: {keyword}")
        return None
