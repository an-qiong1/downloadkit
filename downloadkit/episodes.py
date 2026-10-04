# -*- coding: utf-8 -*-
"""选集展开（P4，计划书 §4.6 三级回退）。

路1  yt-dlp 原生 playlist（B站合集/YouTube 等，flat dump → _type=='playlist'）
路2  通用模板聚类（已按 2 个真实样本实测验证，§4.6.2）：
       L1 静态抓 HTML → 失败再 L2 浏览器 DOM（过 WAF 后选集即在静态 DOM）
路3  返回空组 + error，由调用方回退单集下载

聚类算法要点：
  · 抽全部 <a href>（a 内文本作 label；样本2 的 span.sequence 无 href，
    但其父级 <a> 有 —— HTMLParser 从 a 收集后代文本天然覆盖）
  · path 模板化：纯数字段 → {id}，≥10 位字母数字混合段 → {b64}
  · query 只保留跨链接不变的参数（cartoon_id 常量），离群值剔除
  · 成员数 ≥3 的组才保留（防误判导航/推荐链接），按成员数降序
  · 排序：第N集/纯数字 → 整数升序；非数字集（特殊集名）按 DOM 序垫底
"""
from __future__ import annotations

import logging
import re
import time
from collections import Counter
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Optional
from urllib.parse import parse_qsl, urljoin, urlparse

logger = logging.getLogger(__name__)

MIN_GROUP = 3          # 组内成员下限（§4.6.2 ③）
LABEL_MAX = 40         # 显示截断


# ---------------- 数据结构 ----------------

@dataclass
class Episode:
    url: str
    label: str      # 显示名（归一为「第N集」或原文截断）
    order: int      # 数值排序键；无数字 = -1
    dom: int        # DOM 出现序（次级排序键，特殊集按此排）


# ---------------- 链接抽取（HTMLParser，覆盖 a 后代文本） ----------------

class _LinkParser(HTMLParser):
    """抽取全部 <a href> 及其后代文本（含 span 等子元素）。"""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: Optional[str] = None
        self._buf: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag == "a" and self._href is None:
            href = dict(attrs).get("href")
            if href:
                self._href = href.strip()
                self._buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, "".join(self._buf).strip()))
            self._href = None
            self._buf = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._buf.append(data)


# ---------------- 模板化 ----------------

_NUM_SEG_RE = re.compile(r"^\d+$")
# ID 段：≥10 位字母数字（含 _-）。纯字母 slug（shixiongashixiong-jinlei）
# 全小写且无数字 → 不命中；大小写混合（udWdMztqNU）或含数字 → 命中。
_B64_SEG_RE = re.compile(
    r"^(?=[A-Za-z0-9_\-]{10,})(?=.*[A-Za-z])(?=.*[A-Z0-9])[A-Za-z0-9_\-]+={0,2}$"
)
# 短段内嵌数字（ep1 / show-1234）→ 抽出数字段（§4.6.2「path 中含数字段→{id}」）
_EMBED_NUM_RE = re.compile(r"\d+")


def template_path(path: str) -> str:
    """path 模板化（§4.6.2 ②）：
    ① 纯数字段 → {id}；② 长 ID 段（≥10 位，含大写或数字）→ {b64}；
    ③ 其余含数字段 → 数字部分 → {id}（ep1 → ep{id}）；④ 无数字原样。
    """
    out: list[str] = []
    for seg in path.split("/"):
        if not seg:
            out.append(seg)
            continue
        body, ext = seg, ""
        if "." in seg:
            b, e = seg.rsplit(".", 1)
            if e.isalpha() and 1 <= len(e) <= 5:
                body, ext = b, "." + e
        if _NUM_SEG_RE.match(body):
            out.append("{id}" + ext)
        elif _B64_SEG_RE.match(body):
            out.append("{b64}" + ext)
        elif _EMBED_NUM_RE.search(body):
            out.append(_EMBED_NUM_RE.sub("{id}", body) + ext)
        else:
            out.append(seg)
    return "/".join(out)


# ---------------- label / 排序 ----------------

_EP_NUM_RE = re.compile(r"第\s*(\d+)\s*[集话期]")
_STANDALONE_NUM_RE = re.compile(r"^\d{1,5}$")


def label_and_order(text: str) -> tuple[str, int]:
    """→ (显示名, 数值排序键)。第N集/纯数字归一为「第N集」；其余原文截断。"""
    t = re.sub(r"\s+", " ", text or "").strip()
    m = _EP_NUM_RE.search(t)
    if m:
        n = int(m.group(1))
        return f"第{n}集", n
    if _STANDALONE_NUM_RE.match(t):
        n = int(t)
        return f"第{n}集", n
    return t[:LABEL_MAX], -1


