#!/usr/bin/env python3
"""CLI 队列命令（queue 命令组）回归

2026-10-14 P5-2：队列状态是服务进程的内存态（download_queue.active_tasks +
server._downloads），CLI 直连模块只会看到一份空队列，所以 queue 命令组一律
走 HTTP 读写正在运行的服务。本文件覆盖：

  - _queue_api：URL 拼接（--server 生效）、JSON 解析、非 JSON 响应、
    连接失败给中文提示而不是裸 traceback
  - queue list：all/active/done/failed 四种过滤、--json 纯 stdout、
    空队列与连接失败的提示
  - queue pause/resume/cancel/retry/rm：端点路径拼对、服务端 detail 透传
  - queue retry-failed：retried / orphaned 转述清楚
  - queue open：按任务文件名打开 → 成功才 dismiss；--path 直给；打开失败不移除
  - main --server：改写 _SERVER（去掉尾斜杠）
"""

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

import downloadkit.cli as cli


DEFAULT_SERVER = "http://127.0.0.1:8765"


@pytest.fixture(autouse=True)
def _reset_server(monkeypatch):
    """每个用例把 _SERVER 拨回默认，防 --server 用例污染后续。"""
    monkeypatch.setattr(cli, "_SERVER", DEFAULT_SERVER)


def _run(args):
    return CliRunner().invoke(cli.main, args, catch_exceptions=False)


def _status_payload():
    """一份覆盖全部状态的 /api/queue/status 响应。"""
    return {
        "pending": 1, "downloading": 1, "paused": 1,
        "completed": 1, "failed": 1,
        "tasks": [
            {"task_id": "t-pending", "title": "等待曲", "platform": "music",
             "status": "pending", "progress": 0.0, "downloaded_size": 0, "error": ""},
            {"task_id": "t-dl", "title": "下载中视频", "platform": "douyin",
             "status": "downloading", "progress": 0.62,
             "downloaded_size": 1048576, "error": ""},
            {"task_id": "t-pause", "title": "暂停曲", "platform": "music",
             "status": "paused", "progress": 0.3, "downloaded_size": 100, "error": ""},
            {"task_id": "t-done", "title": "完成曲", "platform": "music",
             "status": "completed", "progress": 1.0, "filename": "完成曲.mp3",
             "downloaded_size": 2097152, "error": ""},
            {"task_id": "t-fail", "title": "失败曲", "platform": "music",
             "status": "failed", "progress": 0.0, "downloaded_size": 0,
             "error": "HTTP 403"},
            {"task_id": "t-cancel", "title": "取消曲", "platform": "music",
             "status": "cancelled", "progress": 0.0, "downloaded_size": 0, "error": ""},
        ],
    }


def _stub_api(monkeypatch, handler):
    """把 cli._queue_api 换成记录调用的替身；handler(method, path, body)。"""
    calls = []

    def stub(method, path, body=None):
        calls.append((method, path, body))
        return handler(method, path, body)

    monkeypatch.setattr(cli, "_queue_api", stub)
    return calls


# ---------------------------------------------------------------- _queue_api


class _FakeResp:
    def __init__(self, code, payload):
        self.status_code = code
        self._payload = payload
        self.text = payload if isinstance(payload, str) else json.dumps(payload)

    def json(self):
        if isinstance(self._payload, (dict, list)):
            return self._payload
        raise ValueError("not json")


