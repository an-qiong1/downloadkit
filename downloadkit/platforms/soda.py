"""汽水音乐下载源 -- https://www.douyin.com/qishui/

搜索接口：https://api.qishui.com/luna/search/track
直链获取：通过 track_id 访问分享页解析 audition_url（完整歌曲，非试听）
歌单接口：https://api.qishui.com/luna/pc/playlist/detail
"""

import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://api.qishui.com/luna/search/track"
_TRACK_PAGE_URL = "https://music.douyin.com/qishui/share/track"
_PLAYLIST_URL = "https://api.qishui.com/luna/pc/playlist/detail"

# 模拟 Android 设备的固定参数（无需登录即可搜索）
_SEARCH_DEFAULTS = {
    "device_platform": "android",
    "os": "android",
    "aid": "386088",
    "app_name": "luna",
    "iid": "850377327519292",
    "device_id": "3753066532709850",
}

_SODA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
    "Accept": "application/json, text/plain, */*",
}

# 歌单页 URL 模式
_PLAYLIST_URL_PATTERNS = [
    re.compile(r"https?://qishui\.douyin\.com/s/([^/?]+)"),
    re.compile(r"https?://www\.douyin\.com/qishui/\?.*playlist_id=([^&]+)"),
]


async def _extract_playlist_id(url: str) -> str | None:
    """从汽水歌单 URL 提取 playlist_id。

    注意：qishui.douyin.com/s/xxxx 是短链接，需要跟随重定向拿到真实 ID；
    music.douyin.com/qishui/share/playlist?playlist_id=xxx 则是直链，直接取参。
    """
    import urllib.parse as _urlparse

    # 先尝试从 URL 本身的 query string 提取
    m = re.search(r"playlist_id=([^&]+)", url)
    if m:
        return m.group(1)

    # 短链接模式：qishui.douyin.com/s/xxxx
    for pat in _PLAYLIST_URL_PATTERNS:
        m = pat.search(url)
        if m:
            short_code = m.group(1)
            # 跟随重定向，从最终 URL 取 playlist_id
            try:
                async with httpx.AsyncClient(
                    timeout=10, follow_redirects=True, trust_env=False
                ) as client:
                    r = await client.get(
                        f"https://qishui.douyin.com/s/{short_code}",
                        headers={
                            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X)"
                        },
                    )
                parsed = _urlparse.urlparse(str(r.url))
                qs = _urlparse.parse_qs(parsed.query)
                pid = qs.get("playlist_id", [None])[0]
                if pid:
                    return pid
            except Exception:
                pass
            # 重定向失败则用短码兜底（大概率无效，让上层处理）
            return short_code

    return None


def _find_track_id(items: list[dict], title: str, artist: str) -> str | None:
    """在搜索结果中匹配歌曲，返回 track ID。"""
    clean_title = title.strip().lower()
    clean_artist = artist.split("/")[0].strip().lower()

    for item in items:
        entity = item.get("entity") or {}
        track = entity.get("track") or {}
        name = (track.get("name") or "").strip().lower()
        artists = track.get("artists") or []
        artist_str = "/".join(
            a.get("name", "") for a in artists if isinstance(a, dict)
        ).strip().lower()

        if clean_title in name and (not clean_artist or clean_artist in artist_str):
            return str(track.get("id") or "")
        if clean_title in name:
            return str(track.get("id") or "")

    # 兜底：返回第一个
    if items:
        entity = items[0].get("entity") or {}
        track = entity.get("track") or {}
        return str(track.get("id") or "")
    return None


def _extract_audition_url(html: str, track_id: str) -> str | None:
    """从分享页 HTML 中提取 audition_url。

    解析优先级：标准库 json →（可选）json_repair 兜底。
    为什么先用标准库：json_repair 从来没写进 pyproject 依赖，venv 与打包 exe 里
    都没有它；而 `_ROUTER_DATA = {...};` 实测就是一段合法 JSON（Next.js SSR 注入）。
    以前直接 import json_repair 会抛 ModuleNotFoundError，又被外层
    `except Exception` 静默吞掉，表现成「打包版汽水永远拿不到下载链接」。
    """
    m = re.search(r"_ROUTER_DATA\s*=\s*({.*?});", html, re.S)
    if not m:
        logger.warning("[soda] 分享页没有 _ROUTER_DATA（页面结构可能已变）")
        return None
    try:
        meta = json.loads(m.group(1))
    except Exception:
        try:
            import json_repair  # 可选：仅当 JSON 被截断/损坏时兜底
            meta = json_repair.loads(m.group(1))
        except Exception as e:
            logger.warning(f"[soda] _ROUTER_DATA 解析失败: {type(e).__name__}: {e}")
            return None
    audio_opt = (
        meta.get("loaderData", {})
        .get("track_page", {})
        .get("audioWithLyricsOption") or {}
    )
    url = audio_opt.get("url") or ""
    if url:
        url = url.replace("\\u002F", "/").replace("%7C", "|").replace("%3D", "=")
        if url.startswith("http"):
            return url
    return None


async def _get_audition_url(track_id: str) -> str | None:
    """通过分享页获取单首歌的下载 URL。"""
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, trust_env=False) as c:
            r = await c.get(
                f"{_TRACK_PAGE_URL}?track_id={track_id}",
                headers=_SODA_HEADERS,
            )
            if r.status_code != 200:
                return None
            return _extract_audition_url(r.text, track_id)
    except Exception as e:
        logger.warning(f"[soda] 分享页请求失败: {type(e).__name__}: {e}")
        return None


