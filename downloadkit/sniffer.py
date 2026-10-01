# -*- coding: utf-8 -*-
"""L2 浏览器嗅探引擎（DrissionPage 4.x + 系统 Edge）。

三层降级流水线（计划书 §4.1）的最深层：L0 直链 / L1 静态深挖都拿不到
流地址时，用真实浏览器打开页面，通过 CDP 网络监听抓 m3u8/mp4。

三个关键实测结论（计划书 §3，改动前先回看实测脚本）：
  1. SafeLine WAF 是 JS 挑战型：前 ~6s 468，t≈8s 自动整页刷新到 200。
     判定 = navigation responseStatus < 400 且 html 不含 safeline；
     挑战通过时页面刷新，DrissionPage 抛「页面被刷新」异常 → 捕获重试即可。
  2. DrissionPage listen 不覆盖 OOPIF（跨域 iframe 播放器）：
     实测主页面 92 条监听请求里连 iframe 文档本身都不出现。
  3. 解法（方案Z）= 把播放器 iframe URL 提升为顶层标签再监听，
     实测抓到 playlist.m3u8 + 各清晰度流（probe_planz.py 验证）。

线程模型：DrissionPage 为同步 API —— 一律经 asyncio.to_thread 进 async 路由；
浏览器单例 + threading.Lock 串行化整个 L2 嗅探（R7/R8；P3 再评估多标签并发）。
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any

logger = logging.getLogger(__name__)

# 系统 Edge（DrissionPage 不带浏览器，R6/R9）
_EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"

# ---------------- 正则常量 / 播放器解析（选流去重见 stream_filter.py） ------

# 选流去重纯函数（§4.3）P5 按 §5.1 抽至 stream_filter.py；
# re-export 保持 downloadkit.sniffer.extract_stream_urls 等旧 import 兼容。
from .stream_filter import (  # noqa: E402
    AD_RE as _AD_RE,
    STREAM_RE,
    dedupe_streams,
    extract_stream_urls,
    prefer_main_streams,
)
# 疑似「拿播放器地址」的 API（读响应体用，避免读大响应）
_API_LIKE_RE = re.compile(
    r"player|pframe|geturl|playurl|chapter|content|video_info|config|\.php|api/", re.I
)
# 播放器 iframe 特征
_PLAYER_HINT_RE = re.compile(r"player|pframe|embed|player\.htm|vod", re.I)

_WAF_MARKERS_RE = re.compile(r"safeline|安全检测|正在进行安全", re.I)


def find_player_url(
    bodies: list[str],
    dom_iframes: list[str],
    page_html: str = "",
) -> str:
    """三级来源找播放器地址（§4.2.2 步骤4）：
    a. XHR 响应体（样本2 命中 content_pframe_url）
    b. DOM iframe src
    c. 页面 HTML 中的 player 链接
    """
    # a. XHR 响应体：pframe/player 特征优先，其次任意 pframe URL、其次响应体里的 m3u8 页
    for body in bodies:
        if not body:
            continue
        m = re.search(r'https?://[^\s"\'<>]+?(?:pframe|player\.htm|/player/?)[^\s"\'<>]*', body, re.I)
        if m:
            return m.group(0)
    for body in bodies:
        if not body:
            continue
        m = re.search(r'https?://[^\s"\'<>]{10,300}', body)
        if m and _PLAYER_HINT_RE.search(m.group(0)):
            return m.group(0)
    # b. DOM iframe（过滤 data:/about: 与广告 iframe，播放器特征优先）
    cand = [s for s in dom_iframes
            if s and s.startswith(("http://", "https://")) and not _AD_RE.search(s)]
    for s in cand:
        if _PLAYER_HINT_RE.search(s):
            return s
    if cand:
        return cand[0]
    # c. 页面 HTML 里的 player 链接
    if page_html:
        m = re.search(
            r'https?://[^\s"\'<>\\)]+(?:player|pframe|embed)[^\s"\'<>\\)]*',
            page_html, re.I,
        )
        if m:
            return m.group(0)
    return ""


# ---------------- 数据结构 ----------------

@dataclass
class SniffStream:
    url: str
    kind: str = "m3u8"          # m3u8 | mp4 | mpd
    referer: str = ""           # 监听到该流时所在页面（防盗链必需）
    ua: str = ""


@dataclass
class SniffResult:
    url: str                    # 输入 URL
    ok: bool = False
    method: str = ""            # main（主页面命中）| player（iframe 提升）| js（hook 兜底）
    streams: list[SniffStream] = field(default_factory=list)
    player_url: str = ""        # 提升用的播放器地址
    page_url: str = ""          # 最终页面 URL（跟随跳转）
    title: str = ""
    referer: str = ""           # 默认 Referer（主页面）
    ua: str = ""
    cookies: str = ""
    requests_seen: int = 0
    elapsed: float = 0.0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------- 浏览器实例管理 ----------------

_lock = threading.Lock()        # 串行化 L2 嗅探（DrissionPage 单例非线程安全）
_page: Any = None               # ChromiumPage 单例


def _get_page():
    """获取（或启动）浏览器单例。必须在 _lock 内调用。"""
    global _page
    if _page is not None:
        return _page
    from DrissionPage import ChromiumOptions, ChromiumPage

    co = ChromiumOptions()
    if os.path.exists(_EDGE_PATH):
        co.set_browser_path(_EDGE_PATH)
    co.auto_port()              # 独立端口/临时 profile，不污染用户日常浏览器
    co.headless(False)          # WAF 挑战与播放行为用有头模式最稳（实测均为有头）
    co.set_argument("--lang=zh-CN")
    co.set_argument("--disable-popup-blocking")
    # 临时 profile 每次都是"首启"——抑制首启向导/sync 确认页抢导航
    # （仍可能漏网，抓取与嗅探侧另有「内部页重新导航」兜底）
    co.set_argument("--no-first-run")
    co.set_argument("--disable-sync")
    co.set_argument("--hide-crash-restore-state")
    co.set_argument("--disable-session-crashed-bubble")
    _page = ChromiumPage(co)
    logger.info("[Sniffer] Edge 已启动")
    return _page


def shutdown() -> None:
    """关闭嗅探浏览器（server shutdown 时调用）。"""
    global _page
    with _lock:
        if _page is not None:
            try:
                _page.quit()
            except Exception:  # noqa: BLE001
                pass
            _page = None
            logger.info("[Sniffer] Edge 已关闭")


def reset_browser() -> None:
    """连接失效时丢弃单例，下次自动重建（外部调用）。"""
    with _lock:
        _reset_browser_locked()


def _reset_browser_locked() -> None:
    """丢弃单例（必须已持 _lock；threading.Lock 不可重入，内部勿再套锁）。"""
    global _page
    _page = None


# ---------------- 监听与 WAF（同步，被 _lock 保护） ----------------

_NAV_STATUS_JS = (
    "return performance.getEntriesByType('navigation')[0]?"
    ".responseStatus || 0"
)
_UA_JS = "return navigator.userAgent"
_IFRAMES_JS = (
    "return Array.from(document.querySelectorAll('iframe'))"
    ".map(function(f){return f.src}).filter(Boolean)"
)


def _collect(tab, count: int = 10, timeout: float = 1.0) -> list:
    """收一批监听包（DrissionPage steps 的统一异常兜底）。"""
    try:
        return list(tab.listen.steps(count=count, timeout=timeout) or [])
    except Exception:  # noqa: BLE001 — 等待超时/页面刷新都走这里
        return []


def _page_ready(tab) -> bool:
    """WAF 挑战是否已通过：responseStatus<400 且非拦截页。

    挑战通过瞬间整页刷新，DrissionPage 会抛「页面被刷新」类异常 → 返回 False 下轮再查。
    只认 http(s) 当前页：Edge 临时 profile 首启的 sync 确认页等内部页的
    navigation responseStatus 同样是 200，会误判为「WAF 已过」。
    """
    try:
        cur = str(tab.url or "")
        code = int(tab.run_js(_NAV_STATUS_JS) or 0)
        html = tab.html or ""
    except Exception:  # noqa: BLE001
        return False
    if not cur.startswith(("http://", "https://")):
        return False
    if _WAF_MARKERS_RE.search(html):
        return False
    if code >= 400:
        return False
    return code > 0


def _sniff_exception_error(e: BaseException) -> str:
    """嗅探外层异常的用户可读文案（浏览器 CDP 连接失效最常见）。

    Edge 崩溃后下一次调用会自动重启浏览器——把 urllib3/requests 的连接异常
    原文（Max retries exceeded / WinError 10061…）换成可操作的提示。
    """
    msg = str(e)
    if (isinstance(e, OSError) or "Max retries" in msg
            or "Connection" in type(e).__name__):
        return "浏览器连接异常（已自动重启，直接重试即可）"
    return f"{type(e).__name__}: {msg[:200]}"


def _miss_error(nav_failed: bool, waf_ok: bool) -> str:
    """未命中时的用户可读错误，按层区分（P5 遗留修复）。

    导航失败（死端口/域名不可达/站点下线）≠ WAF 挑战未过 ≠ 页面已开但无流——
    之前死端口页 _page_ready 恒 False，被兜底误报成「WAF 挑战未在时限内通过」。
    """
    if nav_failed:
        return "页面打开失败（连接被拒绝/域名不可达/站点已下线）"
    if waf_ok:
        return "页面未见流地址（可能无视频/播放需登录/WAF 未通过）"
    return "WAF 挑战未在时限内通过"


def _pkt_body(pkt) -> str:
    """响应体（只给疑似 API 包用）。"""
    try:
        body = pkt.response.body
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        return str(body or "")
    except Exception:  # noqa: BLE001
        return ""


def _cookies_of(tab) -> str:
    try:
        return "; ".join(
            f"{c.get('name')}={c.get('value')}" for c in tab.cookies()
            if c.get("name")
        )
    except Exception:  # noqa: BLE001
        return ""


def _streams_from(pkts: list, bodies: list[str]) -> list[str]:
    """从监听包 URL + API 响应体挖流（提流→去重→主子区分的统一入口）。"""
    text = "\n".join(
        [str(getattr(p, "url", "") or "") for p in pkts] + list(bodies)
    )
    return prefer_main_streams(dedupe_streams(extract_stream_urls(text)))


def _kind_of(u: str) -> str:
    m = re.search(r"\.(m3u8|mpd|mp4)(?:[?#]|$)", u, re.I)
    return m.group(1).lower() if m else "m3u8"


# JS hook 兜底（§4.2.3）：拦 fetch / XHR / media src，记录到 window.__sniffed
_HOOK_JS = r"""
(function(){
  if (window.__dkHook) return; window.__dkHook = true;
  window.__sniffed = window.__sniffed || [];
  var rec = function(u){ try { window.__sniffed.push(String(u)); } catch(e){} };
  var of = window.fetch;
  if (of) window.fetch = function(inp){
    try { rec(inp && inp.url ? inp.url : inp); } catch(e){}
    return of.apply(this, arguments);
  };
  var oo = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(m, u){ try { rec(u); } catch(e){}
    return oo.apply(this, arguments); };
  var d = Object.getOwnPropertyDescriptor(HTMLMediaElement.prototype, 'src');
  if (d && d.set) Object.defineProperty(HTMLMediaElement.prototype, 'src', {
    set: function(v){ try { rec(v); } catch(e){} return d.set.call(this, v); },
    get: d.get
  });
})();
"""

_TRIGGER_PLAY_JS = r"""
var v = document.querySelector('video');
if (v) { try { v.muted = true; v.play().catch(function(){}); } catch(e){} }
['[class*=play]', '.pristart', '.module-play-poster', '#player', '.play-btn', '.btn-play']
  .forEach(function(s){ var e = document.querySelector(s); if (e) { try { e.click(); } catch(err){} } });
