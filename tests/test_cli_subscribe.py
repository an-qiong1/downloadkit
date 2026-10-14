#!/usr/bin/env python3
"""CLI 订阅命令（subscribe 命令组）回归

2026-10-14 P5-3：订阅要抓主页，用的是服务进程里那份浏览器
（douyin._browser_instance），CLI 自己再起一份就是另一套登录态，还会跟轮询
抢同一个 Chromium；检查完要入队，队列又是服务进程的内存态。所以 subscribe
命令组和 queue 一样一律走 HTTP 问正在运行的服务，绝不直连模块。

本文件覆盖：

  - 传输层：超时参数（抓主页远超 30 秒，不传会「服务端还在干活、客户端先
    报超时」）、连接失败的中文提示、_detail_of 两种错误写法
  - _map_scope / _scope_text / _ago / _resolve_creator 四个纯函数
  - subscribe list：表格、上次结果、总览、--json 纯 stdout
  - subscribe add：fetch_profile 开关、重复订阅短路、401/429 给行动建议
  - subscribe remove / rm：按昵称解析后 DELETE
  - subscribe scope：短写翻译、backfill_n 必须带 N、all 要确认
  - subscribe check：dry-run、长超时、范围 all 的确认、结果转述
  - subscribe check-all：临时覆盖范围（不给就是 null 而不是空串）、
    跳过/中断标记要显式喊出来
  - subscribe poller：查看 / on / off / set、--daily-at 或 --interval 单给时
    自动推断 mode、两个都给要显式 --mode

取输出注意：CliRunner 会把 sys.stdout 接走，所以走命令的用例读 r.output；
只有直接调函数（_resolve_creator 等）才轮得到 capsys。
"""

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

import downloadkit.cli as cli


DEFAULT_SERVER = "http://127.0.0.1:8765"
SEC_A = "MS4wLjABAAAA1111aaaa"
SEC_B = "MS4wLjABAAAA2222bbbb"


@pytest.fixture(autouse=True)
def _reset_server(monkeypatch):
    """每个用例把 _SERVER 拨回默认，防 --server 用例污染后续。"""
    monkeypatch.setattr(cli, "_SERVER", DEFAULT_SERVER)


def _run(args, **kw):
    return CliRunner().invoke(cli.main, args, catch_exceptions=False, **kw)


def _stub_api(monkeypatch, handler):
    """把 cli._queue_api 换成记录调用的替身；handler(method, path, body)。

    timeout 单独记在 calls 里：抓主页那几条命令必须传长超时，
    但 handler 不需要关心它。
    """
    calls = []

    def stub(method, path, body=None, timeout=None):
        calls.append({"method": method, "path": path,
                      "body": body, "timeout": timeout})
        return handler(method, path, body)

    monkeypatch.setattr(cli, "_queue_api", stub)
    return calls


def _fake_resp(code, payload):
    """假装的 httpx 响应（传输层测试用；payload 非 dict/list 时 json() 抛错）。"""
    class R:
        status_code = code
        text = payload if isinstance(payload, str) else json.dumps(payload)

        @staticmethod
        def json():
            if isinstance(payload, (dict, list)):
                return payload
            raise ValueError("not json")
    return R()


def _subs_payload(**over):
    """一份 /api/subscriptions 响应：一个启用、一个暂停，覆盖三种范围字段。"""
    data = {
        "creators": [
            {"sec_uid": SEC_A, "nickname": "博主甲", "enabled": 1,
             "download_scope": "only_new", "scope_param": "",
             "last_checked": "2026-10-14 09:00:00",
             "last_result": "发现 3 个新作品，入队 3 个",
             "works_count": 12},
            {"sec_uid": SEC_B, "nickname": "[MV]乙", "enabled": 0,
             "download_scope": "backfill_n", "scope_param": "5",
             "last_checked": "", "last_result": "", "works_count": 0},
        ],
        "stats": {"creators": 2, "enabled": 1, "works_seen": 12,
                  "db_path": "/tmp/subscriptions.db"},
    }
    data.update(over)
    return data


def _poller_payload(**over):
    data = {
        "enabled": True, "mode": "interval", "daily_at": "09:00",
        "interval_minutes": 60, "max_new_per_check": 3, "jitter_percent": 20,
        "running": False, "rounds": 3, "last_run_at": "2026-10-14 09:00:00",
        "consecutive_failures": 0, "backoff_until": "", "needs_login": False,
        "next_run_at": "2026-10-14 10:00:00",
        "interval_range": {"min": 15, "max": 1440},
        "creators_enabled": 2,
        "last_result": {"total": 2, "queued": 1, "new_found": 3, "errors": 0,
                        "rate_limited": False, "needs_login": False,
                        "message": ""},
    }
    data.update(over)
    return data


