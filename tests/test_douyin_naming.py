# -*- coding: utf-8 -*-
"""P4-2 抖音文件命名：「标题 2026-09-27.mp4」（标题在前、发布日期在后）

用户拍板（2026-09-27）：日期用**视频发布日期**，从页面「发布时间」
（浏览器后端 DOM）/ 详情接口 `create_time`（旧接口路径）取；
拿不到就回落旧命名 `douyin_<作品ID>`，不硬造日期。

守住五条：
  1. 有标题有日期 → `标题 YYYY-MM-DD`；缺日期/缺标题 → `douyin_<id>`。
  2. 标题非法字符清洗 + 长度封顶（Windows 路径 260 上限）。
  3. create_time 秒/毫秒/坏值都能处理，按 UTC+8 落日期（与页面显示一致）。
  4. 旧命名文件视为已存在：切新命名后重下不许出第二份。
  5. 四个命名点都走 build_download_base，不允许散落的 f"douyin_…" 拼接。
"""

from dataclasses import fields
from pathlib import Path

import pytest

from downloadkit import douyin
from downloadkit.douyin import (
    DouyinContent,
    OptimizedOfficialParser,
    _existing_target,
    _fmt_publish_date,
    build_download_base,
)

TS = 1742182249          # 2025-03-17 06:10:49 +08:00
DATE = "2025-03-17"


# ---------------- 日期换算 ----------------


def test_fmt_publish_date_seconds():
    assert _fmt_publish_date(TS) == DATE


def test_fmt_publish_date_millis():
    assert _fmt_publish_date(TS * 1000) == DATE, "毫秒时间戳要能识别"


def test_fmt_publish_date_bad_values():
    for bad in (None, "", "abc", 0, -5, 10 ** 15, object()):
        assert _fmt_publish_date(bad) == "", f"{bad!r} 不该产出日期"


# ---------------- 命名主干 ----------------


def _content(**kw):
    kw.setdefault("item_id", "7689023840848006451")
    return DouyinContent(**kw)


def test_base_title_plus_date():
    c = _content(title="今天好开心", publish_date=DATE)
    assert build_download_base(c) == f"今天好开心 {DATE}"


def test_base_falls_back_without_date():
    """取不到发布日期 → 回落旧命名，不硬造"""
    c = _content(title="今天好开心", publish_date="")
    assert build_download_base(c) == f"douyin_{c.item_id}"


def test_base_falls_back_without_title():
    c = _content(title="", publish_date=DATE)
    assert build_download_base(c) == f"douyin_{c.item_id}"


def test_base_sanitizes_illegal_chars():
    c = _content(title='标题/不能有:这些*?"<>|字符', publish_date=DATE)
    base = build_download_base(c)
    assert not set('\\/:*?"<>|') & set(base), f"非法字符没清干净: {base}"
    assert base.endswith(DATE)


def test_base_caps_long_title():
    """300 字标题 + 日期 + 目录前缀要留在 Windows 260 路径内"""
    c = _content(title="标" * 300, publish_date=DATE)
    base = build_download_base(c)
    assert len(base) <= 120 + 1 + len(DATE)


# ---------------- 旧命名文件去重 ----------------


def test_existing_target_prefers_new_then_legacy(tmp_path):
    legacy = tmp_path / "douyin_9.mp4"
    legacy.write_bytes(b"x")
    new = tmp_path / f"标题 {DATE}.mp4"

    assert _existing_target([new, legacy]) == legacy, "只有旧命名文件时要命中旧的"
    new.write_bytes(b"y")
    assert _existing_target([new, legacy]) == new, "新命名在前优先"


def test_existing_target_none(tmp_path):
    assert _existing_target([tmp_path / "a.mp4", tmp_path / "b.mp4"]) is None
    assert _existing_target([]) is None


# ---------------- 旧接口路径取 create_time ----------------


def test_parse_aweme_detail_publish_date():
    parser = OptimizedOfficialParser()
    aweme = {
        "desc": "测试标题",
        "create_time": TS,
        "images": [{"url_list": ["https://x/1.jpg"]}],
    }
    content = parser._parse_aweme_detail(aweme, "123")
    assert content is not None
    assert content.publish_date == DATE
    assert content.title == "测试标题"


def test_parse_data_dict_publish_date():
    parser = OptimizedOfficialParser()
    data = {
        "videoInfoRes": {"item_list": [{
            "desc": "视频标题",
            "create_time": TS,
            "video": {"play_addr": {"url_list": ["https://x/playwm/v"]}},
        }]}
    }
    content = parser._parse_data_dict(data, "456")
    assert content is not None
    assert content.publish_date == DATE


def test_parse_without_create_time_keeps_empty():
    parser = OptimizedOfficialParser()
    aweme = {"desc": "没日期", "images": [{"url_list": ["https://x/1.jpg"]}]}
    content = parser._parse_aweme_detail(aweme, "789")
    assert content.publish_date == "", "缺 create_time 不许硬造日期"


# ---------------- 数据结构 / 接线 ----------------


def test_video_item_has_publish_date():
    from downloadkit.douyin_browser import VideoItem
    names = [f.name for f in fields(VideoItem)]
    assert "publish_date" in names


def test_browser_content_passes_publish_date():
    """浏览器后端 fetch_content 要把 VideoItem.publish_date 带进 DouyinContent"""
    src = (Path(douyin.__file__)).read_text(encoding="utf-8")
    assert 'publish_date=item.publish_date or ""' in src


def test_four_naming_sites_use_builder():
    src = Path(douyin.__file__).read_text(encoding="utf-8")
    assert src.count("build_download_base(content)") >= 4, \
        "浏览器视频/旧接口视频/实况/图文四个命名点都要走统一助手"
    # 散落的旧命名拼接不许再当「下载目标名」用；
    # 仅允许以 _existing_target 去重候选的形式出现 4 处（新命名兜底旧文件）
    for marker in ('filename = f"douyin_{content.item_id}',
                   'filepath = video_dir / f"douyin_',
                   'img_path = animated_dir / f"douyin_'):
        assert marker not in src, f"残留旧命名拼接: {marker}"
    assert src.count("douyin_{content.item_id}") == 5, \
        "应只剩 5 处：build_download_base 回落 1 处 + 4 处去重候选（视频/图文/实况/浏览器视频）"


def test_browser_meta_extracts_publish_time():
    from downloadkit import douyin_browser
    src = Path(douyin_browser.__file__).read_text(encoding="utf-8")
    assert "发布时间" in src, "页面元数据提取没抓发布日期"
    assert "pubDate" in src


def test_download_content_resolves_rename_strategy():
    """已存在预检（含旧命名兜底）要用真实生效值，不能一路传 None 让各处自己猜"""
    src = Path(douyin.__file__).read_text(encoding="utf-8")
    assert "rename_strategy = cfg.get('general', {}).get('rename_strategy', 'skip')" in src
