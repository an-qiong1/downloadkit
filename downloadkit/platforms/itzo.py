"""itzo.cn download source -- https://music.itzo.cn (JSON API)

2026-10-17 实测：``music.itzo.cn`` **DNS 已不解析**（直连 getaddrinfo failed、
走本地代理也连不上，368 首歌单里 368 次全挂）。域名死了但代码保留，
加「源失效短路」：连接级失败（DNS/网络）记时间戳，冷却窗口内直接跳过，
不再让每首歌白等 20s 超时；窗口过去后自动重试一次，域名恢复即自愈。
"""

import logging
import time

import httpx

logger = logging.getLogger(__name__)

SEARCH_URL = "https://music.itzo.cn/a.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded",
    "Origin": "https://music.itzo.cn",
    "Referer": "https://music.itzo.cn/",
}

# 源失效短路：连接级失败（多半是 DNS）后冷却多久再探一次。
# 368 首实测每首在这里烧 20s 超时，整批白等 2 小时。
_DEAD_COOLDOWN = 600.0
_last_conn_fail: float = 0.0


def _source_cooling(now: float | None = None) -> bool:
    """连接级失败的冷却窗口内 = True（跳过本级的探活）。"""
    t = time.time() if now is None else now
    return (_last_conn_fail > 0) and (t - _last_conn_fail < _DEAD_COOLDOWN)


def _mark_conn_fail(now: float | None = None) -> None:
    global _last_conn_fail
    _last_conn_fail = time.time() if now is None else now


async def search_and_get_url(title: str, artist: str,
                             types: tuple[str, ...] = ("qq", "netease")) -> str | None:
    """Search itzo.cn and return best-match download URL.

    ``types`` 按优先级依次尝试。默认先 qq：``type=netease`` 返回的就是
    ``music.163.com/song/media/outer/url``，与下载引擎 Step 1 完全同源，
    VIP 歌曲必然和 Step 1 一起吃 HTML，等于白跑一级；而 ``type=qq`` 返回
    带 vkey 的真实 QQ 直链（m4a），是真正独立的兜底。netease 留作第二顺位，
    万一 Step 1 只是偶发网络失败还能再试一次。
    """
    if _source_cooling():
        logger.debug("[itzo] 源失效冷却中，跳过")
        return None

    keyword = f"{title} {artist}"

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
        for src_type in types:
            data = {"input": keyword, "filter": "name", "type": src_type, "page": "1"}
            try:
                resp = await client.post(SEARCH_URL, data=data, headers=HEADERS)
            except httpx.TransportError as e:
                # DNS/连接级失败：整站不通，再试另一种 type 也是白试，
                # 直接记时间戳进冷却，别再烧 368 遍 20s 超时。
                _mark_conn_fail()
                logger.warning(
                    f"[itzo] 连接失败（该源可能已失效），进入 "
                    f"{int(_DEAD_COOLDOWN)}s 冷却: {type(e).__name__}: {str(e)[:80]}"
                )
                return None
            url = await _parse_and_match(resp, title, artist)
            if url:
                return url
    return None


async def _parse_and_match(resp: httpx.Response, title: str, artist: str) -> str | None:
    """解析一次搜索响应并挑最匹配的 URL。"""
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