# ---------------------------------------------------------------- 传输层


class TestTransport:
    def test_default_timeout_is_30(self, monkeypatch):
        import httpx
        seen = {}

        def fake(method, url, json=None, timeout=None):
            seen["timeout"] = timeout
            return _fake_resp(200, {})

        monkeypatch.setattr(httpx, "request", fake)
        assert cli._queue_api("GET", "/api/subscriptions") == (200, {})
        assert seen["timeout"] == 30.0

    def test_explicit_timeout_overrides(self, monkeypatch):
        """抓主页的命令靠这条把超时从 30 秒抬到 600 秒，必须真的传下去。"""
        import httpx
        seen = {}

        def fake(method, url, json=None, timeout=None):
            seen["timeout"] = timeout
            return _fake_resp(200, {})

        monkeypatch.setattr(httpx, "request", fake)
        cli._queue_api("POST", "/api/subscriptions/check-all", {}, timeout=600.0)
        assert seen["timeout"] == 600.0
        assert cli._API_TIMEOUT_LONG == 600.0

    def test_connect_error_message_works_for_both_groups(self, monkeypatch):
        """连不上时的提示对 queue 和 subscribe 都得成立，别只说队列。"""
        import httpx

        def boom(*a, **k):
            raise httpx.ConnectError("boom")

        monkeypatch.setattr(httpx, "request", boom)
        code, data = cli._queue_api("GET", "/api/subscriptions")
        assert code == 0
        assert "连不上服务" in data
        assert "DownloadKit 正在运行" in data
        assert "--server" in data
        assert "队列命令" not in data


class TestDetailOf:
    def test_http_exception_detail(self):
        assert cli._detail_of({"detail": "没有订阅这个创作者"}) == "没有订阅这个创作者"

    def test_browser_error_uses_error_key(self):
        """401/429 是 {"ok": false, "error": ...} —— 只认 detail 会吐一坨 JSON。"""
        payload = {"ok": False, "error": "需要先登录抖音"}
        assert cli._detail_of(payload) == "需要先登录抖音"

    def test_message_key_fallback(self):
        assert cli._detail_of({"message": "本轮跳过"}) == "本轮跳过"

    def test_falls_back_to_json(self):
        assert cli._detail_of({"a": 1}) == json.dumps({"a": 1}, ensure_ascii=False)

    def test_non_dict(self):
        assert cli._detail_of("plain") == "plain"


# ---------------------------------------------------------------- 纯函数


class TestScopeHelpers:
    @pytest.mark.parametrize("token,expect", [
        ("only_new", "only_new"), ("ONLY_NEW", "only_new"), ("new", "only_new"),
        ("backfill_n", "backfill_n"), ("backfill", "backfill_n"),
        ("all", "all"), (" all ", "all"),
    ])
    def test_map_scope_aliases(self, token, expect):
        assert cli._map_scope(token) == expect

    @pytest.mark.parametrize("token", ["", "since", "newest", "everything"])
    def test_map_scope_unknown(self, token):
        assert cli._map_scope(token) is None

    @pytest.mark.parametrize("scope,param,expect", [
        ("only_new", "", "只下新作品"),
        ("backfill_n", "5", "新 + 往回补 5 个"),
        ("backfill_n", "", "新 + 往回补 ? 个"),
        ("all", "", "全部历史作品"),
        ("", "", "-"),
        ("weird", "", "weird"),
    ])
    def test_scope_text(self, scope, param, expect):
        assert cli._scope_text(scope, param) == expect


