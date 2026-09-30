# -*- coding: utf-8 -*-
"""通用网页视频解析下载模块（generic extractor）

覆盖 P0 范围：
  L0  m3u8 / mp4 / mpd 直链
  L1  普通网页 URL → yt-dlp generic extractor 提取流地址

下载走 yt-dlp Python API（复用 downloadkit/youtube.py 的骨架：
progress_hook → download_queue.update_progress，暂停/取消钩子），
产物统一 remux 为 mp4。

L2 浏览器嗅探见 downloadkit/sniffer.py（P2 交付）。
"""

import asyncio
import gc
import html as html_module
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---- L0 直链判定 ----
DIRECT_MEDIA_RE = re.compile(r"\.(m3u8|mp4|mpd|flv|mkv|webm|ts|mov|m4v)(?:[?#]|$)", re.I)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

# 解析用子进程超时（部分站有 WAF 挑战，给足余量）
PARSE_TIMEOUT = 45


class AbortDownload(Exception):
    """用户暂停/取消导致的下载中止。

    刻意**不**继承 yt_dlp.utils.DownloadError：
    yt-dlp 的分片下载循环（downloader/fragment.py）是

        for retry in RetryManager(self.params.get('fragment_retries'), ...):
            try:
                self._download_fragment(...)
            except (HTTPError, IncompleteRead) as err:
                retry.error = err; continue
            except DownloadError:      # 有自己的一套重试
                if fatal:
                    raise              # <-- fatal 为 False 时被吞掉！

    其中 fatal = is_fatal(fragment index)，而 is_fatal 默认只对第 0 个
    分片返回 True。实测：对 HLS 流取消时 raise DownloadError 会被吞掉，
    下载继续推进到整支视频结束（取消后仍继续传输约 3.75 分钟）。
    改用非 DownloadError 的异常可直接穿透该循环，实现立即中止。
    """
    pass


@dataclass
class GenericVideo:
    """通用视频信息（结构对齐 YouTubeVideo，便于前端复用同一套渲染）"""
    url: str                       # 用户输入的原始 URL
    title: str = ""
    author: str = ""
    cover: str = ""
    duration: int = 0
    ext: str = "mp4"
    webpage_url: str = ""          # 跟随重定向后的实际页面 URL
    referer: str = ""              # 防盗链 Referer（下载时必须带上）
    is_playlist: bool = False      # 识别为播放列表/选集（P4 消费）
    entry_count: int = 0
    formats: list = field(default_factory=list)   # [{format_id, quality, ext, height}]
    uploader: str = ""
    page_title: str = ""           # 网页 <title>（yt-dlp 标题为弱名时抓取，供命名）


def is_http_url(url: Any) -> bool:
    """是否为 http/https 绝对地址"""
    if not isinstance(url, str):
        return False
    return bool(re.match(r"^https?://", url.strip(), re.I))


def is_direct_media_url(url: str) -> bool:
    """L0：URL 本身即媒体直链"""
    return bool(DIRECT_MEDIA_RE.search(urlparse(url.strip()).path))


def origin_of(url: str) -> str:
    """取 scheme://host 作保守 Referer（无页面地址时的兜底）"""
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}" if p.netloc else ""


def _yt_dlp_cmd() -> list[str]:
    """yt-dlp 调用方式：打包环境用同目录 exe，开发环境用 python -m。

    Windows 上 yt-dlp 常不在 PATH，`python -m yt_dlp` 是最稳的兜底
    （同 backend/app/utils/ytdlp.py 的做法）。
    """
    ytdlp = Path(sys.executable).parent / "yt-dlp.exe"
    if ytdlp.exists():
        return [str(ytdlp)]
    return [sys.executable, "-m", "yt_dlp"]


