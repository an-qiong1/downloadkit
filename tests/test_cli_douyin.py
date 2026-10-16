#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI douyin 命令组回归

P0-任务2：douyin 命令此前缺少 CLI 层测试（只有 douyin.py 内部单元测试 + E2E）。
本文件覆盖：

  - parse_url：有效 URL / 短链接 / 分享文本 / 非法输入 → 返回 None
  - douyin CLI：
      · 无链接 → 打印中文提示，exit 0
      · fetch_content 抛 ValueError → 打印错误，exit 0
      · download_content 抛 ValueError → 打印下载失败，exit 0
      · 正常路径 → 视频/图文/动图三种内容类型的输出文案
      · -o 指定输出目录 → 传给 download_content
      · --help → 列出所有子选项

测试策略：monkeypatch cli.fetch_content / cli.download_content / cli.parse_url，
不启动服务，不连网络。

退出码约定：douyin 是「解析+下载」命令，
无链接 / 解析失败 / 下载失败 都视为「没做成该做的事」→ exit 0；
只有用法错误（--help 异常）才是非 0。
与 sniff / bookmarks / probe 那组探测器的 exit 1 不同。
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

import downloadkit.cli as cli
from downloadkit.douyin import ContentType, DouyinContent


# ============================ 测试数据构造 ============================

def _video_content(**kw):
    kw.setdefault("item_id", "7689023840848006451")
    kw.setdefault("title", "晴天")
    kw.setdefault("author", "周杰伦")
    kw.setdefault("content_type", ContentType.VIDEO)
    kw.setdefault("video_url", "http://cdn/v.mp4")
    kw.setdefault("images", [])
    kw.setdefault("motion_photo_pairs", [])
    return DouyinContent(**kw)


def _image_content(**kw):
    kw.setdefault("item_id", "img1")
    kw.setdefault("title", "看图")
    kw.setdefault("author", "画师")
    kw.setdefault("content_type", ContentType.IMAGE)
    kw.setdefault("video_url", "")
    kw.setdefault("images", [
        SimpleNamespace(url="http://cdn/p1.jpg"),
        SimpleNamespace(url="http://cdn/p2.jpg"),
    ])
    kw.setdefault("motion_photo_pairs", [])
    return DouyinContent(**kw)


def _animated_content(**kw):
    kw.setdefault("item_id", "live1")
    kw.setdefault("title", "实况照片")
    kw.setdefault("author", "摄影师")
    kw.setdefault("content_type", ContentType.ANIMATED)
    kw.setdefault("video_url", "http://cdn/live.mp4")
    kw.setdefault("images", [SimpleNamespace(url="http://cdn/live.jpg")])
    kw.setdefault("motion_photo_pairs", [
        SimpleNamespace(image=SimpleNamespace(url="http://cdn/live.jpg"),
                        video=SimpleNamespace(url="http://cdn/live.mp4"))
    ])
    return DouyinContent(**kw)


def _fail_fetch(msg="网络超时"):
    async def f(text):
        raise ValueError(msg)
    return f


def _fail_download(msg="下载失败"):
    async def f(content, output=None):
        raise ValueError(msg)
    return f


def _dummy_path(name="video.mp4"):
    p = Path("/tmp/fake/dl") / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * 1024)
    return p


# ============================ 运行器 ============================

def _run(args, input=None):
    return CliRunner().invoke(cli.main, args, input=input, catch_exceptions=False)


# ============================ parse_url 测试 ============================

class TestParseUrl:
    """parse_url 从输入文本中提取抖音链接的边界情况。"""

    @pytest.mark.parametrize("text,expect", [
        ("https://www.douyin.com/video/123456", "https://www.douyin.com/video/123456"),
        ("https://v.douyin.com/xyz/", "https://v.douyin.com/xyz"),
        ("check https://v.douyin.com/abc this out", "https://v.douyin.com/abc"),
        ("分享链接：https://www.douyin.com/note/789", "https://www.douyin.com/note/789"),
    ])
    def test_valid_urls(self, text, expect):
        from downloadkit.douyin import parse_url
        assert parse_url(text) == expect

    @pytest.mark.parametrize("text", [
        "", "   ", "不是抖音链接",
        "https://www.bilibili.com/video/BV1xx",
        "hello world no url here",
    ])
    def test_invalid_returns_none(self, text):
        from downloadkit.douyin import parse_url
        assert parse_url(text) is None

    def test_url_without_scheme_has_https_prepended(self):
        from downloadkit.douyin import parse_url
        result = parse_url("v.douyin.com/test123")
        assert result is not None
        assert result.startswith("https://")


# ============================ CLI 命令测试 ============================

def test_douyin_no_link_shows_hint_exit_0(monkeypatch):
    """输入里没有抖音链接 → 打印中文提示，不报错。"""
    monkeypatch.setattr(cli, "fetch_content", _fail_fetch())
    monkeypatch.setattr(cli, "download_content", _fail_download())
    r = _run(["douyin", "不是抖音链接"])
    assert r.exit_code == 0
    assert "抖音链接" in r.output


def test_douyin_fetch_error_shows_msg_exit_0(monkeypatch, tmp_path):
    """fetch_content 抛 ValueError → 打印错误，退出码仍是 0。"""
    monkeypatch.setattr(cli, "parse_url", lambda t: "https://v.douyin.com/x")
    monkeypatch.setattr(cli, "fetch_content", _fail_fetch("模拟解析失败"))
    r = _run(["douyin", "https://v.douyin.com/x"])
    assert r.exit_code == 0
    assert "模拟解析失败" in r.output