class TestAgo:
    def test_empty_is_dash(self):
        assert cli._ago("") == "-"
        assert cli._ago(None) == "-"

    def test_unparseable_returns_raw(self):
        assert cli._ago("昨天") == "昨天"

    @pytest.mark.parametrize("delta,expect", [
        (timedelta(minutes=5), "5 分钟前"),
        (timedelta(seconds=30), "30 秒前"),
        (timedelta(hours=3), "3 小时前"),
        (timedelta(days=2), "2 天前"),
    ])
    def test_relative_units(self, delta, expect):
        ts = (datetime.now() - delta).strftime("%Y-%m-%d %H:%M:%S")
        assert cli._ago(ts) == expect

    def test_future_is_just_now(self):
        ts = (datetime.now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        assert cli._ago(ts) == "刚刚"


class TestResolveCreator:
    def _creators(self):
        return [
            {"sec_uid": SEC_A, "nickname": "博主甲"},
            {"sec_uid": SEC_B, "nickname": "乙乙工作室"},
        ]

    def test_exact_nickname(self):
        assert cli._resolve_creator("博主甲", self._creators()) == SEC_A
        assert cli._resolve_creator("乙乙工作室", self._creators()) == SEC_B

    def test_unique_prefix(self):
        assert cli._resolve_creator("博主", self._creators()) == SEC_A
        assert cli._resolve_creator("乙乙", self._creators()) == SEC_B

    def test_unique_substring(self):
        assert cli._resolve_creator("工作室", self._creators()) == SEC_B

    def test_direct_sec_uid(self):
        assert cli._resolve_creator(SEC_A, self._creators()) == SEC_A

    def test_unknown_nickname_lists_candidates(self, capsys):
        assert cli._resolve_creator("张三", self._creators()) is None
        out = capsys.readouterr().out
        assert "没有匹配" in out
        assert "博主甲" in out and "乙乙工作室" in out

    def test_empty_list_gives_add_hint(self, capsys):
        assert cli._resolve_creator("张三", []) is None
        assert "subscribe add" in capsys.readouterr().out

    def test_empty_input(self, capsys):
        assert cli._resolve_creator("   ", self._creators()) is None
        assert "请输入" in capsys.readouterr().out

    def test_ambiguous_reports_both_never_guesses(self, capsys):
        creators = [
            {"sec_uid": SEC_A, "nickname": "同一昵称"},
            {"sec_uid": SEC_B, "nickname": "同一昵称"},
        ]
        assert cli._resolve_creator("同一昵称", creators) is None
        out = capsys.readouterr().out
        assert "匹配到 2 个" in out
        assert SEC_A in out and SEC_B in out


# ---------------------------------------------------------------- list


class TestList:
    def test_empty_gives_add_hint(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, {"creators": [], "stats": {}}))
        r = _run(["subscribe", "list"])
        assert r.exit_code == 0
        assert "还没有订阅任何创作者" in r.output
        assert "subscribe add" in r.output

    def test_table_and_results_and_stats(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, _subs_payload()))
        r = _run(["subscribe", "list"])
        assert r.exit_code == 0
        out = r.output
        # 昵称里的方括号要被转义，否则 rich 当成标记吃掉（[MV] 会消失或报错）
        assert "[MV]乙" in out
        assert "博主甲" in out
        assert "已暂停" in out and "启用" in out
        assert "只下新作品" in out
        assert "新 + 往回补 5 个" in out
        assert "上次结果" in out
        assert "发现 3 个新作品，入队 3 个" in out
        assert "订阅 2 个（启用 1）" in out
        assert "已发现作品 12" in out
        assert "/tmp/subscriptions.db" in out

    def test_json_is_pure_stdout(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, _subs_payload()))
        r = _run(["subscribe", "list", "--json"])
        assert r.exit_code == 0
        parsed = json.loads(r.output)
        assert [c["sec_uid"] for c in parsed] == [SEC_A, SEC_B]

    def test_json_error_is_structured(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (500, {"detail": "炸了"}))
        r = _run(["subscribe", "list", "--json"])
        assert r.exit_code == 0
        assert json.loads(r.output) == {"error": "HTTP 500: 炸了"}

    def test_connect_error_prints_hint(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务 X（ConnectError）。"))
        r = _run(["subscribe", "list"])
        assert r.exit_code == 0
        assert "连不上服务" in r.output


# ---------------------------------------------------------------- add


class TestAdd:
    def test_posts_url_with_profile(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: (200, {
            "ok": True, "creator": {"sec_uid": SEC_A, "nickname": "博主甲",
                                    "download_scope": "only_new", "scope_param": ""}}))
        # 没法本地解析的输入 → 跳过查重，直接 POST
        r = _run(["subscribe", "add", "https://example.com/x"])
        assert r.exit_code == 0
        post = [c for c in calls if c["method"] == "POST"]
        assert len(post) == 1
        assert post[0]["path"] == "/api/subscriptions"
        assert post[0]["body"] == {"url": "https://example.com/x",
                                   "fetch_profile": True}
        assert post[0]["timeout"] == cli._API_TIMEOUT_LONG

    def test_no_profile_skips_profile_fetch(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: (200, {"creator": {}}))
        r = _run(["subscribe", "add", "https://example.com/x", "--no-profile"])
        assert r.exit_code == 0
        assert calls[-1]["body"]["fetch_profile"] is False

    def test_already_subscribed_short_circuits_before_post(self, monkeypatch):
        """重复订阅服务端原样返回记录，光看返回分辨不出是新增还是已存在。"""
        calls = _stub_api(monkeypatch, lambda m, p, b: (200, _subs_payload()))
        r = _run(["subscribe", "add", f"https://www.douyin.com/user/{SEC_A}"])
        assert r.exit_code == 0
        assert "已经订阅过了" in r.output
        assert not [c for c in calls if c["method"] == "POST"], "查重命中不该再 POST"

    def test_not_subscribed_goes_on_to_post(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: (200, {
            "creator": {"sec_uid": SEC_A, "nickname": "新来的",
                        "download_scope": "only_new"}}))
        r = _run(["subscribe", "add", "https://example.com/x"])
        assert r.exit_code == 0
        assert [c for c in calls if c["method"] == "POST"]
        assert "已订阅" in r.output

    def test_login_required_suggests_settings_page(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (401, {"ok": False,
                                                      "error": "需要先登录抖音"}))
        r = _run(["subscribe", "add", "https://example.com/x"])
        assert r.exit_code == 0
        assert "需要先登录抖音" in r.output
        assert "设置 → 登录抖音" in r.output

    def test_rate_limited_suggests_home_page_link(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (429, {"ok": False, "error": "限流了"}))
        r = _run(["subscribe", "add", "https://example.com/x"])
        assert r.exit_code == 0
        assert "限流了" in r.output
        assert "改贴主页链接" in r.output

    def test_json_output(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, {
            "creator": {"sec_uid": SEC_A, "nickname": "博主甲"}}))
        r = _run(["subscribe", "add", "https://example.com/x", "--json"])
        assert r.exit_code == 0
        assert json.loads(r.output)["sec_uid"] == SEC_A