async def _ytdlp_dump_json(
    url: str, *, flat: bool = False, timeout: int = PARSE_TIMEOUT
) -> list[dict[str, Any]]:
    """子进程方式取 yt-dlp 元数据（--dump-json --no-download）。

    用子进程而非 Python API 的原因：批量场景必须能硬超时 kill，
    阻塞的 extract_info 无法中断。
    """
    cmd = _yt_dlp_cmd() + [
        "--dump-json", "--no-download", "--no-warnings", "--quiet",
        # 实测部分 CDN 首连 20s 不够（偶发 connect timeout），放宽到 30s
        "--socket-timeout", "30",
        "--retries", "3",
    ]
    if flat:
        cmd += ["--flat-playlist"]
    # 直链场景跳过 playlist 判定，省一次网络往返
    else:
        cmd += ["--no-playlist"]
    cmd.append(url)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        raise TimeoutError(f"解析超时（>{timeout}s）: {url[:80]}")

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="ignore").strip()
        # yt-dlp 的错误信息常带大量日志，只留最后几行有用信息
        last = [l for l in err.splitlines() if l.strip()][-3:]
        raise RuntimeError("; ".join(last) or f"yt-dlp 退出码 {proc.returncode}")

    lines = [l for l in stdout.decode("utf-8", errors="ignore").splitlines() if l.strip()]
    if not lines:
        raise RuntimeError("yt-dlp 未返回任何结果")
    return [json.loads(l) for l in lines]


def _format_quality_list(raw: Any) -> list[dict]:
    """把 yt-dlp formats 转成前端 FormatInfo 形态（只留视频相关）"""
    out: list[dict] = []
    for f in raw or []:
        if not isinstance(f, dict):
            continue
        if f.get("vcodec") in (None, "none") and f.get("acodec") not in (None, "none"):
            continue  # 纯音频先不列
        out.append({
            "format_id": str(f.get("format_id") or ""),
            "quality": f.get("format_note") or (
                f"{f['height']}p" if f.get("height") else str(f.get("resolution") or "")
            ),
            "ext": str(f.get("ext") or "mp4"),
            "height": f.get("height") or 0,
            "filesize": f.get("filesize") or f.get("filesize_approx") or None,
        })
    return out


def _classify_entries(entries: list[dict[str, Any]]) -> tuple[bool, bool]:
    """区分「真播放列表/选集」与「同一视频的多个 source」。

    yt-dlp 的 generic extractor 会把一个页面里的多个 <source> 也包成
    带 playlist_index/n_entries 的伪列表，但那些条目的 url 完全相同。
    判定规则：
      · _type == 'playlist'              → 真播放列表
      · 多条且 webpage_url 互不相同      → 真选集（不同页面）
      · 多条但 url/webpage_url 相同      → 伪列表（多 source），取第一条即可
    """
    if not entries:
        return False, False
    if entries[0].get("_type") == "playlist":
        return True, False
    if len(entries) == 1:
        return False, False

    keys = {str(e.get("webpage_url") or e.get("url") or "").rstrip("/") for e in entries}
    keys.discard("")
    if len(keys) > 1:
        return True, False      # 不同页面 → 真选集
    return False, True          # 同一地址 → 多 source，应去重


async def parse_generic(
    url: str, *, flat: bool = False, referer: str | None = None, retries: int = 2
) -> GenericVideo:
    """解析通用 URL（L0 直链 + L1 网页）。

    Args:
        url: 待解析地址
        flat: 播放列表按浅层解析（P4 选集用）
        referer: 已知的来源页 Referer。嗅探阶段(L2)会拿到真实播放页地址，
            直链场景不传则退化为同域 origin
        retries: 网络抖动重试次数（实测 CDN 首连偶发超时，同 URL 重试即通）

    Raises:
        TimeoutError / RuntimeError: 解析失败，message 可直接展示给用户
    """
    if not is_http_url(url):
        raise RuntimeError("不是有效的 http(s) 链接")

    entries: list[dict[str, Any]] = []
    last_err: Exception | None = None
    for attempt in range(retries + 1):
        try:
            entries = await _ytdlp_dump_json(url, flat=flat)
            last_err = None
            break
        except (TimeoutError, RuntimeError, OSError) as e:
            last_err = e
            if attempt < retries:
                logger.warning(f"[Generic] 解析第 {attempt + 1} 次失败，重试: {str(e)[:120]}")
                # 指数退避：CDN 抖动时立刻重连大概率还是失败
                await asyncio.sleep(1.5 * (attempt + 1))
    if last_err is not None:
        raise last_err

    is_playlist, is_multi_source = _classify_entries(entries)
    # flat 模式是调用方明确要求解析选集（P4），强制按播放列表处理
    if flat:
        is_playlist = True
    if is_multi_source:
        logger.info(f"[Generic] 同址多 source，去重取首条 ({len(entries)} 条): {url[:80]}")

    # 非播放列表时，首条即完整信息（多 source 条目内容等价）
    info = entries[0] if entries else {}

    webpage_url = str(info.get("webpage_url") or url)
    # Referer 优先级：调用方给的真实页面 > yt-dlp 解析出的页面 > 同域 origin
    if referer:
        resolved_referer = referer
    elif webpage_url and not is_direct_media_url(webpage_url):
        resolved_referer = webpage_url
    else:
        resolved_referer = origin_of(url)

    video = GenericVideo(
        url=url,
        title=str(info.get("title") or "").strip() or _fallback_title(url),
        author=str(info.get("uploader") or info.get("channel") or info.get("creator") or "").strip()
               or _host_of(url),
        cover=str(info.get("thumbnail") or ""),
        duration=int(info.get("duration") or 0),
        ext=str(info.get("ext") or "mp4"),
        webpage_url=webpage_url,
        referer=resolved_referer,
        is_playlist=is_playlist,
        entry_count=(len(entries) if is_playlist else 0),
        formats=_format_quality_list(info.get("formats")),
        uploader=str(info.get("uploader") or ""),
    )

    if not video.formats:
        # 直链场景 yt-dlp 可能不列 formats，补一条占位
        video.formats = [{
            "format_id": "best",
            "quality": "默认",
            "ext": video.ext,
            "height": 0,
            "filesize": None,
        }]

    # 弱标题（m3u8 直链常见 "playlist"）→ 抓原页面 <title> 作命名兜底
    if is_weak_title(video.title):
        tried: set[str] = set()
        for cand in (video.referer, webpage_url):
            if not cand or cand in tried or is_direct_media_url(cand):
                continue
            tried.add(cand)
            p = urlparse(cand)
            if not p.path or p.path == "/":
                # 只有 origin 根路径（无具体页面）→ 抓首页意义有限，跳过省一次请求
                continue
            pt = await _fetch_page_title(cand, referer=video.referer)
            if pt and not is_weak_title(pt):
                video.page_title = pt
                logger.info(f"[Generic] 弱标题兜底: 页面标题 = {pt[:60]}")
                break
    return video