class TestQueueApi:
    def test_url_join_and_json_body(self, monkeypatch):
        import httpx
        seen = {}

        def fake_request(method, url, json=None, timeout=None):
            seen.update(method=method, url=url, json=json, timeout=timeout)
            return _FakeResp(200, {"status": "ok"})

        monkeypatch.setattr(httpx, "request", fake_request)

        code, data = cli._queue_api("POST", "/api/queue/t1/pause", {"a": 1})
        assert code == 200 and data == {"status": "ok"}
        assert seen["url"] == f"{DEFAULT_SERVER}/api/queue/t1/pause"
        assert seen["method"] == "POST"
        assert seen["json"] == {"a": 1}

    def test_server_option_rewrites_base(self, monkeypatch):
        """main --server 应改写 _SERVER，并吃掉尾斜杠。"""
        seen = {}

        def fake_request(method, url, json=None, timeout=None):
            seen["url"] = url
            return _FakeResp(200, {"tasks": []})

        import httpx
        monkeypatch.setattr(httpx, "request", fake_request)

        r = _run(["--server", "http://192.168.1.5:9000/", "queue", "list"])
        assert r.exit_code == 0
        assert cli._SERVER == "http://192.168.1.5:9000"
        assert seen["url"].startswith("http://192.168.1.5:9000/api/queue/status")

    def test_non_json_body_returns_text(self, monkeypatch):
        import httpx
        monkeypatch.setattr(httpx, "request",
                            lambda *a, **k: _FakeResp(200, "plain text"))
        code, data = cli._queue_api("GET", "/api/queue/status")
        assert (code, data) == (200, "plain text")

    def test_connection_error_is_chinese_hint(self, monkeypatch):
        import httpx

        def boom(*a, **k):
            raise httpx.ConnectError("refused")

        monkeypatch.setattr(httpx, "request", boom)
        code, data = cli._queue_api("GET", "/api/queue/status")
        assert code == 0
        assert "连不上服务" in data
        assert DEFAULT_SERVER in data
        assert "--server" in data  # 告诉用户换地址怎么做


# ---------------------------------------------------------------- queue list


class TestQueueList:
    def test_all_shows_every_state(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, _status_payload()))
        r = _run(["queue", "list"])
        assert r.exit_code == 0
        for tid in ("t-pending", "t-dl", "t-pause", "t-done", "t-fail", "t-cancel"):
            assert tid in r.output
        assert "已取消" in r.output
        assert "下载中 1" in r.output  # 汇总行

    def test_active_excludes_done_failed_cancelled(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, _status_payload()))
        r = _run(["queue", "list", "active"])
        for tid in ("t-pending", "t-dl", "t-pause"):
            assert tid in r.output
        for tid in ("t-done", "t-fail", "t-cancel"):
            assert tid not in r.output

    def test_done_and_failed_filters(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, _status_payload()))
        r_done = _run(["queue", "list", "done"])
        assert "t-done" in r_done.output and "t-fail" not in r_done.output

        r_fail = _run(["queue", "list", "failed"])
        assert "t-fail" in r_fail.output and "t-done" not in r_fail.output
        assert "HTTP 403" in r_fail.output  # 错误列透传

    def test_json_is_pipe_friendly(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, _status_payload()))
        r = _run(["queue", "list", "--json"])
        tasks = json.loads(r.output)  # 必须是合法 JSON（stdout 只有 JSON）
        assert len(tasks) == 6
        assert {t["task_id"] for t in tasks} == {
            "t-pending", "t-dl", "t-pause", "t-done", "t-fail", "t-cancel"}

    def test_json_filter_and_error_shape(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, _status_payload()))
        tasks = json.loads(_run(["queue", "list", "failed", "--json"]).output)
        assert [t["task_id"] for t in tasks] == ["t-fail"]

        _stub_api(monkeypatch, lambda m, p, b: (404, {"detail": "boom"}))
        err = json.loads(_run(["queue", "list", "--json"]).output)
        assert "404" in err["error"] and "boom" in err["error"]

    def test_empty_queue_hint(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, {"tasks": []}))
        assert "没有" in _run(["queue", "list"]).output

    def test_down_error_column_shows_service_detail(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务 X（ConnectError）。"))
        r = _run(["queue", "list"])
        assert "连不上服务" in r.output


# ---------------------------------------------------------------- 动作类命令


class TestQueueActions:
    @pytest.mark.parametrize("sub,expected_path,ok_text", [
        ("pause", "/api/queue/t-pending/pause", "已暂停"),
        ("resume", "/api/queue/t-pending/resume", "已恢复"),
        ("cancel", "/api/queue/t-pending/cancel", "已取消"),
    ])
    def test_endpoint_and_confirm(self, monkeypatch, sub, expected_path, ok_text):
        """先查一次队列确认任务存在（服务端这三端点是 fire-and-forget），
        再 POST 动作端点。"""
        calls = _stub_api(monkeypatch, lambda m, p, b: (
            (200, _status_payload()) if p == "/api/queue/status"
            else (200, {"status": "ok"})))
        r = _run(["queue", sub, "t-pending"])
        assert r.exit_code == 0
        assert calls[0] == ("GET", "/api/queue/status", None)
        assert calls[1] == ("POST", expected_path, None)
        assert ok_text in r.output

    def test_rm_needs_no_precheck(self, monkeypatch):
        """rm 直接 POST dismiss（服务端自己会 404/409，不必先查）。"""
        calls = _stub_api(monkeypatch, lambda m, p, b: (200, {"status": "ok"}))
        _run(["queue", "rm", "t1"])
        assert calls == [("POST", "/api/queue/t1/dismiss", None)]

    def test_action_on_missing_task_is_rejected(self, monkeypatch):
        """队列里没有的任务：不发动作请求，报中文提示（不给假成功）。"""
        calls = _stub_api(monkeypatch, lambda m, p, b: (
            (200, {"tasks": []}) if p == "/api/queue/status"
            else (200, {"status": "ok"})))
        r = _run(["queue", "pause", "t-nope"])
        assert "队列里没有任务 t-nope" in r.output
        assert all(c[0] != "POST" for c in calls), "不该发出 pause 请求"

    def test_retry_prints_new_task_id(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, {"status": "retried",
                                                     "new_task_id": "n-9"}))
        r = _run(["queue", "retry", "t-fail"])
        assert "已重新入队 t-fail" in r.output
        assert "n-9" in r.output

    def test_server_detail_is_shown(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (409, {"detail": "任务还在进行中，不能移除"}))
        r = _run(["queue", "rm", "t-dl"])
        assert "HTTP 409" in r.output
        assert "任务还在进行中，不能移除" in r.output

    def test_retry_failed_translates_counts(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: (200, {"status": "ok",
                                                             "retried": 2, "orphaned": 1}))
        r = _run(["queue", "retry-failed"])
        assert calls == [("POST", "/api/queue/retry-failed", None)]
        assert "2" in r.output and "已过期" in r.output and "1" in r.output