# ---------------------------------------------------------------- remove / rm


def _remove_handler(method, path, body):
    """GET 列表给订阅，DELETE 给成功。

    按 method 分而不是按 body：DELETE 也是 body=None，按 body 分会把
    删除请求当列表读回一份 200，测试看着绿其实没删到东西。
    """
    if method == "GET":
        return 200, _subs_payload()
    return 200, {"ok": True}


class TestRemove:
    @pytest.mark.parametrize("cmd", ["remove", "rm"])
    def test_deletes_resolved_uid(self, monkeypatch, cmd):
        calls = _stub_api(monkeypatch, _remove_handler)
        r = _run(["subscribe", cmd, "博主甲"])
        assert r.exit_code == 0
        assert calls[-1]["method"] == "DELETE"
        assert calls[-1]["path"] == f"/api/subscriptions/{SEC_A}"
        assert "已取消订阅" in r.output

    def test_unknown_creator_never_calls_delete(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: (200, _subs_payload()))
        r = _run(["subscribe", "remove", "查无此人"])
        assert r.exit_code == 0
        assert not [c for c in calls if c["method"] == "DELETE"]
        assert "没有匹配的创作者" in r.output

    def test_server_404_detail_shown(self, monkeypatch):
        """列表查得到、DELETE 才 404 —— 才算真测到了删除这一步。"""
        def handler(m, p, b):
            if m == "GET":
                return 200, _subs_payload()
            return 404, {"detail": "没有订阅这个创作者"}

        calls = _stub_api(monkeypatch, handler)
        r = _run(["subscribe", "remove", SEC_A])
        assert r.exit_code == 0
        assert [c for c in calls if c["method"] == "DELETE"]
        assert "HTTP 404" in r.output
        assert "没有订阅这个创作者" in r.output

    def test_json(self, monkeypatch):
        _stub_api(monkeypatch, _remove_handler)
        r = _run(["subscribe", "remove", SEC_A, "--json"])
        assert r.exit_code == 0
        assert json.loads(r.output) == {"ok": True, "sec_uid": SEC_A}


# ---------------------------------------------------------------- scope


def _scope_handler(method, path, body):
    if path.endswith("/scope"):
        return 200, {"ok": True,
                     "creator": {"sec_uid": SEC_A, "nickname": "博主甲",
                                 "download_scope": body["scope"],
                                 "scope_param": body["param"]}}
    return 200, _subs_payload()