def _host_of(url: str) -> str:
    return urlparse(url).netloc or "未知站点"


def _fallback_title(url: str) -> str:
    """yt-dlp 拿不到标题时，用 URL 末段兜底，避免前端显示"无标题" """
    path = urlparse(url).path.rstrip("/")
    seg = path.rsplit("/", 1)[-1] if path else ""
    seg = re.sub(r"\.(m3u8|mp4|mpd|ts|flv|webm|mkv)$", "", seg, flags=re.I)
    return seg or _host_of(url)


# ================= 命名体系（网页名 / 剧名 / 集数） =================

# "弱标题"：yt-dlp 对 m3u8 直链常返回 playlist/index/纯数字/uuid 之类，
# 这类名字对用户没有意义，不能直接当文件名
_WEAK_TITLE_RE = re.compile(
    r"^(?:playlist|index|master|multiple|video|stream|untitled|default|media|anonymous"
    r"|\d+"
    r"|[0-9a-f]{8}(?:-[0-9a-f]{4,}){1,4}"      # uuid（8-4-4-4-12）
    r")$",
    re.I,
)


def is_weak_title(title: str) -> bool:
    """标题是否无信息量（空 / playlist / 纯数字 / uuid / 裸 URL）"""
    t = (title or "").strip()
    if not t:
        return True
    if t.lower().startswith(("http://", "https://")):
        return True
    return bool(_WEAK_TITLE_RE.match(t))


# 集数识别：第12集 / 第十二话 / EP12 / E01 / 12集 …
_EPISODE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"第\s*(\d{1,4}|[一二三四五六七八九十百千]+)\s*([集话話期回])"),
    re.compile(r"\bEP?\s*[.\-_ ]?\s*(\d{1,4})\b", re.I),
    re.compile(r"(?<!\d)(\d{1,4})\s*([集话話期回])"),
)
_SERIES_EDGE_RE = re.compile(r"^[\s\-—–_－｜|:：·・.、,，\[(（【]+")


