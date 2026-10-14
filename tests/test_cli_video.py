#!/usr/bin/env python3
"""CLI 视频解析/下载（parse / video 命令）与共享层 video_service 回归

2026-10-14 新增 CLI 的 parse / video 命令时，把 server.py 本地的
detect_platform 搬到 downloadkit/video_service.py 统一，并新增
parse_url / download_parsed 两个平台分发入口。本文件覆盖：

  - detect_platform 的平台分发（含 generic 兜底与非 http 拒绝）
  - parse_url 各平台分支的输出结构（对齐 /api/video/parse 契约）
  - download_parsed 各平台分支的落点与参数透传
  - CLI 选集选择 _pick_indexes
  - server 与 CLI 共用同一个 detect_platform（防两份实现漂移）
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import downloadkit.video_service as vs
from downloadkit.douyin import ContentType
from downloadkit.video_service import (
    detect_platform, parse_url, download_parsed, public_info,
)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- detect


class TestDetectPlatform:
    @pytest.mark.parametrize("url,expect", [
        ("https://www.douyin.com/video/7347336111154302217", "douyin"),
        ("https://v.douyin.com/ZiwroODm_J0/", "douyin"),
        ("https://www.tiktok.com/@a/video/1", "douyin"),
        ("https://www.bilibili.com/video/BV1xx411c7mD", "bilibili"),
        ("https://b23.tv/abcdef", "bilibili"),
        ("https://www.youtube.com/watch?v=abc", "youtube"),
        ("https://youtu.be/abc", "youtube"),
        ("https://www.xiaohongshu.com/explore/abc", "xiaohongshu"),
        ("https://xhslink.com/abc", "xiaohongshu"),
        # generic 兜底：任何 http(s) 链接
        ("https://example.com/play/1", "generic"),
        ("http://192.168.1.5:8080/video.m3u8", "generic"),
        ("https://cdn.example.com/v.mp4?a=1", "generic"),
    ])
    def test_dispatch(self, url, expect):
        assert detect_platform(url) == expect

    @pytest.mark.parametrize("bad", ["", "not a url", "ftp://x.com/a",
                                     "magnet:?xt=abc", "file:///C:/a.mp4"])
    def test_reject_non_http(self, bad):
        assert detect_platform(bad) is None

    def test_server_shares_the_same_function(self):
        """server.py 的 detect_platform 必须是同一个函数对象（防漂移）。"""
        import server
        assert server.detect_platform is detect_platform, (
            "server.py 应从 downloadkit.video_service import detect_platform")


# ---------------------------------------------------------------- parse


def _patch(monkeypatch, name, value):
    monkeypatch.setattr(vs, name, value)


class TestParseDouyin:
    def _video_content(self):
        return SimpleNamespace(
            title="测试视频", author="作者", cover="http://c/1.jpg",
            item_id="123", content_type=ContentType.VIDEO,
            video_url="http://v/1.mp4", video_url_watermark=None,
            images=[], motion_photo_pairs=[],
        )

    def test_video_branch(self, monkeypatch):
        c = self._video_content()
        _patch(monkeypatch, "douyin_fetch_content", lambda url: _coro(c))
        info = run(parse_url("https://v.douyin.com/x/"))
        assert info["platform"] == "douyin"
        assert info["content_type"] == "video"
        assert info["video_url"] == "http://v/1.mp4"
        assert info["title"] == "测试视频"
        assert info["raw"] is c

    def test_animated_pairs(self, monkeypatch):
        """实况照片：images 每项带 video_url，video_urls 汇总。"""
        pair = SimpleNamespace(
            image=SimpleNamespace(url="http://i/1.jpg"),
            video=SimpleNamespace(url="http://i/1.mp4"))
        c = SimpleNamespace(
            title="实况", author="a", cover="", item_id="1",
            content_type=ContentType.ANIMATED, video_url=None,
            video_url_watermark=None, images=[],
            motion_photo_pairs=[pair])
        _patch(monkeypatch, "douyin_fetch_content", lambda url: _coro(c))
        info = run(parse_url("https://v.douyin.com/y/"))
        assert info["content_type"] == "animated"
        assert info["images"] == [{"url": "http://i/1.jpg",
                                   "video_url": "http://i/1.mp4"}]
        assert info["video_urls"] == ["http://i/1.mp4"]
        # video_url 回落到第一个实况视频
        assert info["video_url"] == "http://i/1.mp4"

    def test_image_branch(self, monkeypatch):
        c = SimpleNamespace(
            title="图文", author="a", cover="", item_id="2",
            content_type=ContentType.IMAGE, video_url=None,
            video_url_watermark=None,
            images=[SimpleNamespace(url="http://i/1.jpg"),
                    SimpleNamespace(url="http://i/2.jpg")],
            motion_photo_pairs=[])
        _patch(monkeypatch, "douyin_fetch_content", lambda url: _coro(c))
        info = run(parse_url("https://v.douyin.com/z/"))
        assert info["content_type"] == "image"
        assert info["images"] == [{"url": "http://i/1.jpg"},
                                  {"url": "http://i/2.jpg"}]
        assert info["video_url"] is None


class TestParseOtherPlatforms:
    def test_bilibili(self, monkeypatch):
        v = SimpleNamespace(title="B站视频", author="up", cover="c",
                            duration=125, quality="1080P")
        _patch(monkeypatch, "parse_bilibili", lambda url: _coro(v))
        info = run(parse_url("https://www.bilibili.com/video/BV1x"))
        assert info["platform"] == "bilibili"
        assert info["content_type"] == "video"
        assert info["duration"] == 125
        assert info["quality"] == "1080P"
        assert info["raw"] is v

    def test_youtube(self, monkeypatch):
        v = SimpleNamespace(title="YT", author="ch", cover="",
                            duration=3661, is_playlist=False,
                            entry_count=0, webpage_url="", formats=[],
                            page_title="", ext="mp4")
        _patch(monkeypatch, "parse_youtube", lambda url: _coro(v))
        info = run(parse_url("https://youtu.be/a"))
        assert info["platform"] == "youtube"
        assert info["duration"] == 3661

    def test_xiaohongshu_video(self, monkeypatch):
        c = SimpleNamespace(title="XHS", author="u", cover="",
                            content_type=ContentType.VIDEO,
                            video_url="http://x/1.mp4", images=[])
        _patch(monkeypatch, "parse_xiaohongshu", lambda url: _coro(c))
        info = run(parse_url("https://www.xiaohongshu.com/explore/a"))
        assert info["platform"] == "xiaohongshu"
        assert info["content_type"] == "video"
        assert info["video_url"] == "http://x/1.mp4"

    def test_xiaohongshu_image(self, monkeypatch):
        c = SimpleNamespace(title="XHS图", author="u", cover="",
                            content_type=ContentType.IMAGE, video_url=None,
                            images=["http://x/1.jpg", "http://x/2.jpg"])
        _patch(monkeypatch, "parse_xiaohongshu", lambda url: _coro(c))
        info = run(parse_url("https://xhslink.com/a"))
        assert info["content_type"] == "image"
        assert info["images"] == [{"url": "http://x/1.jpg"},
                                  {"url": "http://x/2.jpg"}]


class TestParseGeneric:
    def _video(self, **kw):
        base = dict(title="网页视频", author="", cover="http://c/1.jpg",
                    duration=60, is_playlist=False, entry_count=0,
                    webpage_url="http://page/", page_title="页面标题",
                    ext="mp4", formats=[{"format_id": "hls-720",
                                         "quality": "720p", "ext": "mp4",
                                         "height": 720, "filesize": None}])
        base.update(kw)
        return SimpleNamespace(**base)

    def test_direct_mp4_link(self, monkeypatch):
        v = self._video()
        _patch(monkeypatch, "parse_generic",
               lambda url, referer=None: _coro(v))
        info = run(parse_url("http://cdn.example.com/a.mp4"))
        assert info["platform"] == "generic"
        # mp4 直链才能直接播放 → video_url 给出
        assert info["video_url"] == "http://cdn.example.com/a.mp4"
        assert info["formats"][0]["quality"] == "720p"

    def test_m3u8_link_no_video_url(self, monkeypatch):
        """m3u8 不能被 <video> 直接播，不给 video_url（交给下载流程）。"""
        v = self._video(ext="m3u8")
        _patch(monkeypatch, "parse_generic",
               lambda url, referer=None: _coro(v))
        info = run(parse_url("http://cdn.example.com/a.m3u8"))
        assert "video_url" not in info

    def test_suggested_name_uses_hint(self, monkeypatch):
        v = self._video()
        _patch(monkeypatch, "parse_generic",
               lambda url, referer=None: _coro(v))
        info = run(parse_url("http://cdn.example.com/a.mp4",
                             title_hint="某某剧-第03集"))
        assert "某某剧" in info["suggested_name"]
        assert "第03集" in info["suggested_name"]

    def test_reject_non_http(self):
        with pytest.raises(ValueError):
            run(parse_url("not a url"))


class TestPublicInfo:
    def test_strips_raw_only(self, monkeypatch):
        c = SimpleNamespace(title="t", author="", cover="", item_id="1",
                            content_type=ContentType.VIDEO,
                            video_url="http://v/1.mp4",
                            video_url_watermark=None, images=[],
                            motion_photo_pairs=[])
        _patch(monkeypatch, "douyin_fetch_content", lambda url: _coro(c))
        info = run(parse_url("https://v.douyin.com/x/"))
        pub = public_info(info)
        assert "raw" not in pub
        assert pub["title"] == "t"
        # 确保可 JSON 序列化
        import json
        json.dumps(pub, ensure_ascii=False)


# ---------------------------------------------------------------- download


class TestDownloadParsed:
    def test_douyin_passes_out_dir_through(self, monkeypatch):
        """抖音：out_dir 原样透传（None=配置分类目录）。"""
        got = {}

        async def fake_dl(content, out_dir, **kw):
            got["out"] = out_dir
            got["merge"] = kw.get("merge_motion_photo")
            return [Path("x.mp4")]

        _patch(monkeypatch, "douyin_download_content", fake_dl)
        c = SimpleNamespace()
        run(download_parsed({"platform": "douyin", "url": "u", "raw": c},
                            out_dir=None, merge_motion_photo=False))
        assert got["out"] is None
        assert got["merge"] is False

    def test_out_dir_none_uses_config_videos(self, monkeypatch, tmp_path):
        """非抖音平台：out_dir=None → get_download_subdir('videos')。"""
        got = {}

        async def fake_dl(video, out_dir, **kw):
            got["out"] = out_dir
            return Path("b.mp4")

        _patch(monkeypatch, "parse_bilibili",
               lambda url: _coro(SimpleNamespace()))
        _patch(monkeypatch, "download_bilibili_video", fake_dl)
        _patch(monkeypatch, "get_download_subdir",
               lambda cat: tmp_path / cat)

        run(download_parsed({"platform": "bilibili", "url": "u", "raw": None}))
        assert got["out"] == tmp_path / "videos"

    def test_out_dir_specified_used_directly(self, monkeypatch, tmp_path):
        got = {}

        async def fake_dl(video, out_dir, quality="best", **kw):
            got["out"] = out_dir
            got["quality"] = quality
            return Path("y.mp4")

        _patch(monkeypatch, "parse_youtube", lambda url: _coro(SimpleNamespace()))
        _patch(monkeypatch, "download_youtube_video", fake_dl)
        run(download_parsed({"platform": "youtube", "url": "u", "raw": None},
                            out_dir=tmp_path, quality="720"))
        assert got["out"] == tmp_path
        assert got["quality"] == "720"  # 画质也要透传到下载器

    def test_quality_forwarded(self, monkeypatch, tmp_path):
        got = {}

        async def fake_dl(video, out_dir, quality, **kw):
            got["quality"] = quality
            return Path("g.mp4")

        _patch(monkeypatch, "parse_generic",
               lambda url, referer=None: _coro(SimpleNamespace()))
        _patch(monkeypatch, "download_generic_video", fake_dl)
        run(download_parsed({"platform": "generic", "url": "http://x/a.mp4",
                             "raw": None},
                            out_dir=tmp_path, quality="720",
                            name_hint="hint", referer="http://src/"))
        assert got["quality"] == "720"

    def test_xhs_defaults_to_root_dir(self, monkeypatch, tmp_path):
        """小红书默认落根目录（可能同时产图与视频），不是 videos/。"""
        got = {}

        async def fake_dl(content, out_dir, **kw):
            got["out"] = out_dir
            return [Path("x.jpg")]

        _patch(monkeypatch, "parse_xiaohongshu", lambda url: _coro(SimpleNamespace()))
        _patch(monkeypatch, "download_xhs_content", fake_dl)
        _patch(monkeypatch, "get_download_dir", lambda: tmp_path)
        run(download_parsed({"platform": "xiaohongshu", "url": "u",
                             "raw": None}))
        assert got["out"] == tmp_path

    def test_raw_none_triggers_reparse(self, monkeypatch):
        """raw 缺失时按 url 重新解析（批量/断点场景）。"""
        called = {}

        async def fake_parse(url):
            called["url"] = url
            return SimpleNamespace()

        async def fake_dl(video, out_dir, **kw):
            return Path("b.mp4")

        _patch(monkeypatch, "parse_bilibili", fake_parse)
        _patch(monkeypatch, "download_bilibili_video", fake_dl)
        run(download_parsed({"platform": "bilibili", "url": "http://b/1",
                             "raw": None}))
        assert called["url"] == "http://b/1"

    def test_unknown_platform_raises(self):
        with pytest.raises(ValueError):
            run(download_parsed({"platform": "mars", "url": "u", "raw": None}))


# ---------------------------------------------------------------- CLI 选集


class TestPickIndexes:
    def test_all(self):
        from downloadkit.cli import _pick_indexes
        assert _pick_indexes("a", 3) == [0, 1, 2]
        assert _pick_indexes("A", 2) == [0, 1]

    def test_single_and_list(self):
        from downloadkit.cli import _pick_indexes
        assert _pick_indexes("3", 5) == [2]
        assert _pick_indexes("1,3", 5) == [0, 2]

    def test_range(self):
        from downloadkit.cli import _pick_indexes
        assert _pick_indexes("1-3", 5) == [0, 1, 2]
        assert _pick_indexes("2-4", 5) == [1, 2, 3]

    def test_dedup_and_order(self):
        from downloadkit.cli import _pick_indexes
        assert _pick_indexes("3,1,3,2", 5) == [0, 1, 2]

    def test_out_of_range_and_garbage(self):
        from downloadkit.cli import _pick_indexes
        assert _pick_indexes("99", 3) == []
        assert _pick_indexes("0", 3) == []          # 1 基，0 非法
        assert _pick_indexes("x", 3) == []
        assert _pick_indexes("", 3) == []
        assert _pick_indexes("1-99", 3) == [0, 1, 2]  # 范围截断到 n

    def test_invalid_range_ignored(self):
        from downloadkit.cli import _pick_indexes
        assert _pick_indexes("3-1", 5) == []       # 反向范围无结果
        assert _pick_indexes("a-b", 5) == []


def _coro(v):
    """把普通值包成协程，方便 mock 平台解析器。"""
    async def _inner(url=None, **kw):
        return v
    return _inner()


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
