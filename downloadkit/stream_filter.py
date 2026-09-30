# -*- coding: utf-8 -*-
"""选流与去重（计划书 §4.3 / §5.1，P5 独立模块）。

规则：
  · 主/子播放列表区分：playlist.m3u8（主）与 640x360/video.m3u8（子）并存
    → 只保留主列表（yt-dlp 处理主列表会自动选清晰度）
  · 多清晰度不在此筛：交给 yt-dlp（-f bv*+ba/b + --merge-output-format mp4）
  · 排除干扰流：trailer/preview/ad/commerc/vod_ad/advert/blank 占位
  · 归一化去重：去 fragment + query 签名参数（expires/sign/ts…）后按
    host+path 去重，保留首见完整 URL
  · 跨页去重（R10）：同一 m3u8 在多书签页出现 → 只下载一次（server
    batch-download 入队前用 stream_key 过滤）

原为 sniffer.py 内纯函数（P2），P5 按 §5.1 抽出独立模块；
sniffer / generic_video / test_sniffer 经 sniffer 的 re-export 兼容。
"""
from __future__ import annotations

import re

# 流地址（m3u8 / mpd / mp4），结尾排除引号与括号
STREAM_RE = re.compile(
    r'https?://[^\s"\'<>\\)]+?\.(?:m3u8|mpd|mp4)(?:[^\s"\'<>\\)]*)?', re.I
)
# 干扰流排除（计划书 §4.3：trailer/preview/ad/commerc/vod_ad/advert；
# 实测补充：plyr 播放器的空白占位 blank.mp4）
AD_RE = re.compile(
    r"trailer|preview|advert|commerc|vod[_-]?ad|/ad[s]?[./_?#-]|\bblank\b", re.I
)
# 子播放列表特征：路径含分辨率段（如 /640x360/video.m3u8）
SUB_M3U8_RE = re.compile(r"/\d{2,4}x\d{2,4}/", re.I)


def extract_stream_urls(text: str) -> list[str]:
    """从任意文本（URL/响应体/HTML）挖流地址，排除干扰流，保序去重。"""
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for m in STREAM_RE.finditer(str(text)):
        u = m.group(0).rstrip("\\").rstrip(",;]")
        if AD_RE.search(u):
            continue
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def stream_key(url: str) -> str:
    """归一化去重 key：去 fragment → host+path 小写（query 签名参数不参与）。

    同一流在不同页/不同时刻的 URL 会换 expires/sign/ts 等参数，
    host+path 不变即同一流（§4.3「去重」行）。
    """
    base = str(url or "").split("#", 1)[0]
    m = re.match(r"(https?://[^/?#]+)(/[^?#]*)?", base, re.I)
    if m:
        return m.group(1).lower() + (m.group(2) or "/").lower()
    return base.lower()


def dedupe_streams(urls: list[str]) -> list[str]:
    """去重：同 host+path 视为同一流，保留首见完整 URL。"""
    out: list[str] = []
    seen: set[str] = set()
    for u in urls:
        k = stream_key(u)
        if k in seen:
            continue
        seen.add(k)
        out.append(u)
    return out


def prefer_main_streams(urls: list[str]) -> list[str]:
    """主/子播放列表区分（§4.3）：主列表与分辨率子列表并存时只保留主列表。"""
    if not urls:
        return []
    has_main = any(".m3u8" in u.lower() and not SUB_M3U8_RE.search(u) for u in urls)
    has_sub = any(".m3u8" in u.lower() and SUB_M3U8_RE.search(u) for u in urls)
    if has_main and has_sub:
        return [u for u in urls
                if not (".m3u8" in u.lower() and SUB_M3U8_RE.search(u))]
    return urls
