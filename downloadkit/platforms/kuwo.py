"""酷我音乐下载源 -- http://www.kuwo.cn/

搜索接口：http://search.kuwo.cn/r.s
  注意：该接口返回的是**单引号伪 JSON**（`{'abslist':[{'SONGNAME':'...'}]}`），
  不是合法 JSON —— `json.loads` 必然失败。2026-10-17 实测：4110 个单引号、
  0 个双引号。此前只走 json + 逐行 `key=value` 兜底，而响应里根本没有 `=`，
  于是解析恒返回 0 条 → 搜索级永远 miss（交接文档记的"搜索可用"不成立）。
  现在用 ast.literal_eval 解析 Python 字面量，json 与逐行解析仍保留兜底。

直链获取（2026-10-17 实测排序）：
  1. antiserver anti.s —— 实测可用，返回纯文本直链，落盘为真 MP3（魔数 49443304）
  2. 官方 mobi.s       —— 实测 404，已失效，保留仅作探测
  3. lxmusic(onrender) —— 实测 503 Service Suspended，已停服
  4. nxinxz            —— 实测返回可下载音频（但拿到的是 AAC，非其声称的 lossless）
"""

import ast
import logging
import re
import urllib.parse

import httpx

logger = logging.getLogger(__name__)

_SEARCH_URL = "http://search.kuwo.cn/r.s"
_OFFICIAL_DL_URL = "http://mobi.kuwo.cn/mobi.s"
# 实测可用的官方直链接口（无需鉴权）
_ANTISERVER_URL = "http://antiserver.kuwo.cn/anti.s"
_LX_MUSIC_API = "https://lxmusicapi.onrender.com/url/kw/{song_id}/flac"
_NXINXZ_API = "http://music.nxinxz.com/kw.php?id={song_id}&level=lossless&type=json"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def _encrypt_kuwo_query(query: str) -> str:
    """酷我官方接口的简单旋转加密。"""
    raw = query.encode()
    enc = []
    for i, b in enumerate(raw):
        enc.append(chr((b + i) % 128))
    return urllib.parse.quote("".join(enc))


def _parse_search_result(resp_text: str) -> list[dict] | None:
    """解析酷我搜索响应。

    真实响应是单引号伪 JSON（Python 字典字面量），所以优先 ast.literal_eval；
    合法 JSON 与逐行 `key=value` 作为兜底。
    """
    if not resp_text or not resp_text.strip():
        return []

    # 1) 合法 JSON（未来接口若修正格式）
    try:
        import json
        d = json.loads(resp_text)
        if isinstance(d, dict) and "abslist" in d:
            return d.get("abslist") or []
    except Exception:
        pass

    # 2) 单引号伪 JSON —— 实测的真实格式
    #    用 ast.literal_eval 而不是 replace("'", '"')：后者会把内容里的
    #    撇号（如 "Don't"）也换成双引号，直接破坏 JSON。
    try:
        d = ast.literal_eval(resp_text)
        if isinstance(d, dict):
            items = d.get("abslist") or []
            if items:
                return items
    except Exception as e:
        logger.debug(f"[kuwo] literal_eval 失败，退回逐行解析: {type(e).__name__}: {e}")

    # 3) 逐行 key=value 兜底（老式 text/plain 响应）
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


async def _try_antiserver_dl(song_id: str) -> str | None:
    """官方 antiserver anti.s 接口：返回纯文本直链，实测可用。"""
    url = (
        f"{_ANTISERVER_URL}?type=convert_url&format=mp3"
        f"&response=url&rid=MUSIC_{song_id}"
    )
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, trust_env=False) as c:
            r = await c.get(url, headers={"User-Agent": _UA})
            if r.status_code != 200:
                logger.warning(f"[kuwo] antiserver 返回 {r.status_code}")
                return None
            text = r.text.strip()
            if text.startswith("http"):
                return text.split()[0]
            logger.warning(f"[kuwo] antiserver 响应不是直链: {text[:80]!r}")
    except Exception as e:
        logger.warning(f"[kuwo] antiserver 失败: {type(e).__name__}: {e}")
    return None


async def _try_official_dl(song_id: str) -> str | None:
    """尝试酷我官方 convert_url2 接口（mobi.s）。

    2026-10-17 实测该接口恒 404，已失效；保留探测以免将来恢复。
    """
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
                r2 = await c.head(dl_url, headers={"User-Agent": _UA}, timeout=8)
                if r2.status_code in (200, 206):
                    return dl_url
    except Exception as e:
        logger.warning(f"[kuwo] 官方 mobi.s 失败: {type(e).__name__}: {e}")
    return None


async def _try_lxmusic_dl(song_id: str) -> str | None:
    """尝试 lxmusic API（第三方）。2026-10-17 实测 503 已停服。"""
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
            else:
                logger.warning(f"[kuwo] lxmusic 返回 {r.status_code}（该源可能已停服）")
    except Exception as e:
        logger.warning(f"[kuwo] lxmusic 失败: {type(e).__name__}: {e}")
    return None


async def _try_nxinxz_dl(song_id: str) -> str | None:
    """尝试 nxinxz API（第三方）。

    实测能下到音频，但即使传 level=lossless 拿到的也是 AAC（魔数 fff1），
    质量与宣称不符，故排在最后。
    """
    url = _NXINXZ_API.format(song_id=song_id)
    try:
        async with httpx.AsyncClient(timeout=8, follow_redirects=True, trust_env=False) as c:
            r = await c.get(url, headers={"User-Agent": _UA})
            if r.status_code == 200:
                data = r.json()
                dl_url = (data.get("data") or {}).get("url") or ""
                if dl_url and dl_url.startswith("http"):
                    return dl_url
    except Exception as e:
        logger.warning(f"[kuwo] nxinxz 失败: {type(e).__name__}: {e}")
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
                headers={"User-Agent": _UA},
            )
            if r.status_code != 200:
                logger.warning(f"[kuwo] 搜索返回 {r.status_code}")
                return None
            items = _parse_search_result(r.text)
        except Exception as e:
            logger.warning(f"[kuwo] 搜索失败: {type(e).__name__}: {e}")
            return None

        song_id = _find_song_id(items, title, artist)
        if not song_id:
            logger.warning(f"[kuwo] 未找到匹配歌曲: {keyword}（解析出 {len(items or [])} 条）")
            return None

        logger.info(f"[kuwo] 找到歌曲 DC_TARGETID={song_id}")

        # Step 2: 依次尝试各下载源（antiserver 实测可用，放第一位）
        for try_fn in [_try_antiserver_dl, _try_official_dl,
                       _try_lxmusic_dl, _try_nxinxz_dl]:
            url = await try_fn(song_id)
            if url:
                return url

        logger.warning(f"[kuwo] 所有下载源均不可用，跳过: {keyword}")
        return None