# 详情页「播放/立即观看」入口按钮（语义 = 第1集，chapter_id 常独立于选集项）
_ENTRY_LABEL_RE = re.compile(
    r"^(播放|立即播放|开始播放|立刻播放|立即观看|开始观看|观看|正片|继续观看)$"
)


def _repair_missing_first(members: list[dict]) -> None:
    """详情页常见结构：第1集做成「播放」入口（实测样本2 详情页：数字集从第2
    集起、入口按钮 chapter_id 独立，去重后总数与集数吻合）。数字序列缺第1集
    且恰有一个入口词成员 → 就地补为第1集。"""
    nums = [m["order"] for m in members if m["order"] >= 0]
    if not nums or min(nums) <= 1:
        return
    entries = [m for m in members
               if m["order"] < 0 and _ENTRY_LABEL_RE.match(m["label"])]
    if len(entries) == 1:
        entries[0]["order"], entries[0]["label"] = 1, "第1集"


def _sort_members(members: list[dict]) -> list[dict]:
    """数字集按集数升序；无数字成员（特殊集名/未识别文本）按 DOM 序**插入**
    数字序列中其应在的位置（不垫底）—— 混序特殊集保持页面原相对顺序。"""
    nums = sorted((m for m in members if m["order"] >= 0), key=lambda m: m["order"])
    others = sorted((m for m in members if m["order"] < 0), key=lambda m: m["dom"])
    if not others:
        return nums
    inserts: dict[int, list[dict]] = {}
    for m in others:
        k = sum(1 for n in nums if n["dom"] < m["dom"])
        inserts.setdefault(k, []).append(m)
    result = list(nums)
    for k in sorted(inserts, reverse=True):   # 从后往前插，避免下标漂移
        result[k:k] = inserts[k]
    return result


# ---------------- 模板聚类（§4.6.2 ②③④） ----------------

def _query_outlier_filter(members: list[dict]) -> list[dict]:
    """准常量 query 参数上的离群链接剔除（如混入其他 cartoon_id 的推荐链接）。

    key 出现率 <50% 不检查；众数占比 ≥90% 且存在多值 → 保留众数值链接。
    """
    if len(members) < MIN_GROUP:
        return members
    total = len(members)
    keys: Counter = Counter()
    for m in members:
        keys.update(m["q"].keys())
    for k, cnt in keys.items():
        if cnt / total < 0.5:
            continue
        vals = Counter(m["q"][k] for m in members if k in m["q"])
        if len(vals) <= 1:
            continue
        top, top_n = vals.most_common(1)[0]
        if top_n / total >= 0.9:
            members = [m for m in members if m["q"].get(k, top) == top]
    return members


def extract_from_html(html: str, base_url: str) -> dict[str, Any]:
    """通用选集提取：链接抽取 → path 模板聚类 → 过滤 → 排序。

    Returns:
        {"count": 最大组成员数,
         "groups": [{"template", "count", "items": [{"url", "label"}...]}...]}
        groups 按 count 降序，仅含 count >= MIN_GROUP 的组。
    """
    empty: dict[str, Any] = {"count": 0, "groups": []}
    if not html or not base_url:
        return empty

    parser = _LinkParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception as e:  # noqa: BLE001 — 畸形 HTML 不应让展开失败
        logger.debug(f"[Episodes] HTML 解析异常 {base_url[:80]}: {e}")

    # 抽链接 → 归一绝对 URL → path 模板分组（保序去重）
    groups: dict[str, list[dict]] = {}
    seen: set[str] = set()
    dom = 0
    for href, text in parser.links:
        if not href or href.startswith(("#", "javascript:", "mailto:", "data:")):
            continue
        u = urljoin(base_url, href)
        if not u.startswith(("http://", "https://")) or u in seen:
            continue
        seen.add(u)
        p = urlparse(u)
        label, order = label_and_order(text)
        tpl = template_path(p.path)
        groups.setdefault(tpl, []).append({
            "url": u, "label": label, "order": order, "dom": dom,
            "q": dict(parse_qsl(p.query, keep_blank_values=True)),
        })
        dom += 1

    # 离群过滤 → ≥3 → 补缺第1集 → 排序 → 输出
    out: list[dict] = []
    for tpl, members in groups.items():
        members = _query_outlier_filter(members)
        if len(members) < MIN_GROUP:
            continue
        _repair_missing_first(members)
        members = _sort_members(members)
        out.append({
            "template": tpl,
            "count": len(members),
            "items": [{"url": m["url"], "label": m["label"]} for m in members],
        })
    out.sort(key=lambda g: -g["count"])
    return {"count": (out[0]["count"] if out else 0), "groups": out}


# ---------------- 路1：yt-dlp 原生 playlist ----------------