class TestScope:
    def test_backfill_alias_posts_param(self, monkeypatch):
        calls = _stub_api(monkeypatch, _scope_handler)
        r = _run(["subscribe", "scope", "博主甲", "backfill", "5"])
        assert r.exit_code == 0
        post = calls[-1]
        assert post["path"] == f"/api/subscriptions/{SEC_A}/scope"
        assert post["body"] == {"scope": "backfill_n", "param": "5"}
        assert "新 + 往回补 5 个" in r.output

    def test_only_new_posts_empty_param(self, monkeypatch):
        calls = _stub_api(monkeypatch, _scope_handler)
        r = _run(["subscribe", "scope", "博主甲", "new"])
        assert r.exit_code == 0
        assert calls[-1]["body"] == {"scope": "only_new", "param": ""}

    def test_backfill_without_n_is_local_error(self, monkeypatch):
        calls = _stub_api(monkeypatch, _scope_handler)
        r = _run(["subscribe", "scope", "博主甲", "backfill"])
        assert r.exit_code == 0
        assert not [c for c in calls if c["body"]], "参数没校验就发出去了"
        assert "要给个数" in r.output

    @pytest.mark.parametrize("n", ["0", "10000"])
    def test_n_out_of_range(self, monkeypatch, n):
        calls = _stub_api(monkeypatch, _scope_handler)
        r = _run(["subscribe", "scope", "博主甲", "backfill", n])
        assert r.exit_code == 0
        assert not [c for c in calls if c["body"]]
        assert "1-9999" in r.output

    def test_n_on_scope_that_takes_none(self, monkeypatch):
        calls = _stub_api(monkeypatch, _scope_handler)
        r = _run(["subscribe", "scope", "博主甲", "all", "3", "--yes"])
        assert r.exit_code == 0
        assert not [c for c in calls if c["body"]]
        assert "不带个数" in r.output

    def test_unknown_scope_rejected_locally(self, monkeypatch):
        calls = _stub_api(monkeypatch, _scope_handler)
        r = _run(["subscribe", "scope", "博主甲", "since"])
        assert r.exit_code == 0
        assert not [c for c in calls if c["body"]]
        assert "only_new / backfill_n / all" in r.output

    def test_all_needs_confirmation_and_decline_sends_nothing(self, monkeypatch):
        calls = _stub_api(monkeypatch, _scope_handler)
        r = _run(["subscribe", "scope", "博主甲", "all"], input="n\n")
        assert r.exit_code == 0
        assert "全部历史作品" in r.output
        assert "已取消" in r.output
        assert not [c for c in calls if c["body"]]

    def test_all_with_yes_proceeds(self, monkeypatch):
        calls = _stub_api(monkeypatch, _scope_handler)
        r = _run(["subscribe", "scope", "博主甲", "all", "--yes"])
        assert r.exit_code == 0
        assert calls[-1]["body"] == {"scope": "all", "param": ""}
        assert "已取消" not in r.output

    def test_scope_server_error_passthrough(self, monkeypatch):
        def handler(m, p, b):
            if b is None:
                return 200, _subs_payload()
            return 400, {"detail": "往回补的个数要在 1-9999 之间"}

        _stub_api(monkeypatch, handler)
        r = _run(["subscribe", "scope", SEC_A, "backfill", "5"])
        assert r.exit_code == 0
        assert "HTTP 400" in r.output
        assert "1-9999" in r.output

    def test_json(self, monkeypatch):
        _stub_api(monkeypatch, _scope_handler)
        r = _run(["subscribe", "scope", "博主甲", "new", "--json"])
        assert r.exit_code == 0
        assert json.loads(r.output)["download_scope"] == "only_new"


# ---------------------------------------------------------------- check


def _check_payload(**over):
    data = {"sec_uid": SEC_A, "nickname": "博主甲", "baselined": False,
            "fetched": 20, "new_count": 3, "drift_blocked": 2, "queued": 3,
            "download": True, "task_ids": ["t1", "t2", "t3"],
            "message": "发现 3 个新作品，入队 3 个"}
    data.update(over)
    return data


def _check_handler(method, path, body):
    """GET 列表给订阅，POST check 给结果（不分路径会卡在解析那步）。"""
    if body is None:
        return 200, _subs_payload()
    return 200, _check_payload()


def _baseline_handler(method, path, body):
    if body is None:
        return 200, _subs_payload()
    return 200, _check_payload(baselined=True, new_count=0, queued=0,
                               drift_blocked=0, fetched=20,
                               message="已建立基线，40 个存量不下载")


def _login_required_handler(method, path, body):
    if body is None:
        return 200, _subs_payload()
    return 401, {"ok": False, "error": "登录态失效"}