# ---------------------------------------------------------------- queue open


class TestQueueOpen:
    def _open_stub(self, monkeypatch, open_code=(200, {"status": "opened",
                                                       "path": "/dl/完成曲.mp3"}),
                   payload=None):
        payload = payload or _status_payload()
        calls = []

        def handler(method, path, body):
            calls.append((method, path, body))
            if path == "/api/queue/status":
                return 200, payload
            if path == "/api/open-file":
                return open_code
            return 200, {"status": "dismissed"}

        _stub_api(monkeypatch, handler)
        return calls

    def test_open_by_task_then_dismiss(self, monkeypatch):
        calls = self._open_stub(monkeypatch)
        r = _run(["queue", "open", "t-done"])
        assert r.exit_code == 0
        assert calls[1] == ("POST", "/api/open-file", {"path": "完成曲.mp3"})
        assert calls[2][1] == "/api/queue/t-done/dismiss"
        assert "/dl/完成曲.mp3" in r.output
        assert "已把 t-done 移出队列列表" in r.output

    def test_open_with_path_option_skips_status(self, monkeypatch):
        calls = self._open_stub(monkeypatch)
        _run(["queue", "open", "t-done", "--path", "C:/dl/a.mp3"])
        # 只打了 open-file + dismiss，没有查状态
        assert [c[1] for c in calls] == ["/api/open-file", "/api/queue/t-done/dismiss"]
        assert calls[0][2] == {"path": "C:/dl/a.mp3"}

    def test_open_failure_does_not_dismiss(self, monkeypatch):
        calls = self._open_stub(
            monkeypatch, open_code=(404, {"detail": "文件不存在或已被移动"}))
        r = _run(["queue", "open", "t-done"])
        assert "文件不存在或已被移动" in r.output
        assert all(c[1] != "/api/queue/t-done/dismiss" for c in calls)

    def test_open_unknown_task(self, monkeypatch):
        calls = self._open_stub(monkeypatch)
        r = _run(["queue", "open", "t-nope"])
        assert "队列里没有任务 t-nope" in r.output
        assert all(c[1] != "/api/open-file" for c in calls)

    def test_open_task_without_filename(self, monkeypatch):
        payload = _status_payload()
        payload["tasks"][3]["filename"] = ""  # t-done 没文件名
        calls = self._open_stub(monkeypatch, payload=payload)
        r = _run(["queue", "open", "t-done"])
        assert "--path" in r.output
        assert all(c[1] != "/api/open-file" for c in calls)