def parse_series_episode(text: str) -> tuple[str, str]:
    """从标题拆出 (剧名, 集数标签)；识别不到集数返回 ("", "")。

    >>> parse_series_episode("师兄啊师兄 第01集-某站")
    ('师兄啊师兄', '第01集')
    >>> parse_series_episode("凡人修仙传 EP12")
    ('凡人修仙传', '第12集')
    >>> parse_series_episode("无集数的普通标题")
    ('', '')
    """
    t = (text or "").strip()
    if not t:
        return "", ""
    for pat in _EPISODE_PATTERNS:
        m = pat.search(t)
        if not m:
            continue
        num_raw = m.group(1)
        unit = m.group(2) if (m.lastindex or 0) >= 2 else "集"
        episode = f"第{int(num_raw):02d}{unit}" if num_raw.isdigit() else f"第{num_raw}{unit}"
        # 剧名取集数标记之前的部分；其后多是站点后缀（-XX影视），丢弃
        series = t[: m.start()].strip(" \t-—–_－｜|:：·・.、,，")
        series = _SERIES_EDGE_RE.sub("", series)
        return series, episode
    return "", ""


def build_file_stem(
    *,
    hint: str = "",
    title: str = "",
    page_title: str = "",
    url: str = "",
    prefix_weak: bool = True,
) -> str:
    """决定下载产物文件名（不含扩展名；未过 sanitize_filename）。

    优先级：
      1. 能解析出集数的候选（顺序 hint > title > page_title）→ "剧名-第01集"
         （书签标题/网页标题带集数信息时优先，剧名集数是最有价值的命名）
      2. hint —— 书签标题/调用方指定，代表用户意图
      3. title —— yt-dlp 解析标题
      4. page_title —— 网页 <title> 抓取
      5. URL 末段兜底（加 web_ 前缀，便于识别弱名来源）

    弱标题（playlist/uuid/裸URL…）不参与 2~4。
    """
    candidates: list[str] = []
    for val in (hint, title, page_title):
        v = (val or "").strip()
        if v and not is_weak_title(v) and v not in candidates:
            candidates.append(v)

    def _trim(s: str) -> str:
        return s.strip()[:120].strip(" .\t")

    # 1) 含集数信息的候选优先 → 剧名-第NN集
    for v in candidates:
        series, episode = parse_series_episode(v)
        if episode:
            base = _trim(series or v)
            return f"{base}-{episode}" if base else episode

    # 2~4) 依次取有意义的原始标题
    for v in candidates:
        name = _trim(v)
        if name:
            return name

    # 5) URL 兜底
    fb = _trim(_fallback_title(url)) if url else ""
    if not fb:
        return "unknown"
    return f"web_{fb}" if prefix_weak else fb


def _extract_page_title(html_text: str) -> str:
    """从 HTML 文本提取 og:title / <title>（抓取与提取分离，供 L1 探测复用）。"""
    m = re.search(
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        html_text, re.I,
    ) or re.search(
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']',
        html_text, re.I,
    )
    if m:
        return html_module.unescape(m.group(1)).strip()
    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.I | re.S)
    if m:
        return re.sub(r"\s+", " ", html_module.unescape(m.group(1))).strip()
    return ""


async def _fetch_page_title(page_url: str, *, referer: str = "") -> str:
    """抓网页 og:title / <title>（弱标题时的命名兜底）。失败返回 ""。"""
    if not is_http_url(page_url) or is_direct_media_url(page_url):
        return ""
    headers = {"User-Agent": DEFAULT_UA, "Accept": "text/html,application/xhtml+xml,*/*"}
    if referer and not is_direct_media_url(referer):
        headers["Referer"] = referer
    try:
        import httpx
        async with httpx.AsyncClient(
            timeout=8, follow_redirects=True, headers=headers
        ) as c:
            r = await c.get(page_url)
            if r.status_code >= 400:
                return ""
            html_text = r.text[:300_000]
    except Exception as e:  # noqa: BLE001 — 取标题失败不能影响解析主流程
        logger.debug(f"[Generic] 抓页面标题失败 {page_url[:80]}: {e}")
        return ""

    return _extract_page_title(html_text)


# ---------------- L1 静态深挖（P3 批量探测的快速通道） ----------------

_JS_SRC_RE = re.compile(r'<script[^>]+src=["\']([^"\']+)["\']', re.I)
# 第三方库 JS 永远不含本站视频流，抓了纯浪费 3s 预算
_THIRD_PARTY_JS_RE = re.compile(
    r"jquery|googleapis|gstatic|googletag|analytics|cloudflare|unpkg|jsdelivr"
    r"|bootcss|polyfill|schema\.org", re.I,
)


def page_js_urls(html_text: str, base_url: str) -> list[str]:
    """提取页面引用的 script src（urljoin 转绝对地址，保序去重）。"""
    from urllib.parse import urljoin
    out: list[str] = []
    for m in _JS_SRC_RE.finditer(html_text or ""):
        u = urljoin(base_url, m.group(1))
        if u.startswith(("http://", "https://")) and u not in out:
            out.append(u)
    return out