def _all_scope_subs():
    return {"creators": [{"sec_uid": SEC_A, "nickname": "博主甲", "enabled": 1,
                          "download_scope": "all", "scope_param": "",
                          "last_checked": "", "works_count": 0}],
            "stats": {"creators": 1, "enabled": 1, "works_seen": 0}}


class TestCheck:
    def test_body_and_long_timeout(self, monkeypatch):
        calls = _stub_api(monkeypatch, _check_handler)
        r = _run(["subscribe", "check", "博主甲"])
        assert r.exit_code == 0
        post = calls[-1]
        assert post["path"] == f"/api/subscriptions/{SEC_A}/check"
        assert post["body"] == {"download": True, "max_new": 3}
        assert post["timeout"] == cli._API_TIMEOUT_LONG
        # 前面那次是解析用的 GET 列表
        assert calls[0]["method"] == "GET"
        assert calls[0]["path"] == "/api/subscriptions"

    def test_dry_run_turns_download_off(self, monkeypatch):
        calls = _stub_api(monkeypatch, _check_handler)
        r = _run(["subscribe", "check", "博主甲", "--dry-run", "--max-new", "0"])
        assert r.exit_code == 0
        assert calls[-1]["body"] == {"download": False, "max_new": 0}

    def test_renders_message_and_progress_hint(self, monkeypatch):
        _stub_api(monkeypatch, _check_handler)
        r = _run(["subscribe", "check", "博主甲"])
        assert r.exit_code == 0
        assert "发现 3 个新作品，入队 3 个" in r.output
        assert "抓到 20 个作品" in r.output
        assert "水位线拦下 2 个老作品" in r.output
        assert "queue list" in r.output

    def test_first_check_baseline_message(self, monkeypatch):
        _stub_api(monkeypatch, _baseline_handler)
        r = _run(["subscribe", "check", "博主甲"])
        assert "已建立基线，40 个存量不下载" in r.output

    def test_creator_set_to_all_requires_confirm(self, monkeypatch):
        def handler(m, p, b):
            if b is None:
                return 200, _all_scope_subs()
            return 200, _check_payload()

        calls = _stub_api(monkeypatch, handler)
        r = _run(["subscribe", "check", "博主甲"], input="n\n")
        assert r.exit_code == 0
        assert "全部历史作品" in r.output
        assert "已取消" in r.output
        assert not [c for c in calls if c["path"].endswith("/check")]

    def test_json(self, monkeypatch):
        _stub_api(monkeypatch, _check_handler)
        r = _run(["subscribe", "check", SEC_A, "--json"])
        assert r.exit_code == 0
        assert json.loads(r.output)["queued"] == 3

    def test_login_required(self, monkeypatch):
        _stub_api(monkeypatch, _login_required_handler)
        r = _run(["subscribe", "check", SEC_A])
        assert "登录态失效" in r.output
        assert "设置 → 登录抖音" in r.output


# ---------------------------------------------------------------- check-all


def _empty_round(**over):
    data = {"results": [], "total": 0, "queued": 0, "new_found": 0,
            "errors": 0, "needs_login": False, "rate_limited": False,
            "stopped_at": ""}
    data.update(over)
    return 200, data