async def search_and_get_url(title: str, artist: str) -> str | None:
    """搜索汽水音乐并返回最佳匹配下载 URL。取不到时返回 None。"""
    keyword = f"{title} {artist}"

    async with httpx.AsyncClient(timeout=12, follow_redirects=True, trust_env=False) as c:
        # Step 1: 搜索
        try:
            params = {**_SEARCH_DEFAULTS, "q": keyword, "cursor": "0", "count": "10"}
            r = await c.get(_SEARCH_URL, params=params, headers=_SODA_HEADERS)
            if r.status_code != 200:
                return None
            data = r.json()
            result_groups = data.get("result_groups") or []
            if not result_groups:
                return None
            items = result_groups[0].get("data") or []
        except Exception as e:
            logger.info(f"[soda] 搜索失败: {e}")
            return None

        track_id = _find_track_id(items, title, artist)
        if not track_id:
            logger.info(f"[soda] 未找到匹配歌曲: {keyword}")
            return None

        logger.info(f"[soda] 找到歌曲 track_id={track_id}")

        # Step 2: 分享页拿 audition_url
        url = await _get_audition_url(track_id)
        if url:
            return url

        logger.info(f"[soda] 无法获取下载链接，跳过")
        return None


async def search_songs(keyword: str, limit: int = 20) -> list[dict]:
    """搜索汽水音乐，返回歌曲信息列表（用于歌单批量解析）。

    每首歌包含：track_id, name, artist, album, duration_ms
    """
    results = []
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, trust_env=False) as c:
        page, fetched = 0, 0
        while fetched < limit:
            params = {
                **_SEARCH_DEFAULTS,
                "q": keyword,
                "cursor": str(fetched),
                "count": str(min(limit - fetched, 20)),
            }
            try:
                r = await c.get(_SEARCH_URL, params=params, headers=_SODA_HEADERS)
                if r.status_code != 200:
                    break
                data = r.json()
                result_groups = data.get("result_groups") or []
                if not result_groups:
                    break
                items = result_groups[0].get("data") or []
                if not items:
                    break
            except Exception as e:
                logger.debug(f"[soda] search page {page} failed: {e}")
                break

            for item in items:
                entity = item.get("entity") or {}
                track = entity.get("track") or {}
                results.append({
                    "track_id": str(track.get("id") or ""),
                    "name": track.get("name") or "",
                    "artist": "/".join(
                        a.get("name", "")
                        for a in (track.get("artists") or [])
                        if isinstance(a, dict)
                    ),
                    "album": (track.get("album") or {}).get("name", "")
                        if isinstance(track.get("album"), dict) else "",
                    "duration_ms": int(track.get("duration") or 0),
                })
                fetched += 1
                if fetched >= limit:
                    break

            # 判断是否还有下一页
            cursor_val = int(params.get("cursor") or 0)
            if len(items) < 20:
                break
            page += 1

    return results


async def parse_playlist(playlist_url: str) -> dict | None:
    """解析汽水歌单，返回 {name, songs: [{track_id, name, artist, ...}]}。"""
    playlist_id = await _extract_playlist_id(playlist_url)
    if not playlist_id:
        logger.info("[soda] 无法从 URL 提取 playlist_id")
        return None

    tracks = []
    page, total = 0, 0
    playlist_name = f"playlist-{playlist_id}"

    async with httpx.AsyncClient(timeout=20, follow_redirects=True, trust_env=False) as c:
        while True:
            params = {
                "playlist_id": playlist_id,
                "cursor": str(page * 20),
                "cnt": "20",
                "aid": "386088",
                "device_platform": "web",
                "channel": "pc_web",
            }
            try:
                r = await c.get(_PLAYLIST_URL, params=params, headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                })
                if r.status_code != 200:
                    break
                data = r.json()
                # 检查业务错误码
                sc = data.get("status_code")
                if sc in (1000004, 1000005):
                    # 1000004=参数无效（playlist_id 格式不对），1000005=资源不存在
                    si = data.get("status_info") or {}
                    msg = si.get("status_msg") if isinstance(si, dict) else ""
                    logger.info(f"[soda] 歌单接口错误: {sc} ({msg})，歌单可能不存在或需登录")
                    break
                media_resources = data.get("media_resources") or []
                playlist_info = data.get("playlist") or {}
                if page == 0:
                    playlist_name = playlist_info.get("title") or playlist_name
                    total = int(playlist_info.get("count_tracks") or len(media_resources))
                if not media_resources:
                    break
            except Exception as e:
                logger.debug(f"[soda] playlist page {page} failed: {e}")
                break

            for item in media_resources:
                entity = item.get("entity") or {}
                # 歌单 API 结构：entity.track_wrapper.track（不同于搜索接口的 entity.track）
                tw = entity.get("track_wrapper") or {}
                track = tw.get("track") or entity.get("track") or {}
                tracks.append({
                    "track_id": str(track.get("id") or item.get("id") or ""),
                    "name": track.get("name") or "",
                    "artist": "/".join(
                        a.get("name", "")
                        for a in (track.get("artists") or [])
                        if isinstance(a, dict)
                    ),
                    "album": (track.get("album") or {}).get("name", "")
                        if isinstance(track.get("album"), dict) else "",
                    "duration_ms": int(track.get("duration") or 0),
                })

            if len(media_resources) < 20 or len(tracks) >= total:
                break
            page += 1

    if not tracks:
        return None

    return {"name": playlist_name, "song_count": len(tracks), "songs": tracks}