async def probe_static(url: str, timeout: float = 3.0) -> dict[str, Any]:
    """L1 静态深挖（计划书 §4.1）：抓 HTML 正则挖流地址；未命中则抓页面
    引用的 JS 文件再挖（最多 2 个，跳过第三方库）。

    探测语义：任何网络/解析失败都返回 streams=[]（= 未命中），不抛异常，
    由调用方决定是否降级到 L2 浏览器嗅探。

    Returns:
        {"streams": [...提流+去重+主子区分后最多 8 条...], "title": 页面标题}
    """
    from downloadkit.sniffer import dedupe_streams, extract_stream_urls, prefer_main_streams

    empty: dict[str, Any] = {"streams": [], "title": ""}
    if not is_http_url(url):
        return empty
    headers = {
        "User-Agent": DEFAULT_UA,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }
    html_text = ""
    try:
        import httpx
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers=headers
        ) as c:
            r = await c.get(url)
            if r.status_code < 400 and "mpegurl" not in r.headers.get("content-type", "").lower() \
                    and not r.text.lstrip().startswith("#EXTM3U"):
                html_text = r.text[:300_000]
            elif r.text.lstrip().startswith("#EXTM3U"):
                # 服务端把 m3u8 当文本返回：URL 本身即流
                return {"streams": [url], "title": ""}
    except Exception as e:  # noqa: BLE001 — 探测失败 = 未命中，不打断批次
        logger.debug(f"[Probe] L1 抓取失败 {url[:80]}: {e}")
        return empty
    if not html_text:
        return empty

    title = _extract_page_title(html_text)
    streams: list[str] = extract_stream_urls(html_text)

    # 未命中 → 抓页面引用的 JS 再挖（最多 2 个）
    if not streams:
        js_urls = [j for j in page_js_urls(html_text, url)
                   if not _THIRD_PARTY_JS_RE.search(j)][:2]
        for ju in js_urls:
            try:
                import httpx
                async with httpx.AsyncClient(
                    timeout=timeout, follow_redirects=True, headers=headers
                ) as c:
                    r = await c.get(ju)
                    if r.status_code < 400:
                        streams.extend(extract_stream_urls(r.text[:200_000]))
            except Exception:  # noqa: BLE001
                continue
            if streams:
                break

    return {
        "streams": prefer_main_streams(dedupe_streams(streams))[:8],
        "title": title,
    }


def _format_selector(quality: str) -> str:
    """清晰度 → yt-dlp -f 表达式。

    generic 场景多为 HLS 单流（无独立音轨），故用 bv*/b 兜底链，
    避免 height 元数据缺失导致选不到流。
    """
    if not quality or quality == "best":
        return "bv*+ba/b"
    if str(quality).isdigit():
        h = int(quality)
        return (
            f"bv*[height<={h}]+ba/b[height<={h}]/"
            f"bv*[height<={h}]/b[height<={h}]/bv*+ba/b"
        )
    return "bv*+ba/b"


def build_ydl_opts(
    *,
    output_path: str,
    quality: str = "best",
    referer: str = "",
    ua: str = DEFAULT_UA,
    rename_strategy: str | None = None,
    progress_hook=None,
    proxy: str | None = None,
) -> dict:
    """构建 yt_dlp.YoutubeDL 参数（供本模块与后续嗅探模块共用）。

    remux_video + merge_output_format 双保险：
      · 单流 HLS(TS) → remux 成 mp4（-c copy，不重编码，秒级）
      · 双流(DASH)   → merge 直接进 mp4
    """
    opts: dict[str, Any] = {
        "format": _format_selector(quality),
        "outtmpl": str(output_path),
        "merge_output_format": "mp4",
        "remux_video": "mp4",
        "quiet": True,
        "no_warnings": True,
        # 抑制终端进度条（进度仍经 progress_hooks 回调），避免污染 server 日志
        "noprogress": True,
        "continuedl": True,     # 断点续传
        "part": True,           # 保留 .part，中断后可续
        "retries": 3,
        "fragment_retries": 5,
        # 实测目标站 CDN 偶发读超时（20s 会报 Read timed out），
        # 与解析子进程的 --socket-timeout 30 对齐
        "socket_timeout": 30,
        "http_headers": {"User-Agent": ua},
    }
    if referer:
        opts["http_headers"]["Referer"] = referer
    if proxy:
        opts["proxy"] = proxy
    if rename_strategy == "overwrite":
        opts["overwrites"] = True
    if progress_hook:
        opts["progress_hooks"] = [progress_hook]
    return opts