class TestCheckAll:
    def test_scope_sent_as_null_when_not_overriding(self, monkeypatch):
        """不给 --scope 必须是 null 不是空串 —— 服务端拿空串会 400。"""
        calls = _stub_api(monkeypatch, lambda m, p, b: _empty_round())
        r = _run(["subscribe", "check-all"])
        assert r.exit_code == 0
        body = calls[-1]["body"]
        assert body["scope"] is None
        assert body["scope_param"] == ""
        assert body["download"] is True
        assert body["max_new"] == 3
        assert calls[-1]["path"] == "/api/subscriptions/check-all"
        assert calls[-1]["timeout"] == cli._API_TIMEOUT_LONG

    def test_scope_alias_and_param(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: _empty_round())
        r = _run(["subscribe", "check-all", "--scope", "backfill",
                  "--scope-param", "7", "--dry-run"])
        assert r.exit_code == 0
        assert calls[-1]["body"] == {"download": False, "max_new": 3,
                                     "scope": "backfill_n", "scope_param": "7"}

    @pytest.mark.parametrize("extra,expect", [
        (["--scope", "backfill"], "要配 --scope-param"),
        (["--scope", "backfill", "--scope-param", "0"], "1-9999"),
        (["--scope", "backfill", "--scope-param", "10000"], "1-9999"),
        (["--scope", "new", "--scope-param", "5"], "不带个数"),
        (["--scope", "weird"], "only_new / backfill_n / all"),
    ])
    def test_local_validation_blocks_request(self, monkeypatch, extra, expect):
        calls = _stub_api(monkeypatch, lambda m, p, b: _empty_round())
        r = _run(["subscribe", "check-all"] + extra)
        assert r.exit_code == 0
        assert not [c for c in calls if c["body"]], "校验没挡住，请求发出去了"
        assert expect in r.output

    def test_scope_all_needs_yes(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: _empty_round())
        r = _run(["subscribe", "check-all", "--scope", "all"], input="n\n")
        assert r.exit_code == 0
        assert not [c for c in calls if c["body"]]
        assert "已取消" in r.output

    def test_renders_table_and_summary(self, monkeypatch):
        payload = _empty_round(
            results=[
                {"sec_uid": SEC_A, "nickname": "博主甲", "new_count": 3,
                 "queued": 3, "message": "发现 3 个新作品，入队 3 个"},
                {"sec_uid": SEC_B, "nickname": "[MV]乙", "new_count": 0,
                 "queued": 0, "message": "没有新作品"},
                {"sec_uid": "x", "nickname": "坏人", "error": "抓主页失败"},
            ],
            total=3, queued=3, new_found=3, errors=1, stopped_at="坏人")
        _stub_api(monkeypatch, lambda m, p, b: payload)
        r = _run(["subscribe", "check-all"])
        assert r.exit_code == 0
        out = r.output
        assert "[MV]乙" in out
        assert "发现 3 个新作品，入队 3 个" in out
        assert "抓主页失败" in out
        assert "合计: 创作者 3 · 新发现 3 · 入队 3 · 失败 1" in out
        assert "本轮中断于 坏人" in out
        assert "queue list" in out

    def test_interrupt_flags_are_called_out(self, monkeypatch):
        """中断时「合计」行看着像正常跑完，必须显式喊出来。"""
        payload = _empty_round(
            results=[{"sec_uid": "x", "nickname": "甲", "error": "验证码中间页"}],
            total=3, errors=1, needs_login=True, rate_limited=True,
            stopped_at="甲")
        _stub_api(monkeypatch, lambda m, p, b: payload)
        r = _run(["subscribe", "check-all"])
        assert "撞了风控" in r.output
        assert "登录态失效" in r.output
        assert "设置 → 登录抖音" in r.output

    def test_skipped_round_is_not_reported_as_success(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (
            200, {"skipped": True, "reason": "backoff",
                  "message": "风控退避中，本轮跳过（还剩 8 分钟）"}))
        r = _run(["subscribe", "check-all"])
        assert r.exit_code == 0
        assert "本轮跳过" in r.output
        assert "合计" not in r.output

    def test_unexpected_error_shown(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, {"error": "意外炸了",
                                                      "results": []}))
        r = _run(["subscribe", "check-all"])
        assert "意外炸了" in r.output
        assert "合计" not in r.output

    def test_no_enabled_creators(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: _empty_round())
        r = _run(["subscribe", "check-all"])
        assert "没有启用中的订阅" in r.output

    def test_json(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, {"results": [], "total": 0}))
        r = _run(["subscribe", "check-all", "--json"])
        assert json.loads(r.output) == {"results": [], "total": 0}


# ---------------------------------------------------------------- poller


def _poller_handler(method, path, body):
    if body is None:
        return 200, _poller_payload()
    return 200, {"status": "ok", "settings": _poller_payload(),
                 "poller": _poller_payload()}


