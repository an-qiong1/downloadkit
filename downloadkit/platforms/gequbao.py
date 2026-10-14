"""歌曲宝下载源 -- https://www.gequbao.com

2026-10-14 站点改版适配：
  - 搜索页 /s/{keyword} 不再有 ``data-aid``，只剩 ``/music/{aid}`` 链接
  - 音乐页不再内嵌 mp3 直链，改成内联 ``window.appData`` +
    ``POST /member/common-play-url``（id=appData.play_id, purpose=play）换直链
  - 换到的直链落在酷我 CDN（kw-er.kuwo.cn），**带 gequbao 的 Referer 会 403**，
    只给 User-Agent 才 200 —— downloader._stream_download 只对 163 加 Referer，
    正好符合；如果以后统一加 Referer，这里会重新挂掉。
"""

import json
import logging
import re

import httpx

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.gequbao.com/s/{keyword}"
MUSIC_URL = "https://www.gequbao.com/music/{aid}"
PLAY_URL = "https://www.gequbao.com/member/common-play-url"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.gequbao.com/",
}

# 换直链要按 XHR 身份发，否则走不到业务分支
AJAX_HEADERS = {
    **HEADERS,
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
}

_TRIES = 3


async def _get(client: httpx.AsyncClient, url: str, headers=None) -> httpx.Response | None:
    """GET + 有限重试。站点偶发不回包（Server disconnected），单独重开连接再试。"""
    last: Exception | None = None
    for attempt in range(_TRIES):
        try:
            return await client.get(url, headers=headers)
        except Exception as e:  # noqa: BLE001 - 网络层异常全部兜住交给上层
            last = e
            logger.debug(f"[gequbao] GET {url} 第{attempt + 1}次失败: {type(e).__name__}: {e}")
    logger.warning(f"[gequbao] GET {url} 重试{_TRIES}次仍失败: {type(last).__name__}: {last}")
    return None


async def search_and_get_url(title: str, artist: str) -> str | None:
    """在歌曲宝搜索歌曲，返回下载链接。取不到时返回 None（交给下一级源）。"""
    keyword = f"{title} {artist}"

    async with httpx.AsyncClient(timeout=25, follow_redirects=True, trust_env=False) as client:
        # Step 1: 搜索页拿 aid
        resp = await _get(client, SEARCH_URL.format(keyword=keyword))
        if resp is None or resp.status_code != 200:
            return None

        aids = re.findall(r'data-aid="(\d+)"', resp.text)
        aid = _find_aid(resp.text, title, artist) or (aids[0] if aids else None)
        if not aid:
            logger.info(f"[gequbao] 搜索无匹配: {keyword}")
            return None

        # Step 2: 音乐页拿内联 appData
        page = await _get(client, MUSIC_URL.format(aid=aid))
        if page is None or page.status_code != 200:
            return None

        app = _parse_app_data(page.text)
        if not app:
            logger.debug(f"[gequbao] aid={aid} 页面无 appData，回落旧正则")
            return _extract_download_url(page.text)

        # Step 3: play_id 换直链
        url = await _resolve_play_url(client, app)
        if url:
            return url

        # 老结构兜底（万一回滚）
        return _extract_download_url(page.text)


async def _resolve_play_url(client: httpx.AsyncClient, app: dict) -> str | None:
    play_id = app.get("play_id")
    if not play_id:
        return None

    last_msg = ""
    for attempt in range(_TRIES):
        try:
            resp = await client.post(
                PLAY_URL, data={"id": play_id, "purpose": "play"}, headers=AJAX_HEADERS
            )
        except Exception as e:  # noqa: BLE001
            last_msg = f"{type(e).__name__}: {e}"
            logger.debug(f"[gequbao] 换直链第{attempt + 1}次失败: {last_msg}")
            continue

        try:
            data = resp.json()
        except Exception:  # noqa: BLE001
            last_msg = f"非 JSON 响应 status={resp.status_code}"
            continue

        code = data.get("code")
        if code == 1:
            url = (data.get("data") or {}).get("url") or ""
            return url or None
        if code in (2, 3):
            # 人机验证：匿名流程解不了，直接放弃这一级
            logger.info(f"[gequbao] 需人机验证，跳过该源: {data.get('msg', '')}")
            return None
        if code == 4:
            logger.info(f"[gequbao] 今日免费次数用完，跳过该源: {data.get('msg', '')}")
            return None
        if code == 5:
            last_msg = "解析繁忙"
            continue
        last_msg = data.get("msg") or f"code={code}"

    logger.info(f"[gequbao] 取直链失败({last_msg})，跳过该源")
    return None


def _parse_app_data(html: str) -> dict | None:
    """解析音乐页内联的 ``window.appData = JSON.parse('{...}')``。"""
    m = re.search(r"window\.appData\s*=\s*JSON\.parse\('(.*?)'\);", html, re.S)
    if not m:
        return None
    # 外层是 JS 单引号字符串字面量：JSON 里的双引号被写成 \\u0022，
    # 斜杠写成 \\/。这两步还原成合法 JSON 后再交给 json.loads。
    raw = m.group(1).replace("\\u0022", '"').replace("\\/", "/")
    try:
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[gequbao] appData 解析失败: {e}")
        return None


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
        link_text = re.sub(r"<[^>]+>", "", m.group(3)).strip().lower()
        if clean_title in link_text and (not clean_artist or clean_artist in link_text):
            return aid

    # Strategy 2: Fallback - just match title
    for m in song_pattern.finditer(html):
        aid = m.group(2)
        link_text = re.sub(r"<[^>]+>", "", m.group(3)).strip().lower()
        if clean_title in link_text:
            return aid

    # Strategy 3: 2026-10 改版后搜索页只剩裸链接，没有可见文案
    m = re.search(r'href="(/music/(\d+))"', html, re.I)
    return m.group(2) if m else None


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