async def download_generic_video(
    video: GenericVideo,
    output_dir: Path,
    quality: str = "best",
    task_id: str | None = None,
    rename_strategy: str | None = None,
    progress_callback=None,
    name_hint: str = "",
) -> Path:
    """下载通用视频并转封装为 mp4。

    Args:
        video: parse_generic() 的结果（含 referer）
        output_dir: 输出目录
        quality: best / 1080 / 720 / 480 / 360
        task_id: 用于暂停/取消检测（download_queue）
        rename_strategy: overwrite 时允许覆盖已有文件
        progress_callback: 额外的进度回调
        name_hint: 命名提示（书签标题/选集条目标题），优先级见 build_file_stem

    Returns:
        实际产物路径
    """
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("yt-dlp 未安装，请运行: pip install yt-dlp")

    from .download_queue import download_queue
    from .proxy import get_yt_dlp_proxy
    from .utils import load_config, sanitize_filename

    output_dir.mkdir(parents=True, exist_ok=True)

    # 文件名：书签标题/网页标题/剧名集数 优先，弱名才回退 web_ + URL 末段
    stem = sanitize_filename(build_file_stem(
        hint=name_hint,
        title=video.title,
        page_title=video.page_title,
        url=video.url,
    ))
    outtmpl = str(output_dir / f"{stem}.%(ext)s")

    proxy = get_yt_dlp_proxy("generic", load_config())

    # HLS 分片切换时 yt-dlp 会重算 downloaded_bytes，导致进度出现
    # ~0.1% 级回退（实测 2876 样本中多次 0.0022→0.0021），
    # 这里做单调平滑，避免进度条来回抖动
    _progress_state = {"last": 0.0}
    # 中止信号可能被 hook 反复触发（HLS 每个分片都回调），日志只打一次
    _abort_logged = {"done": False}

    def _abort(msg):
        if not _abort_logged["done"]:
            _abort_logged["done"] = True
            logger.info(f"[Generic] {msg}，立即中止下载（task_id={task_id}）")
        raise AbortDownload(msg)

    def _hook(d):
        if d.get("status") == "downloading":
            if task_id and download_queue.is_cancelled(task_id):
                _abort("下载已取消")
            if task_id and download_queue.is_paused(task_id):
                _abort("下载已暂停")

            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            if total > 0:
                p = downloaded / total
                # 单调不回退（只对当前任务生效，重开任务自然重置）
                p = max(p, _progress_state["last"])
                _progress_state["last"] = p
                if progress_callback:
                    progress_callback(p)
                if task_id:
                    download_queue.update_progress(task_id, p, downloaded, total)
        elif d.get("status") == "finished":
            _progress_state["last"] = 1.0
            if progress_callback:
                progress_callback(1.0)
            if task_id:
                download_queue.update_progress(task_id, 1.0)

    opts = build_ydl_opts(
        output_path=outtmpl,
        quality=quality,
        referer=video.referer,
        rename_strategy=rename_strategy,
        progress_hook=_hook,
        proxy=proxy,
    )

    def _run():
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([video.url])

    logger.info(f"[Generic] 开始下载: {video.title[:60]} (referer={video.referer[:60]})")
    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _run)
    except AbortDownload:
        # AbortDownload 的 traceback 在整个传播期间都持有 yt-dlp 未关闭的
        # .part 文件句柄（except 块执行时 exc_info 始终持有栈帧，gc 无法回收）。
        # 实测不处理时 cancel 后 60s 内残留文件始终删除失败。
        # 这里登记一个延迟回调，等异常传播完毕（exc_info 清除、栈帧可回收）
        # 再触发分代回收，句柄随即释放，残留才能被清理。
        loop.call_later(0.5, gc.collect)
        raise

    # remux 后产物 ext 为 mp4；ffmpeg 缺失时可能停在 ts，一并兜底
    for suffix in (".mp4", ".mkv", ".webm", ".ts", ".flv"):
        f = output_dir / f"{stem}{suffix}"
        if f.exists() and f.stat().st_size > 0:
            logger.info(f"[Generic] 下载完成: {f.name}")
            return f

    raise RuntimeError("下载失败，未找到输出文件")