return true;
"""


# ---------------- 单页嗅探主流程（同步，必须持 _lock 调用） ----------------

def _sniff_locked(url: str, timeout: float) -> SniffResult:
    t0 = time.monotonic()
    res = SniffResult(url=url)
    deadline_total = t0 + timeout

    main_tab = None
    player_tab = None
    all_pkts: list = []
    bodies: list[str] = []
    ua = ""
    from_player = False

    try:
        page = _get_page()

        # ===== 阶段1：主页面（WAF 等待 + 收包 + 提播放器地址）=====
        main_tab = page.latest_tab
        main_tab.listen.start()
        try:
            main_tab.get(url, timeout=min(12.0, max(4.0, timeout - 2)))
        except Exception:  # noqa: BLE001 — WAF 挑战中导航超时是常态，靠轮询接管
            pass

        phase1_end = min(deadline_total, t0 + 15.0)
        waf_ok = False
        waf_ok_at = 0.0
        player_url = ""
        seen_urls: set[str] = set()
        phase1_renav = 0
        last_renav = 0.0
        nav_failed = False       # 导航失败错误页（≠ WAF 挑战，见 _miss_error）
        nav_fail_streak = 0
        while time.monotonic() < phase1_end:
            # Edge 临时 profile 首启的 sync 确认页会覆盖首次导航（tab 停在
            # edge:// 内部页）→ 浏览器启动完成后重新导航，限 2 次防死循环
            try:
                cur_url = str(main_tab.url or "")
            except Exception:  # noqa: BLE001
                cur_url = ""
            if (not cur_url.startswith(("http://", "https://"))
                    and phase1_renav < 2
                    and time.monotonic() - last_renav > 2.0):
                phase1_renav += 1
                last_renav = time.monotonic()
                try:
                    main_tab.get(url, timeout=min(12.0, max(4.0, timeout - 2)))
                except Exception:  # noqa: BLE001
                    pass
                continue
            # 导航失败错误页（死端口/DNS 失败）：连续 3 轮确认后提前结束
            # 主页面阶段——页面打不开时 WAF/播放器阶段必然白等（P5 遗留修复）
            if cur_url.startswith("chrome-error:"):
                nav_fail_streak += 1
            else:
                try:
                    _phtml = main_tab.html or ""
                except Exception:  # noqa: BLE001 — 刷新瞬间抛错，下轮再查
                    _phtml = ""
                if _NAV_ERROR_RE.search(_phtml[:20000]):
                    nav_fail_streak += 1
                else:
                    nav_fail_streak = 0
            if nav_fail_streak >= 3:
                nav_failed = True
                logger.info(f"[Sniffer] 导航失败错误页确认，提前结束主页面阶段 {url[:70]}")
                break
            for pkt in _collect(main_tab, count=10, timeout=1.0):
                u = str(getattr(pkt, "url", "") or "")
                if u and u not in seen_urls:
                    seen_urls.add(u)
                    all_pkts.append(pkt)
                    if _API_LIKE_RE.search(u):
                        b = _pkt_body(pkt)
                        if b:
                            bodies.append(b)
            if not waf_ok:
                waf_ok = _page_ready(main_tab)
                if waf_ok:
                    waf_ok_at = time.monotonic()
            cur = _streams_from(all_pkts, bodies)
            # 就绪且已见流 → 再多收 2 秒收全多清晰度，转下载判定
            if waf_ok and cur:
                extra_end = min(phase1_end, time.monotonic() + 2.0)
                while time.monotonic() < extra_end:
                    for pkt in _collect(main_tab, count=10, timeout=1.0):
                        u = str(getattr(pkt, "url", "") or "")
                        if u and u not in seen_urls:
                            seen_urls.add(u)
                            all_pkts.append(pkt)
                break
            # 每轮轻探测播放器地址（iframe 是动态注入的，时机随网络波动，
            # 样本2 实测 4s~14s 不等 —— 只在循环末尾查一次会漏）
            if waf_ok and not player_url:
                player_url = find_player_url(bodies, _dom_iframes(main_tab))
                if player_url:
                    break   # 有提升入口且主页面无流 → 提前转阶段2
            # 就绪但既无流也无播放器（播放器在跨域 iframe，尚未注入）
            # → 观察 10s 后放弃主页面阶段
            if waf_ok and time.monotonic() - waf_ok_at > 10.0:
                break

        # 主页面结果
        try:
            res.page_url = str(main_tab.url or url)
            res.title = str(main_tab.title or "")
            ua = str(main_tab.run_js(_UA_JS) or "")
        except Exception:  # noqa: BLE001 — 挑战刷新中属性访问可能抛
            res.page_url = res.page_url or url
        res.referer = res.page_url
        res.ua = ua
        res.cookies = _cookies_of(main_tab)

        main_urls = _streams_from(all_pkts, bodies)

        # ===== 阶段2：iframe 提升（方案Z）=====
        # 导航失败的错误页里没有播放器入口，跳过查提升
        if not player_url and not nav_failed:   # 循环内轻探测没抓到 → 完整再查一次（含页面 HTML 兜底）
            player_url = find_player_url(
                bodies,
                _dom_iframes(main_tab),
                _tab_html(main_tab),
            )
        res.player_url = player_url

        if not main_urls and player_url and time.monotonic() < deadline_total:
            try:
                player_tab = page.new_tab(player_url)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"[Sniffer] 播放器标签打开失败: {e}")
                player_tab = None
            if player_tab is not None:
                try:
                    player_tab.listen.start()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    player_tab.refresh()   # 实测顺序：new_tab → listen.start → refresh
                except Exception:  # noqa: BLE001 — 刷新异常则退回显式导航
                    try:
                        player_tab.get(player_url, timeout=10)
                    except Exception:  # noqa: BLE001
                        pass

            if player_tab is not None:
                from_player = True
                p_seen: set[str] = set()
                phase2_end = min(deadline_total, time.monotonic() + 12.0)
                while time.monotonic() < phase2_end:
                    for pkt in _collect(player_tab, count=10, timeout=1.0):
                        u = str(getattr(pkt, "url", "") or "")
                        if u and u not in p_seen:
                            p_seen.add(u)
                            all_pkts.append(pkt)
                            if _API_LIKE_RE.search(u):
                                b = _pkt_body(pkt)
                                if b:
                                    bodies.append(b)
                    # 播放器页见到流再多收 2 秒收全多清晰度
                    if _streams_from(all_pkts, bodies):
                        extra_end = min(phase2_end, time.monotonic() + 2.0)
                        while time.monotonic() < extra_end:
                            for pkt in _collect(player_tab, count=10, timeout=1.0):
                                u = str(getattr(pkt, "url", "") or "")
                                if u and u not in p_seen:
                                    p_seen.add(u)
                                    all_pkts.append(pkt)
                        break
                # 播放器页上下文覆盖 Referer/UA/Cookie
                try:
                    res.referer = str(player_tab.url or player_url)
                    res.ua = str(player_tab.run_js(_UA_JS) or ua)
                    c = _cookies_of(player_tab)
                    if c:
                        res.cookies = c
                    if not res.title:
                        res.title = str(player_tab.title or "")
                except Exception:  # noqa: BLE001
                    res.referer = player_url

        # ===== 阶段3：JS hook 兜底（仅当仍无流）=====
        stream_urls = _streams_from(all_pkts, bodies)
        if not stream_urls and not nav_failed:
            hook_seen: set[str] = set()
            try:
                main_tab.run_js(_HOOK_JS)
                main_tab.run_js(_TRIGGER_PLAY_JS)
            except Exception:  # noqa: BLE001
                pass
            hook_end = min(deadline_total, time.monotonic() + 6.0)
            while time.monotonic() < hook_end:
                for pkt in _collect(main_tab, count=10, timeout=1.0):
                    all_pkts.append(pkt)
                try:
                    extra = main_tab.run_js("return window.__sniffed || []") or []
                    for e in extra:
                        s = str(e)
                        if s and s not in hook_seen:   # __sniffed 累积，避免重复追加
                            hook_seen.add(s)
                            bodies.append(s)
                except Exception:  # noqa: BLE001
                    pass
                stream_urls = _streams_from(all_pkts, bodies)
                if stream_urls:
                    break
            if stream_urls:
                res.method = "js"

        res.requests_seen = len(all_pkts)
        res.streams = [
            SniffStream(
                url=u,
                kind=_kind_of(u),
                referer=res.referer,
                ua=res.ua,
            )
            for u in stream_urls
        ]
        res.ok = bool(res.streams)
        if res.ok and not res.method:
            res.method = "player" if from_player else "main"
        if not res.ok and not res.error:
            res.error = _miss_error(nav_failed, waf_ok)

    except Exception as e:  # noqa: BLE001 — 浏览器连接失效等
        logger.warning(f"[Sniffer] 嗅探异常 {url[:80]}: {type(e).__name__}: {e}")
        res.error = _sniff_exception_error(e)
        _reset_browser_locked()   # 连接失效 → 丢弃单例，下次重建（已持锁）
    finally:
        for t in (player_tab,):
            if t is not None:
                try:
                    t.listen.stop()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    t.close()
                except Exception:  # noqa: BLE001
                    pass
        if main_tab is not None:
            try:
                main_tab.listen.stop()
            except Exception:  # noqa: BLE001
                pass
        res.elapsed = round(time.monotonic() - t0, 2)

    logger.info(
        f"[Sniffer] {'命中' if res.ok else '未命中'} {len(res.streams)} 流 "
        f"method={res.method or '-'} {res.elapsed}s req={res.requests_seen} {url[:70]}"
    )
    return res


def _dom_iframes(tab) -> list[str]:
    try:
        return list(tab.run_js(_IFRAMES_JS) or [])
    except Exception:  # noqa: BLE001
        return []


def _tab_html(tab) -> str:
    try:
        return str(tab.html or "")
    except Exception:  # noqa: BLE001
        return ""


# ---------------- 对外 API ----------------

# Chromium/Edge 导航失败错误页特征（title 常伪装成目标域名，须按内容识别）
_NAV_ERROR_RE = re.compile(r"main-frame-error|chrome-error://|neterror", re.I)


def fetch_page_html_sync(url: str, timeout: float = 25.0) -> str:
    """打开页面并等 WAF 通过后返回完整 DOM HTML（P4 选集提取的 L2 通道）。

    与 _sniff_locked 共用浏览器单例与 _lock（串行排队）。三层防护：
      · 只认 http(s) 最终 URL —— 挡临时 profile 首启的 edge:// 同步弹窗等内部页
      · 按内容识别导航失败错误页（title 伪装成目标域名）—— 连续确认后提前
        放弃并重试导航一次，不傻等到 deadline
      · WAF 拦截页继续等（挑战中），超时兜底同样按上述规则过滤
    导航彻底失败/拦截页返回 ""。
    """
    t0 = time.monotonic()
    deadline = t0 + timeout
    with _lock:
        page = _get_page()
        tab = page.latest_tab

        def _nav() -> None:
            try:
                tab.get(url, timeout=min(12.0, max(4.0, timeout - 2)))
            except Exception:  # noqa: BLE001 — WAF 挑战中导航超时是常态
                pass

        _nav()
        bad_streak = 0
        retried = False
        renav = 0
        last_renav = t0
        while time.monotonic() < deadline:
            try:
                cur = str(tab.url or "")
                html = tab.html or ""
            except Exception:  # noqa: BLE001 — 页面刷新瞬间抛错，下轮再查
                cur, html = "", ""
            if not cur.startswith(("http://", "https://")):
                # Edge 首启 sync 弹窗等内部页覆盖首次导航 → 重新导航（限 2 次）
                if renav < 2 and time.monotonic() - last_renav > 2.0:
                    renav += 1
                    last_renav = time.monotonic()
                    _nav()
                time.sleep(0.5)
                continue
            if html:
                if _NAV_ERROR_RE.search(html[:20000]):
                    bad_streak += 1
                    if bad_streak >= 4:
                        if not retried:
                            retried = True
                            bad_streak = 0
                            _nav()          # 瞬时失败（DNS 首查）重试一次
                        else:
                            return ""       # 导航失败已确认
                elif not _WAF_MARKERS_RE.search(html) and len(html) >= 200:
                    return html
                else:
                    bad_streak = 0          # WAF 挑战中，继续等
            time.sleep(0.5)
        # 超时兜底：同样只放行 http(s) + 非错误页 + 非拦截页
        try:
            cur = str(tab.url or "")
            html = tab.html or ""
            if (cur.startswith(("http://", "https://"))
                    and html and len(html) >= 200
                    and not _NAV_ERROR_RE.search(html[:20000])
                    and not _WAF_MARKERS_RE.search(html)):
                return html
        except Exception:  # noqa: BLE001
            pass
        return ""


async def fetch_page_html(url: str, timeout: float = 25.0) -> str:
    """async 入口（to_thread 桥接；与嗅探共用全局锁，串行排队）。"""
    return await asyncio.to_thread(fetch_page_html_sync, url, timeout=timeout)


def sniff_sync(url: str, timeout: float = 30.0) -> SniffResult:
    """L2 深度嗅探（同步，直接调用会阻塞；服务端走 async 入口 sniff()）。"""
    with _lock:
        return _sniff_locked(url, timeout=timeout)


async def sniff(url: str, timeout: float = 30.0) -> SniffResult:
    """L2 深度嗅探（async 入口，内部 to_thread 桥接同步 DrissionPage）。"""
    return await asyncio.to_thread(sniff_sync, url, timeout=timeout)