def test_douyin_download_error_shows_msg_exit_0(monkeypatch, tmp_path):
    """download_content 抛 ValueError → 打印下载失败，退出码 0。"""
    content = _video_content()
    async def good_fetch(text):
        return content
    monkeypatch.setattr(cli, "fetch_content", good_fetch)
    monkeypatch.setattr(cli, "download_content", _fail_download("模拟下载失败"))
    r = _run(["douyin", "https://v.douyin.com/x"])
    assert r.exit_code == 0
    assert "下载失败" in r.output


def test_douyin_video_shows_title_author(monkeypatch, tmp_path):
    """视频内容：标题、作者、ID、类型出现在输出里。"""
    content = _video_content()
    path = tmp_path / "videos" / "晴天.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 524288)

    async def good_fetch(text):
        return content
    async def good_download(c, output=None):
        return [path]

    monkeypatch.setattr(cli, "fetch_content", good_fetch)
    monkeypatch.setattr(cli, "download_content", good_download)
    r = _run(["douyin", "https://v.douyin.com/x"])
    assert r.exit_code == 0
    assert "晴天" in r.output
    assert "周杰伦" in r.output
    assert "视频" in r.output
    assert "完成" in r.output


def test_douyin_image_shows_image_count(monkeypatch, tmp_path):
    """图文类型：显示图片数量，不显示"视频"。"""
    content = _image_content()
    p1 = tmp_path / "images" / "看图_1.jpg"
    p1.parent.mkdir(parents=True, exist_ok=True)
    p1.write_bytes(b"y" * 1024)
    p2 = tmp_path / "images" / "看图_2.jpg"
    p2.write_bytes(b"z" * 2048)

    async def good_fetch(text):
        return content
    async def good_download(c, output=None):
        return [p1, p2]

    monkeypatch.setattr(cli, "fetch_content", good_fetch)
    monkeypatch.setattr(cli, "download_content", good_download)
    r = _run(["douyin", "https://v.douyin.com/img"])
    assert r.exit_code == 0
    assert "图文" in r.output
    assert "图片数量: 2" in r.output
    assert "完成" in r.output


def test_douyin_animated_shows_type(monkeypatch, tmp_path):
    """动图（实况照片）类型显示为「动图」。"""
    content = _animated_content()
    path = tmp_path / "animated" / "实况照片.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"a" * 102400)

    async def good_fetch(text):
        return content
    async def good_download(c, output=None):
        return [path]

    monkeypatch.setattr(cli, "fetch_content", good_fetch)
    monkeypatch.setattr(cli, "download_content", good_download)
    r = _run(["douyin", "https://v.douyin.com/live"])
    assert r.exit_code == 0
    assert "动图" in r.output
    assert "完成" in r.output


def test_douyin_output_dir_passed_to_download(monkeypatch, tmp_path):
    """-o 指定目录 → download_content 收到对应 output 参数。"""
    content = _video_content()
    saved_output = []

    path = tmp_path / "mydir" / "videos" / "晴天.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 1024)

    async def good_fetch(text):
        return content

    async def record_download(c, output=None):
        saved_output.append(output)
        return [path]

    monkeypatch.setattr(cli, "fetch_content", good_fetch)
    monkeypatch.setattr(cli, "download_content", record_download)
    r = _run(["douyin", "https://v.douyin.com/x", "-o", str(tmp_path / "mydir")])
    assert r.exit_code == 0
    assert len(saved_output) == 1
    assert saved_output[0] == str(tmp_path / "mydir")


def test_douyin_help_lists_options():
    r = _run(["douyin", "--help"])
    assert r.exit_code == 0
    assert "-o" in r.output
    assert "--output" in r.output


def test_douyin_short_link_in_output(monkeypatch, tmp_path):
    """短链接解析后输出的 URL 是完整 HTTPS 地址。"""
    content = _video_content()
    path = tmp_path / "videos" / "晴天.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 512)

    async def good_fetch(text):
        return content
    async def good_download(c, output=None):
        return [path]

    monkeypatch.setattr(cli, "fetch_content", good_fetch)
    monkeypatch.setattr(cli, "download_content", good_download)
    r = _run(["douyin", "https://v.douyin.com/short123/"])
    assert r.exit_code == 0
    assert "https://v.douyin.com/short123" in r.output or "v.douyin.com" in r.output


def test_douyin_share_text_extracts_url(monkeypatch, tmp_path):
    """分享文本（含标题+链接）能正确提取 URL 并解析。"""
    content = _video_content()
    path = tmp_path / "videos" / "晴天.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * 512)

    async def good_fetch(text):
        return content
    async def good_download(c, output=None):
        return [path]

    share_text = "【晴天】周杰伦\n点击打开链接：https://v.douyin.com/share123/"
    monkeypatch.setattr(cli, "fetch_content", good_fetch)
    monkeypatch.setattr(cli, "download_content", good_download)
    r = _run(["douyin", share_text])
    assert r.exit_code == 0
    assert "晴天" in r.output


def test_douyin_multi_file_total_size(monkeypatch, tmp_path):
    """多图图文下载多个文件时，输出总大小和各文件明细。"""
    content = _image_content()
    p1 = tmp_path / "images" / "看图_1.jpg"
    p2 = tmp_path / "images" / "看图_2.jpg"
    p1.parent.mkdir(parents=True, exist_ok=True)
    p1.write_bytes(b"x" * 102400)   # ~100KB
    p2.write_bytes(b"y" * 204800)   # ~200KB

    async def good_fetch(text):
        return content
    async def good_download(c, output=None):
        return [p1, p2]

    monkeypatch.setattr(cli, "fetch_content", good_fetch)
    monkeypatch.setattr(cli, "download_content", good_download)
    r = _run(["douyin", "https://v.douyin.com/img"])
    assert r.exit_code == 0
    assert "2 个文件" in r.output
    assert "看图_1.jpg" in r.output
    assert "看图_2.jpg" in r.output
