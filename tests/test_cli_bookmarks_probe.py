#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI bookmarks probe 命令回归

P5-9：服务端已有 POST /api/bookmarks/probe / GET /api/bookmarks/probe/{id}
/ POST /api/bookmarks/probe/{id}/stop 三个端点，CLI 补齐命令。

测试策略：
  - _probe_api 替身：记录调用，返回假探测结果
  - _read_bookmark_file 替身：返回假 HTML，跳过真实文件解析
  - 覆盖：启动 / 轮询 / --urls / --json / 无 HTTP 链接 / 连不上服务
"""
import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

import downloadkit.cli as cli


FAKE_HTML = (
    '<!DOCTYPE NETSCAPE-Bookmark-file-1>\n'
    '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">\n'
    '<TITLE>Bookmarks</TITLE>\n'
    '<H1>Bookmarks</H1>\n'
    '<DL><p>\n'
    '  <DT><A HREF="https://example.com/video/1">视频1</A>\n'
    '  <DT><A HREF="https://example.com/video/2">视频2</A>\n'
    '  <DT><A HREF="not-a-url">无效</A>\n'
    '</DL><p>\n'
)

BAD_HTML = (
    '<!DOCTYPE NETSCAPE-Bookmark-file-1>\n'
    '<DL><p>\n'
    '  <DT><A HREF="mailto:test@test.com">邮件</A>\n'
    '</DL><p>\n'
)

_PROBE_RESULT = {
    "status": "done",
    "total": 2,
    "done": 2,
    "hit": 1,
    "results": [
        {"url": "https://example.com/video/1", "title": "视频1",
         "status": "hit", "layer": "L1", "streams": ["http://cdn/x.mp4"],
         "referer": "", "elapsed": 1.2, "error": ""},
        {"url": "https://example.com/video/2", "title": "视频2",
         "status": "miss", "layer": "L1", "streams": [],
         "referer": "", "elapsed": 0.8, "error": "静态无流"},
    ],
    "error": "",
}


@pytest.fixture(autouse=True)
def _reset_server(monkeypatch):
    monkeypatch.setattr(cli, "_SERVER", "http://127.0.0.1:8765")


def _run(args, input=None):
    return CliRunner().invoke(cli.main, args, input=input, catch_exceptions=False)


def _make_handler(start_code=200, start_payload=None, poll_result=None):
    """标准 handler：第一次 POST 返回 probe_id，之后 GET 轮询返回结果。"""
    state = {"done": False}

    def handler(method, path, body=None):
        if method == "POST" and path == "/api/bookmarks/probe":
            return start_code, start_payload or {"probe_id": "probe_123", "total": 2}
        if method == "GET" and "/api/bookmarks/probe/" in path:
            if not state["done"]:
                state["done"] = True
                return 200, {
                    "status": "running", "total": 2, "done": 0, "hit": 0,
                    "results": [], "error": "",
                }
            return 200, poll_result or _PROBE_RESULT
        return 500, {"detail": "unexpected"}

    return handler


def _stub_probe(monkeypatch, handler, html=FAKE_HTML):
    """替身 _probe_api + _read_bookmark_file。"""
    calls = []

    def stub(method, path, body=None, **kw):
        calls.append({"method": method, "path": path, "body": body})
        return handler(method, path, body)

    monkeypatch.setattr(cli, "_probe_api", stub)
    monkeypatch.setattr(cli, "_read_bookmark_file", lambda path: html)
    return calls


# ============================ probe ============================

def test_probe_starts_and_polls(monkeypatch, tmp_path):
    calls = _stub_probe(monkeypatch, _make_handler())
    f = tmp_path / "bm.html"
    f.write_text(FAKE_HTML, encoding="utf-8")
    r = _run(["bookmarks", "probe", str(f)])
    assert r.exit_code == 0, r.output
    posts = [c for c in calls if c["method"] == "POST"]
    gets = [c for c in calls if c["method"] == "GET"]
    assert len(posts) >= 1
    assert posts[0]["body"]["l2"] is True
    assert len(gets) >= 1
    assert "探测完成" in r.output
    assert "命中 1" in r.output
    assert "未命中 1" in r.output


def test_probe_urls_mode(monkeypatch, tmp_path):
    _stub_probe(monkeypatch, _make_handler())
    f = tmp_path / "bm.html"
    f.write_text(FAKE_HTML, encoding="utf-8")
    r = _run(["bookmarks", "probe", str(f), "--urls"])
    assert r.exit_code == 0, r.output
    lines = [l.strip() for l in r.output.splitlines() if l.strip().startswith("http")]
    assert "https://example.com/video/1" in lines
    assert "https://example.com/video/2" in lines


def test_probe_json_mode(monkeypatch, tmp_path):
    _stub_probe(monkeypatch, _make_handler())
    f = tmp_path / "bm.html"
    f.write_text(FAKE_HTML, encoding="utf-8")
    r = _run(["bookmarks", "probe", str(f), "--json"])
    assert r.exit_code == 0, r.output
    data = json.loads(r.output)
    assert "probe_id" in data


def test_probe_no_l2(monkeypatch, tmp_path):
    calls = _stub_probe(monkeypatch, _make_handler())
    f = tmp_path / "bm.html"
    f.write_text(FAKE_HTML, encoding="utf-8")
    r = _run(["bookmarks", "probe", str(f), "--no-l2"])
    assert r.exit_code == 0, r.output
    post = [c for c in calls if c["method"] == "POST"][0]
    assert post["body"]["l2"] is False


def test_probe_limit_truncates(monkeypatch, tmp_path):
    """limit 小于命中数 → 显示截断提示。"""
    result = dict(_PROBE_RESULT)
    result["hit"] = 3
    result["results"] = [
        {"url": f"https://example.com/v/{i}", "title": f"视频{i}",
         "status": "hit", "layer": "L1", "streams": ["http://cdn/x.mp4"],
         "referer": "", "elapsed": 1.0, "error": ""}
        for i in range(1, 4)
    ] + [
        {"url": "https://example.com/miss", "title": " miss",
         "status": "miss", "layer": "L1", "streams": [],
         "referer": "", "elapsed": 0.5, "error": "静态无流"}
    ]
    result["total"] = result["done"] = 4
    _stub_probe(monkeypatch, _make_handler(poll_result=result))
    f = tmp_path / "bm.html"
    f.write_text(FAKE_HTML, encoding="utf-8")
    r = _run(["bookmarks", "probe", str(f), "-n", "1"])
    assert r.exit_code == 0, r.output
    assert "只显示前 1 条" in r.output


def test_probe_connection_failed_exit_1(monkeypatch, tmp_path):
    """连不上服务 → _probe_api 退出码 1（和 sniff/bookmarks 探测器组一致）。"""
    _stub_probe(monkeypatch, lambda m, p, b: (0, "连不上服务"))
    f = tmp_path / "bm.html"
    f.write_text(FAKE_HTML, encoding="utf-8")
    r = _run(["bookmarks", "probe", str(f)])
    assert r.exit_code == 1, r.output
    assert "启动失败" in r.output


def test_probe_no_http_links(monkeypatch, tmp_path):
    """书签里没有任何 HTTP 链接 → 本地报错退出。"""
    f = tmp_path / "bm.html"
    f.write_text(BAD_HTML, encoding="utf-8")
    r = _run(["bookmarks", "probe", str(f)])
    assert r.exit_code == 0, r.output
    assert "可探测的 HTTP 链接" in r.output


def test_probe_help_has_probe():
    r = _run(["bookmarks", "--help"])
    assert r.exit_code == 0
    assert "probe" in r.output


def test_probe_show_miss_details(monkeypatch, tmp_path):
    """未命中条目也展示层和错误原因。"""
    _stub_probe(monkeypatch, _make_handler())
    f = tmp_path / "bm.html"
    f.write_text(FAKE_HTML, encoding="utf-8")
    r = _run(["bookmarks", "probe", str(f)])
    assert r.exit_code == 0, r.output
    assert "L1" in r.output
    assert "静态无流" in r.output