class TestPoller:
    def test_bare_command_shows_status(self, monkeypatch):
        calls = _stub_api(monkeypatch, _poller_handler)
        r = _run(["subscribe", "poller"])
        assert r.exit_code == 0
        assert calls[-1]["method"] == "GET"
        assert calls[-1]["path"] == "/api/subscriptions/poller"
        out = r.output
        assert "开关: 开启" in out
        assert "每 60 分钟一轮" in out
        assert "抖动 20%" in out
        assert "单轮最多入队 3 个" in out
        assert "启用中的订阅 2 个" in out
        assert "下次检查" in out
        assert "已跑 3 轮" in out

    def test_off_state_shown(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (
            200, _poller_payload(enabled=False, next_run_at="")))
        r = _run(["subscribe", "poller"])
        assert "开关: 关闭" in r.output
        assert "未排期" in r.output

    def test_daily_at_mode_shown(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (
            200, _poller_payload(mode="daily_at")))
        r = _run(["subscribe", "poller"])
        assert "每天 09:00 检查" in r.output

    def test_backoff_and_login_flag_shown(self, monkeypatch):
        from datetime import datetime, timedelta
        soon = (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
        _stub_api(monkeypatch, lambda m, p, b: (
            200, _poller_payload(backoff_until=soon, needs_login=True,
                                 running=True)))
        r = _run(["subscribe", "poller"])
        out = r.output
        assert "风控退避中" in out
        # 取整到分钟，执行瞬间可能是 29 也可能是 30，别把断言钉死在边界上
        assert "还剩约 " in out and " 分钟" in out
        assert "登录态失效" in out
        assert "有一轮检查正在跑" in out

    def test_expired_backoff_still_explained(self, monkeypatch):
        from datetime import datetime, timedelta
        past = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        _stub_api(monkeypatch, lambda m, p, b: (200, _poller_payload(backoff_until=past)))
        r = _run(["subscribe", "poller"])
        assert "退避已过期" in r.output
        assert "风控退避中" not in r.output

    def test_on_infers_mode_from_interval(self, monkeypatch):
        calls = _stub_api(monkeypatch, _poller_handler)
        r = _run(["subscribe", "poller", "on", "--interval", "45"])
        assert r.exit_code == 0
        post = [c for c in calls if c["method"] == "POST"][0]
        assert post["body"] == {"interval_minutes": 45, "mode": "interval",
                                "enabled": True}
        assert "自动轮询已开启" in r.output

    def test_on_infers_mode_from_daily_at(self, monkeypatch):
        calls = _stub_api(monkeypatch, _poller_handler)
        r = _run(["subscribe", "poller", "on", "--daily-at", "08:30"])
        assert r.exit_code == 0
        post = [c for c in calls if c["method"] == "POST"][0]
        assert post["body"] == {"daily_at": "08:30", "mode": "daily_at",
                                "enabled": True}

    def test_on_without_options_only_toggles(self, monkeypatch):
        calls = _stub_api(monkeypatch, _poller_handler)
        r = _run(["subscribe", "poller", "on"])
        assert r.exit_code == 0
        post = [c for c in calls if c["method"] == "POST"][0]
        assert post["body"] == {"enabled": True}

    def test_off_only_disables(self, monkeypatch):
        calls = _stub_api(monkeypatch, _poller_handler)
        r = _run(["subscribe", "poller", "off"])
        assert r.exit_code == 0
        post = [c for c in calls if c["method"] == "POST"][0]
        assert post["body"] == {"enabled": False}
        assert "自动轮询已关闭" in r.output

    def test_set_never_touches_enabled(self, monkeypatch):
        calls = _stub_api(monkeypatch, _poller_handler)
        r = _run(["subscribe", "poller", "set", "--max-new", "10",
                  "--jitter", "30"])
        assert r.exit_code == 0
        post = [c for c in calls if c["method"] == "POST"][0]
        assert post["body"] == {"max_new_per_check": 10, "jitter_percent": 30}
        assert "enabled" not in post["body"]
        assert "轮询配置已更新" in r.output

    def test_set_with_no_options_is_usage_error(self, monkeypatch):
        calls = _stub_api(monkeypatch, _poller_handler)
        r = _run(["subscribe", "poller", "set"])
        assert r.exit_code != 0
        assert not [c for c in calls if c["method"] == "POST"]

    def test_both_daily_at_and_interval_need_explicit_mode(self, monkeypatch):
        calls = _stub_api(monkeypatch, _poller_handler)
        r = _run(["subscribe", "poller", "set", "--daily-at", "09:00",
                  "--interval", "60"])
        assert r.exit_code != 0
        assert not [c for c in calls if c["method"] == "POST"]

    def test_explicit_mode_allows_both(self, monkeypatch):
        calls = _stub_api(monkeypatch, _poller_handler)
        r = _run(["subscribe", "poller", "set", "--mode", "daily_at",
                  "--daily-at", "09:00", "--interval", "60"])
        assert r.exit_code == 0
        post = [c for c in calls if c["method"] == "POST"][0]
        assert post["body"] == {"daily_at": "09:00", "interval_minutes": 60,
                                "mode": "daily_at"}

    def test_server_error_shown(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (
            500, {"detail": "更新失败：配置文件只读"}))
        r = _run(["subscribe", "poller", "off"])
        assert r.exit_code == 0
        assert "HTTP 500" in r.output
        assert "配置文件只读" in r.output
