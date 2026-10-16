#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 下载历史命令（history 命令组）回归

P5-7b：服务端 /api/history/* 端点补齐后的 CLI 回归。
退出码沿用 P5-2 那组「状态查询」约定——查到空也算成功 → 0；用法错误 → 2。
"""
import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

import downloadkit.cli as cli


DEFAULT_SERVER = "http://127.0.0.1:8765"

_RECORDS = [
    {"id": 1, "url": "https://example.com/1", "platform": "douyin",
     "title": "晴天", "author": "周杰伦", "cover": "",
     "file_path": "C:/Downloads/music/晴天.mp3", "file_size": 5242880,
     "downloaded_at": "2026-10-15 10:00:00"},
    {"id": 2, "url": "https://example.com/2", "platform": "bilibili",
     "title": "某视频", "author": "UP主", "cover": "",
     "file_path": "C:/Downloads/videos/某视频.mp4", "file_size": 104857600,
     "downloaded_at": "2026-10-14 08:30:00"},
    {"id": 3, "url": "https://example.com/3", "platform": "youtube",
     "title": "Another Song", "author": "Artist", "cover": "",
     "file_path": "", "file_size": 0,
     "downloaded_at": "2026-10-13 22:15:00"},
]


@pytest.fixture(autouse=True)
def _reset_server(monkeypatch):
    monkeypatch.setattr(cli, "_SERVER", DEFAULT_SERVER)


def _run(args, input=None):
    return CliRunner().invoke(cli.main, args, input=input, catch_exceptions=False)


def _stub_api(monkeypatch, handler):
    """把 cli._queue_api 换成记录调用的替身。"""
    calls = []

    def stub(method, path, body=None, **kw):
        calls.append({"method": method, "path": path, "body": body})
        return handler(method, path, body)

    monkeypatch.setattr(cli, "_queue_api", stub)
    return calls


def _make_handler(records):
    """根据 records 列表构造一个完整的请求 handler。"""
    import urllib.parse
    def handler(method, path, body=None):
        # GET /api/history?limit=X&offset=Y
        if method == "GET" and path.startswith("/api/history?"):
            qs = urllib.parse.urlparse(path).query
            params = urllib.parse.parse_qs(qs)
            limit = int(params.get("limit", ["50"])[0])
            offset = int(params.get("offset", ["0"])[0])
            return 200, records[offset:offset + limit]
        # GET /api/history/count
        if method == "GET" and path == "/api/history/count":
            return 200, {"count": len(records)}
        # POST /api/history/search?keyword=X
        if method == "POST" and path.startswith("/api/history/search"):
            qs = urllib.parse.urlparse(path).query
            params = urllib.parse.parse_qs(qs)
            kw = params.get("keyword", [""])[0].lower()
            matched = [r for r in records
                       if kw in r.get("title", "").lower()
                       or kw in r.get("author", "").lower()]
            return 200, matched
        # POST /api/history/clear
        if method == "POST" and path == "/api/history/clear":
            return 200, {"status": "cleared"}
        # DELETE /api/history/{id}
        if method == "DELETE" and path.startswith("/api/history/"):
            rid_str = path.split("/")[-1]
            try:
                rid = int(rid_str)
            except ValueError:
                return 400, {"detail": "无效的 ID"}
            if rid not in {r["id"] for r in records}:
                return 404, {"detail": "记录不存在"}
            return 200, {"status": "deleted"}
        return 500, {"detail": "unexpected endpoint"}
    return handler


# ============================ list ============================

def test_list_is_get_request(monkeypatch):
    calls = _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "list"])
    assert r.exit_code == 0
    assert calls[0]["method"] == "GET"
    assert calls[0]["path"].startswith("/api/history?")


def test_list_empty_shows_hint(monkeypatch):
    _stub_api(monkeypatch, _make_handler([]))
    r = _run(["history", "list"])
    assert r.exit_code == 0
    assert "还没有下载记录" in r.output


def test_list_shows_title_author_size(monkeypatch):
    _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "list"])
    assert r.exit_code == 0
    assert "晴天" in r.output
    assert "周杰伦" in r.output
    assert "共 3 条" in r.output


def test_list_file_path_echoed_separately(monkeypatch):
    _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "list"])
    assert r.exit_code == 0
    assert "C:/Downloads/music/晴天.mp3" in r.output


def test_list_json_raw(monkeypatch):
    _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "list", "--json"])
    assert r.exit_code == 0
    assert json.loads(r.output) == _RECORDS


def test_list_offline_exit_0(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务"))
    r = _run(["history", "list"])
    assert r.exit_code == 0
    assert "连不上服务" in r.output


def test_list_pagination(monkeypatch):
    _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "list", "-n", "2", "-o", "1"])
    assert r.exit_code == 0
    assert "共 2 条" in r.output
    # Should show records 2 and 3, not record 1
    assert "某视频" in r.output
    assert "Another Song" in r.output


# ============================ search ============================

def test_search_posts_keyword(monkeypatch):
    calls = _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "search", "晴天"])
    assert r.exit_code == 0
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"].startswith("/api/history/search")
    assert "keyword=%E6%99%B4%E5%A4%A9" in calls[0]["path"] or "keyword=%E6%99%B4%E5%A4%A9" in calls[0]["path"]


def test_search_hits_show_results(monkeypatch):
    _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "search", "晴天"])
    assert r.exit_code == 0
    assert "晴天" in r.output
    assert "共 1 条" in r.output


def test_search_no_match(monkeypatch):
    _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "search", "不存在"])
    assert r.exit_code == 0
    assert "没有找到" in r.output


def test_search_json(monkeypatch):
    _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "search", "晴天", "--json"])
    assert r.exit_code == 0
    result = json.loads(r.output)
    assert len(result) == 1
    assert result[0]["title"] == "晴天"


def test_search_empty_keyword_exit_2(monkeypatch):
    calls = _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "search", ""])
    assert r.exit_code == 2
    assert calls == []
    assert "不能为空" in (r.stderr or "")


def test_search_online_exit_0(monkeypatch):
    """离线时 _hist_api 返回中文提示而非 None，但退出码仍是 0。"""
    _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务"))
    r = _run(["history", "search", "test"])
    assert r.exit_code == 0
    assert "连不上服务" in r.output


# ============================ rm ============================

def test_rm_confirm_no_deletes_nothing(monkeypatch):
    _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "rm", "1"], input="n\n")
    assert r.exit_code == 0
    assert "已取消" in r.output
    deletes = [c for c in _stub_api(monkeypatch, _make_handler(_RECORDS))
               if c["method"] == "DELETE"]
    assert len(deletes) == 0


def test_rm_lists_ids_before_confirm(monkeypatch):
    _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "rm", "1", "2"], input="n\n")
    assert r.exit_code == 0
    assert "已取消" in r.output
    assert "1" in r.output and "2" in r.output


def test_rm_yes_deletes(monkeypatch):
    records = list(_RECORDS)

    def handler(method, path, body=None):
        if method == "GET" and path.startswith("/api/history?"):
            return 200, records
        if method == "DELETE" and "/api/history/1" in path:
            records.pop(0)
            return 200, {"status": "deleted"}
        return 500, {}

    _stub_api(monkeypatch, handler)
    r = _run(["history", "rm", "1", "--yes"])
    assert r.exit_code == 0
    assert "已删除 1 条" in r.output


def test_rm_unknown_id_reported(monkeypatch):
    _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "rm", "999", "--yes"])
    assert r.exit_code == 0
    assert "记录不存在：999" in r.output
    # 全部不存在时直接 return，不打印"已删除 0 条"
    assert "已删除" not in r.output


def test_rm_all_unknown_no_confirm(monkeypatch):
    """全都不存在时不该问确认，也不打印"已删除"。"""
    _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "rm", "998", "999"])
    assert r.exit_code == 0
    assert "确认删除" not in r.output
    assert "记录不存在：998" in r.output
    assert "记录不存在：999" in r.output
    assert "已删除" not in r.output


def test_rm_partial(monkeypatch):
    def handler(method, path, body=None):
        if method == "GET" and path.startswith("/api/history?"):
            return 200, _RECORDS
        if method == "DELETE" and "/api/history/1" in path:
            return 200, {"status": "deleted"}
        if method == "DELETE":
            return 404, {"detail": "记录不存在"}
        return 500, {}
    _stub_api(monkeypatch, handler)
    r = _run(["history", "rm", "1", "999", "--yes"])
    assert r.exit_code == 0
    assert "记录不存在：999" in r.output
    assert "已删除 1 条" in r.output


def test_rm_non_int_id_exit_2(monkeypatch):
    calls = _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "rm", "abc"])
    assert r.exit_code == 2
    assert calls == []
    assert "必须是整数" in (r.stderr or "")


def test_rm_requires_ids():
    r = _run(["history", "rm"])
    assert r.exit_code == 2


# ============================ clear ============================

def test_clear_confirms_first(monkeypatch):
    _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "clear"], input="n\n")
    assert r.exit_code == 0
    assert "已取消" in r.output
    assert "不可恢复" in r.output


def test_clear_yes_clears(monkeypatch):
    def handler(method, path, body=None):
        if path == "/api/history/count":
            return 200, {"count": 3}
        if path == "/api/history/clear":
            return 200, {"status": "cleared"}
        return 500, {}
    _stub_api(monkeypatch, handler)
    r = _run(["history", "clear", "--yes"])
    assert r.exit_code == 0
    assert "已清空" in r.output
    assert "共删除 3 条" in r.output


def test_clear_offline_exit_0(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务"))
    r = _run(["history", "clear"])
    assert r.exit_code == 0
    assert "连不上服务" in r.output


# ============================ count ============================

def test_count_show_number(monkeypatch):
    _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "count"])
    assert r.exit_code == 0
    assert "3" in r.output


def test_count_json(monkeypatch):
    _stub_api(monkeypatch, _make_handler(_RECORDS))
    r = _run(["history", "count", "--json"])
    assert r.exit_code == 0
    assert json.loads(r.output) == {"count": 3}


def test_count_offline_exit_0(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务"))
    r = _run(["history", "count"])
    assert r.exit_code == 0
    assert "连不上服务" in r.output


# ============================= 组 =============================

def test_bare_history_is_usage_error():
    r = _run(["history"])
    assert r.exit_code == 2


def test_help_lists_all_commands():
    r = _run(["history", "--help"])
    assert r.exit_code == 0
    for name in ("list", "search", "rm", "clear", "count"):
        assert name in r.output