async def _expand_ytdlp(url: str) -> tuple[list[dict], str]:
    """flat dump 判真播放列表 → entries 扁平化，附 playlist 级标题。

    返回 (items, playlist_title)。失败/非 playlist 返回 ([], "")。
    """
    from downloadkit.generic_video import _classify_entries, _ytdlp_dump_json

    try:
        entries = await _ytdlp_dump_json(url, flat=True, timeout=20)
    except Exception as e:  # noqa: BLE001 — 影视站 generic 必失败，属预期
        logger.debug(f"[Episodes] yt-dlp 路径失败 {url[:80]}: {e}")
        return [], ""
    is_playlist, _ = _classify_entries(entries)
    if not is_playlist:
        return [], ""
    # flat dump 每条 entry 携带 playlist 级标题（剧名的唯一来源，路1 曾传空）
    title = ""
    for e in entries:
        t = str(e.get("playlist_title") or e.get("playlist") or "").strip()
        if t:
            title = t
            break
    items: list[dict] = []
    seen: set[str] = set()
    for i, e in enumerate(entries):
        u = str(e.get("webpage_url") or e.get("url") or "").strip()
        if not u:
            continue
        if not u.startswith(("http://", "https://")):
            u = urljoin(url, u)
        if not u.startswith(("http://", "https://")) or u in seen:
            continue
        seen.add(u)
        label = str(e.get("title") or "").strip()[:LABEL_MAX] or f"第{i + 1}集"
        items.append({"url": u, "label": label})
    return items, title


# ---------------- 路2-L1：静态抓取 ----------------

async def _fetch_static(url: str, timeout: float = 5.0) -> str:
    """httpx 抓 HTML（失败返回 ""，属探测语义）。"""
    from downloadkit.generic_video import DEFAULT_UA

    try:
        import httpx
        headers = {
            "User-Agent": DEFAULT_UA,
            "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
        }
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=True, headers=headers
        ) as c:
            r = await c.get(url)
            if r.status_code >= 400:
                return ""
            return r.text[:600_000]
    except Exception as e:  # noqa: BLE001
        logger.debug(f"[Episodes] L1 抓取失败 {url[:80]}: {e}")
        return ""


# ---------------- 总入口：三级回退 ----------------

async def expand_episodes(
    url: str,
    *,
    timeout: float = 60.0,
    try_ytdlp: bool = True,
    use_browser: bool = True,
) -> dict[str, Any]:
    """选集展开三级回退（§4.6.3）。

    Args:
        timeout: 整体预算上限（主要约束 L2 段）
        try_ytdlp: 是否走路1（generic 影视站应传 False，省 20s 白跑）
        use_browser: 是否允许路2-L2 浏览器 DOM（单测关掉）

    Returns:
        {"url", "method": "ytdlp"|"static"|"browser"|"none",
         "title", "count", "groups", "error", "elapsed"}
    """
    t0 = time.monotonic()

    def _finish(method: str, title: str, data: dict, error: str = "") -> dict:
        return {
            "url": url, "method": method, "title": title,
            "count": data.get("count", 0), "groups": data.get("groups", []),
            "error": error,
            "elapsed": round(time.monotonic() - t0, 1),
        }

    # 路1：yt-dlp 原生 playlist
    if try_ytdlp:
        items, ytdlp_title = await _expand_ytdlp(url)
        if len(items) >= MIN_GROUP:
            return _finish("ytdlp", ytdlp_title, {
                "count": len(items),
                "groups": [{"template": "yt-dlp", "count": len(items), "items": items}],
            })

    # 路2-L1：静态抓 HTML → 模板聚类
    html = await _fetch_static(url)
    if html:
        data = extract_from_html(html, url)
        if data["count"] >= MIN_GROUP:
            from downloadkit.generic_video import _extract_page_title
            return _finish("static", _extract_page_title(html), data)

    # 路2-L2：浏览器过 WAF 取 DOM（与嗅探共用单例锁，串行排队）
    html2 = ""
    doc_title = ""
    if use_browser:
        from downloadkit.sniffer import fetch_page_html
        html2, doc_title = await fetch_page_html(
            url, timeout=min(30.0, max(15.0, timeout))
        )
        if html2:
            data = extract_from_html(html2, url)
            if data["count"] >= MIN_GROUP:
                from downloadkit.generic_video import _extract_page_title
                # document.title（渲染后，SPA 动态改名也能拿到）优先于源码提取
                title = doc_title.strip() or _extract_page_title(html2)
                return _finish("browser", title, data)

    # 路3：回退单集。两层都没拿到页面 → 报「打不开」而非「无选集」，
    # 免得把站点不可达/需登录误报成页面没有选集
    if html or html2:
        err = "未识别到选集（已回退为单集下载）"
    else:
        err = "页面打开失败（网络不通/站点异常/需登录），已回退为单集下载"
    return _finish("none", "", {"count": 0, "groups": []}, err)
