#!/usr/bin/env python3
"""_fetch_content_browser 的图文/视频分流回归

覆盖 2026-10-14 加的 resolve_note 分流逻辑（纯逻辑，不启动浏览器）：
  1. 图文判对 → 走 resolve_note，有实况对则 ANIMATED
  2. 只有图无实况 → IMAGE
  3. 落地页被重定向回 /video/（调用方类型判错）→ 改走 resolve_stream
  4. resolve_note 返回空结果 → 视为失败返回 None，不得谎报"解析成功"
  5. 普通视频链接 → 完全不碰 resolve_note
"""

import asyncio
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import downloadkit.douyin as douyin
from downloadkit.douyin import ContentType
import downloadkit.douyin_browser as douyin_browser


NOTE_WITH_MOTION = {
    "aweme_id": "123", "title": "t", "author": "a", "author_sec_uid": "s",
    "images": [f"https://p{i}.jpg" for i in range(3)],
    "motion_pairs": [{"img": "https://p0.jpg", "video": "https://v0.mp4"}],
    "publish_date": "",
}
NOTE_IMAGE_ONLY = {**NOTE_WITH_MOTION, "motion_pairs": []}
NOTE_EMPTY = {
    "aweme_id": "123", "title": "", "author": "", "author_sec_uid": "",
    "images": [], "motion_pairs": [], "publish_date": "",
}
NOTE_TYPE_MISMATCH = {"type_mismatch": True, "aweme_id": "123"}


class FakeBrowser:
    """只实现分流会碰到的两个方法，记录调用顺序。"""

    def __init__(self, note_result):
        self.note_result = note_result
        self.calls: list[str] = []

    async def resolve_note(self, aweme_id):
        self.calls.append("note")
        return self.note_result

    async def resolve_stream(self, aweme_id):
        self.calls.append("stream")
        return types.SimpleNamespace(
            aweme_id=aweme_id, title="标题", author="作者", cover="",
            stream_url="https://x/video.mp4", size=1000,
            author_sec_uid="MS4wLjAB", publish_date="2026-01-01",
        )


async def _run(input_text: str, note_result):
    """打桩 get_browser / parse_video_url / resolve_short_url 后跑一次分流。"""
    fake = FakeBrowser(note_result)

    async def fake_get_browser():
        return fake

    # 这两个是函数体内 `from .douyin_browser import ...` 取的，
    # 所以要替换 douyin_browser 模块上的属性而不是 douyin 的
    async def fake_parse_video_url(text, browser=None):
        return "123"

    async def fake_resolve_short_url(url, retries=3, browser=None):
        return url  # 直接把输入 URL 当最终 URL，让 is_note 能看到 /note/ /video/

    saved = (douyin.get_browser, douyin_browser.parse_video_url,
             douyin_browser.resolve_short_url)
    douyin.get_browser = fake_get_browser
    douyin_browser.parse_video_url = fake_parse_video_url
    douyin_browser.resolve_short_url = fake_resolve_short_url
    try:
        content = await douyin._fetch_content_browser(input_text)
    finally:
        (douyin.get_browser, douyin_browser.parse_video_url,
         douyin_browser.resolve_short_url) = saved
    return content, fake.calls


class TestNoteRouting:
    def test_note_with_motion_is_animated(self):
        content, calls = asyncio.run(
            _run("https://www.douyin.com/note/123", NOTE_WITH_MOTION))
        assert calls == ["note"]
        assert content.content_type == ContentType.ANIMATED
        assert len(content.images) == 3
        assert len(content.motion_photo_pairs) == 1

    def test_note_without_motion_is_image(self):
        content, calls = asyncio.run(
            _run("https://www.douyin.com/slides/123", NOTE_IMAGE_ONLY))
        assert calls == ["note"]
        assert content.content_type == ContentType.IMAGE
        assert len(content.images) == 3
        assert content.motion_photo_pairs == []

    def test_landing_page_mismatch_falls_back_to_video(self):
        """类型判错时不能当图文解析，要改走 resolve_stream。"""
        content, calls = asyncio.run(
            _run("https://www.douyin.com/note/123", NOTE_TYPE_MISMATCH))
        assert calls == ["note", "stream"]
        assert content.content_type == ContentType.VIDEO
        assert content.video_url == "https://x/video.mp4"

    def test_empty_note_result_is_failure(self):
        """0 图 0 实况不能谎报成功，必须返回 None 交给旧后端兜底。"""
        content, calls = asyncio.run(
            _run("https://www.douyin.com/note/123", NOTE_EMPTY))
        assert calls == ["note"]
        assert content is None

    def test_video_link_never_touches_resolve_note(self):
        content, calls = asyncio.run(
            _run("https://www.douyin.com/video/123", NOTE_WITH_MOTION))
        assert calls == ["stream"]
        assert content.content_type == ContentType.VIDEO

    def test_no_self_import_in_douyin(self):
        """MediaItem/MotionPhotoPair 就定义在 douyin 模块内，不该自导入。"""
        src = (Path(douyin.__file__)).read_text(encoding="utf-8")
        assert "from .douyin import MediaItem" not in src


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
