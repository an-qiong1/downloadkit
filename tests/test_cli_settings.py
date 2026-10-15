#!/usr/bin/env python3
"""CLI 设置命令（settings 命令组）回归

2026-10-15 P5-6：配置文件在**服务进程**的 HOME 下，CLI 自己写会写到另一份
配置；而且有些项保存后是服务进程当场改内存的（history_max_records 保存时
就 update_max_records），直连模块只会弄出「文件改了、内存还是老值」的分裂，
所以照旧走 HTTP。

三个从服务端契约里挖出来的硬约束（都写成了测试）：

  - `/api/settings/update` 的请求模型只声明了 general/proxy/cookie，
    **传 subscription 它照样回 {"status": "ok"} 却什么都没写** —— 假成功，
    必须本地拦下并指向 `subscribe poller`
  - `proxy.mode` 写非三态值会被 `resolve_mode` 静默忽略（设了等于没设）
  - `general.max_concurrent < 1` 会在下次启动造出 `asyncio.Semaphore(0)`，
    所有下载一起卡死

本文件覆盖：

  - get：全量列出（段名.键名 可直接喂回 set）、单键只回值、裸键唯一归属 /
    多义列候选、proxy.mode 缺省按服务端同一套推导回显、配置里的历史遗留键
    不被藏起来、--json 原样返回、系统代理探测行
  - set：按默认值类型解析（bool 认 on/off/1/0）、范围与界面同款、proxy.mode
    收口、下载目录先过服务端校验且校验不过就不写、回执比对服务端实际存的值
  - proxy-test：服务端永远 200，通不通由 body 的 ok 决定 → 退出码 0/1
"""

import json
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

import downloadkit.cli as cli


DEFAULT_SERVER = "http://127.0.0.1:8765"


@pytest.fixture(autouse=True)
def _reset_server(monkeypatch):
    """每个用例把 _SERVER 拨回默认，防 --server 用例污染后续。"""
    monkeypatch.setattr(cli, "_SERVER", DEFAULT_SERVER)


def _run(args, input=None):
    return CliRunner().invoke(cli.main, args, input=input,
                              catch_exceptions=False)


def _stub_api(monkeypatch, handler):
    """把 cli._queue_api 换成记录调用的替身；记录 method/path/body/kw。"""
    calls = []

    def stub(method, path, body=None, **kw):
        calls.append({"method": method, "path": path, "body": body, **kw})
        return handler(method, path, body)

    monkeypatch.setattr(cli, "_queue_api", stub)
    return calls


def _run_with_stub(monkeypatch, args, handler=None):
    """起一个默认返回正常配置的替身，再跑命令（给用法错误类用例用）。"""
    _stub_api(monkeypatch, handler or (lambda m, p, b: (200, _get_payload())))
    return _run(args)


def _cfg(**over):
    """一份贴近真实的配置（四段齐全，proxy 里**故意不放 mode**）。"""
    cfg = {
        "general": {
            "download_dir": "~/Downloads/DownloadKit",
            "download_dir_music": "~/Downloads/DownloadKit/music",
            "download_dir_video": "~/Downloads/DownloadKit/videos",
            "download_dir_animated": "~/Downloads/DownloadKit/animated",
            "download_dir_images": "~/Downloads/DownloadKit/images",
            "max_concurrent": 3,
            "log_level": "INFO",
            "language": "zh-CN",
            "history_max_records": 1000,
            "rename_strategy": "skip",
            "motion_photo_default": True,
            "close_to_tray": False,
        },
        "proxy": {
            "enabled": True,
            "global": "",
            "youtube": "",
            "douyin": "",
            "bilibili": "",
            "xiaohongshu": "",
        },
        "cookie": {"douyin_path": "", "bilibili_path": ""},
        "subscription": {
            "enabled": False,
            "interval_minutes": 60,
            "max_new_per_check": 3,
            "jitter_percent": 20,
        },
    }
    for sec, vals in over.items():
        cfg[sec] = {**cfg.get(sec, {}), **vals}
    return cfg


def _get_payload(**over):
    sys_proxy = over.pop("proxy_system", "")
    settings = over.pop("settings", _cfg(**over))
    return {"settings": settings, "proxy_system": sys_proxy}


def _update_payload(cfg=None):
    return {"status": "ok", "settings": cfg if cfg is not None else _cfg()}


def _ok_dir(path_input=""):
    return 200, {"ok": True, "absolute": "C:\\dl", "exists": True,
                 "writable": True, "message": "OK", "input": path_input}


def _listing(output):
    """把全量列出解析成 {键: 值}。

    键名是左对齐补空格的（最长的 subscription.max_new_per_check 有 30 列），
    直接拿 `general.max_concurrent = 3` 这种整串去 in 断言必然失配 ——
    参照 probe_settings.py 实测：对齐后是
    `general.max_concurrent         = 3`。所以按 ` = ` 切开再 strip。
    """
    out = {}
    for line in output.splitlines():
        if line.startswith(("系统", "Usage", "Try", "Error", "#")):
            continue
        key, sep, value = line.partition(" = ")
        if sep:
            out[key.strip()] = value.strip()
    return out


# ============================ get ============================

def test_get_is_get_request(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _get_payload()))
    r = _run(["settings", "get"])
    assert r.exit_code == 0
    assert calls[0]["method"] == "GET"
    assert calls[0]["path"] == "/api/settings/get"
    assert calls[0]["body"] is None


def test_get_lists_every_schema_key(monkeypatch):
    """全量列出必须覆盖键表里每一项，漏一项等于那项在命令行里不存在。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, _get_payload()))
    r = _run(["settings", "get"])
    assert r.exit_code == 0
    for full in (f"{sec}.{name}"
                 for sec, names in cli._setting_schema().items()
                 for name in names):
        assert full in r.output, full


def test_get_key_value_form_is_reusable(monkeypatch):
    """打出来的形状必须能原样喂回 `settings set`（键名.键值成对可解析）。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, _get_payload()))
    r = _run(["settings", "get"])
    items = _listing(r.output)
    assert items["general.max_concurrent"] == "3"
    assert "cookie.douyin_path" in items


def test_get_bool_lowercased(monkeypatch):
    """true/false 正是 set 认得的写法，别吐 True/False 让人改一遍。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, _get_payload()))
    r = _run(["settings", "get"])
    items = _listing(r.output)
    assert items["general.motion_photo_default"] == "true"
    assert items["general.close_to_tray"] == "false"
    assert items["subscription.enabled"] == "false"
    assert "True" not in r.output and "False" not in r.output


def test_get_single_key_value_only(monkeypatch):
    """单键模式是给管道用的，除了值不能有别的东西。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, _get_payload()))
    r = _run(["settings", "get", "general.download_dir"])
    assert r.exit_code == 0
    assert r.output == "~/Downloads/DownloadKit\n"


def test_get_single_key_long_value_not_folded(monkeypatch):
    """长路径过 rich 会被 80 列切断，那就不叫原值了。"""
    long_path = "D:\\" + "\\".join(f"很长的目录{i}" for i in range(12))
    _stub_api(monkeypatch, lambda m, p, b: (
        200, _get_payload(general={"download_dir": long_path})))
    r = _run(["settings", "get", "general.download_dir"])
    assert r.output == long_path + "\n"


def test_get_bare_key_unique_match(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (200, _get_payload()))
    r = _run(["settings", "get", "download_dir"])
    assert r.exit_code == 0
    assert r.output == "~/Downloads/DownloadKit\n"


def test_get_bare_key_ambiguous_lists_sections(monkeypatch):
    """enabled 挂在 proxy / subscription 两段下，猜哪一段都可能改错开关。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, _get_payload()))
    r = _run(["settings", "get", "enabled"])
    assert r.exit_code == 2
    err = r.stderr or ""
    assert "proxy" in err and "subscription" in err
    assert "general" not in err          # general 段并没有 enabled，不该被列进来
    assert "段名.enabled" in err


def test_get_unknown_key_exit_2(monkeypatch):
    r = _run_with_stub(monkeypatch, ["settings", "get", "general.nope"])
    assert r.exit_code == 2
    assert "settings get" in (r.stderr or "")


def test_get_legacy_key_not_in_schema(monkeypatch):
    """配置里有、键表里没登记的键，单键模式也得能查出来，别藏一半。"""
    _stub_api(monkeypatch, lambda m, p, b: (
        200, _get_payload(general={"legacy_thing": "hello"})))
    r = _run(["settings", "get", "general.legacy_thing"])
    assert r.exit_code == 0
    assert r.output == "hello\n"


def test_get_proxy_mode_derived_when_absent(monkeypatch):
    """配置里没写 mode 时回显推导值，并注明它不是文件里读到的。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, _get_payload()))
    r = _run(["settings", "get", "proxy.mode"])
    assert r.exit_code == 0
    assert r.output == "system\n"      # enabled=true 且全空 → system


def test_get_proxy_mode_annotated_in_full_listing(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (200, _get_payload()))
    r = _run(["settings", "get"])
    items = _listing(r.output)
    assert items["proxy.mode"] == "system  # 未显式设置，按 enabled/地址推导"


def test_get_proxy_mode_explicit_not_annotated(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (
        200, _get_payload(proxy={"mode": "manual"})))
    r = _run(["settings", "get"])
    items = _listing(r.output)
    assert items["proxy.mode"] == "manual"
    assert "未显式设置" not in r.output


def test_get_shows_keys_missing_from_schema(monkeypatch):
    """配置里的历史遗留键不能因为键表没登记就消失。"""
    _stub_api(monkeypatch, lambda m, p, b: (
        200, _get_payload(general={"legacy_thing": "hello"})))
    r = _run(["settings", "get"])
    assert "general.legacy_thing" in r.output
    assert "hello" in r.output


def test_get_json_raw_payload(monkeypatch):
    payload = _get_payload(proxy_system="http://127.0.0.1:7890")
    _stub_api(monkeypatch, lambda m, p, b: (200, payload))
    r = _run(["settings", "get", "--json"])
    assert r.exit_code == 0
    assert json.loads(r.output) == payload


def test_get_json_wins_over_key(monkeypatch):
    payload = _get_payload()
    _stub_api(monkeypatch, lambda m, p, b: (200, payload))
    r = _run(["settings", "get", "general.log_level", "--json"])
    assert json.loads(r.output) == payload


def test_get_system_proxy_line(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (
        200, _get_payload(proxy_system="http://127.0.0.1:7890")))
    r = _run(["settings", "get"])
    assert "系统代理探测：http://127.0.0.1:7890" in r.output


def test_get_system_proxy_empty(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (200, _get_payload()))
    r = _run(["settings", "get"])
    assert "系统代理探测：未检测到" in r.output


def test_get_offline_exit_1(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务"))
    r = _run(["settings", "get"])
    assert r.exit_code == 1
    assert "连不上服务" in r.output


def test_get_http_error_exit_1(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (500, {"detail": "炸了"}))
    r = _run(["settings", "get"])
    assert r.exit_code == 1
    assert "失败（HTTP 500）: 炸了" in r.output


def test_get_http_error_json(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (500, {"detail": "炸了"}))
    r = _run(["settings", "get", "--json"])
    assert r.exit_code == 1
    assert json.loads(r.output) == {"error": "HTTP 500: 炸了"}


# ============================ set ============================

def test_set_int_body_and_confirmation(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (
        200, _update_payload(_cfg(general={"max_concurrent": 5}))))
    r = _run(["settings", "set", "general.max_concurrent", "5"])
    assert r.exit_code == 0
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"] == "/api/settings/update"
    assert calls[0]["body"] == {"general": {"max_concurrent": 5}}
    assert "general.max_concurrent" in r.output
    assert "= 5" in r.output


def test_set_only_sends_one_key(monkeypatch):
    """整段提交会把同段没提到的键一起覆盖掉，必须只带这一个键。"""
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _update_payload()))
    _run(["settings", "set", "general.log_level", "DEBUG"])
    assert list(calls[0]["body"].keys()) == ["general"]
    assert calls[0]["body"]["general"] == {"log_level": "DEBUG"}


@pytest.mark.parametrize("raw,expected", [
    ("true", True), ("on", True), ("1", True), ("yes", True), ("TRUE", True),
    ("false", False), ("off", False), ("0", False), ("no", False),
])
def test_set_bool_accepted_forms(monkeypatch, raw, expected):
    calls = _stub_api(monkeypatch, lambda m, p, b: (
        200, _update_payload(_cfg(general={"close_to_tray": expected}))))
    r = _run(["settings", "set", "general.close_to_tray", raw])
    assert r.exit_code == 0, r.output
    assert calls[0]["body"] == {"general": {"close_to_tray": expected}}


def test_set_bool_string_is_not_bool(monkeypatch):
    """bool("false") 是 True——写成字符串等于把开关悄悄反了。"""
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _update_payload()))
    r = _run(["settings", "set", "general.close_to_tray", "falsey"])
    assert r.exit_code == 2
    assert calls == []
    assert "是开关" in (r.stderr or "")


def test_set_bad_int(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _update_payload()))
    r = _run(["settings", "set", "general.max_concurrent", "abc"])
    assert r.exit_code == 2
    assert calls == []
    assert "是整数" in (r.stderr or "")


def test_set_max_concurrent_zero_rejected(monkeypatch):
    """0 会在下次启动造出 asyncio.Semaphore(0)，所有下载一起卡死。"""
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _update_payload()))
    r = _run(["settings", "set", "general.max_concurrent", "0"])
    assert r.exit_code == 2
    assert calls == []
    assert "1~10" in (r.stderr or "")


def test_set_max_concurrent_over_limit_rejected(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _update_payload()))
    r = _run(["settings", "set", "general.max_concurrent", "11"])
    assert r.exit_code == 2
    assert calls == []


def test_set_history_records_range_matches_ui(monkeypatch):
    """界面 min/max 是 100~100000，命令行不另立一套。"""
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _update_payload()))
    r = _run(["settings", "set", "general.history_max_records", "50"])
    assert r.exit_code == 2
    assert calls == []
    assert "100~100000" in (r.stderr or "")


def test_set_proxy_mode_valid(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (
        200, _update_payload(_cfg(proxy={"mode": "manual"}))))
    r = _run(["settings", "set", "proxy.mode", "manual"])
    assert r.exit_code == 0
    assert calls[0]["body"] == {"proxy": {"mode": "manual"}}


def test_set_proxy_mode_invalid_rejected(monkeypatch):
    """resolve_mode 只认三态，写别的值会被静默忽略 = 设了等于没设。"""
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _update_payload()))
    r = _run(["settings", "set", "proxy.mode", "auto"])
    assert r.exit_code == 2
    assert calls == []
    assert "三态" in (r.stderr or "")


def test_set_str_passthrough(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (
        200, _update_payload(_cfg(proxy={"global": "http://1.2.3.4:8080"}))))
    r = _run(["settings", "set", "proxy.global", "http://1.2.3.4:8080"])
    assert r.exit_code == 0
    assert calls[0]["body"] == {"proxy": {"global": "http://1.2.3.4:8080"}}


def test_set_empty_string_clears(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (
        200, _update_payload(_cfg(cookie={"douyin_path": ""}))))
    r = _run(["settings", "set", "cookie.douyin_path", ""])
    assert r.exit_code == 0
    assert calls[0]["body"] == {"cookie": {"douyin_path": ""}}


def test_set_subscription_rejected_without_request(monkeypatch):
    """/api/settings/update 不收 subscription，只传它会回 ok 却不写。"""
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _update_payload()))
    r = _run(["settings", "set", "subscription.interval_minutes", "30"])
    assert r.exit_code == 2
    assert calls == []
    err = r.stderr or ""
    assert "不走 settings set" in err
    assert "subscribe poller" in err


def test_set_ambiguous_bare_key(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _update_payload()))
    r = _run(["settings", "set", "enabled", "true"])
    assert r.exit_code == 2
    assert calls == []


def test_set_unknown_key(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _update_payload()))
    r = _run(["settings", "set", "general.nope", "1"])
    assert r.exit_code == 2
    assert calls == []


def test_set_download_dir_validates_first(monkeypatch):
    """先问目录能不能用，再写配置——顺序反了就写进了个用不了的路径。"""
    calls = _stub_api(monkeypatch, lambda m, p, b: (
        _ok_dir() if "download-dir-info" in p
        else (200, _update_payload(_cfg(general={"download_dir": "D:\\new"})))))
    r = _run(["settings", "set", "general.download_dir", "D:\\new"])
    assert r.exit_code == 0
    assert len(calls) == 2
    assert calls[0]["method"] == "GET"
    assert calls[0]["path"].startswith("/api/settings/download-dir-info?")
    # 反斜杠会被 urlencode 转义，按解码后的值断言，别把转义当路径
    assert parse_qs(urlsplit(calls[0]["path"]).query) == {"path": ["D:\\new"]}
    assert calls[1]["path"] == "/api/settings/update"
    assert calls[1]["body"] == {"general": {"download_dir": "D:\\new"}}


def test_set_download_dir_bad_refuses_to_write(monkeypatch):
    """目录不可用就必须一个 update 都不发，否则配置指向了废路径。"""
    calls = _stub_api(monkeypatch, lambda m, p, b: (
        200, {"ok": False, "absolute": "", "exists": False, "writable": False,
              "message": "无法创建目录：磁盘已满", "input": "D:\\x"})
        if "download-dir-info" in p else (200, _update_payload()))
    r = _run(["settings", "set", "general.download_dir", "D:\\x"])
    assert r.exit_code == 1
    assert len(calls) == 1
    assert "无法创建目录" in r.output
    assert "没有保存" in r.output


def test_set_non_dir_key_skips_validation(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _update_payload()))
    r = _run(["settings", "set", "general.log_level", "DEBUG"])
    assert r.exit_code == 0
    assert len(calls) == 1
    assert calls[0]["path"] == "/api/settings/update"


def test_set_reports_stored_value_from_response(monkeypatch):
    """回执读服务端返回的实际值，不是把自己刚发的再念一遍。"""
    _stub_api(monkeypatch, lambda m, p, b: (
        200, _update_payload(_cfg(general={"log_level": "DEBUG"}))))
    r = _run(["settings", "set", "general.log_level", "DEBUG"])
    assert r.exit_code == 0
    assert "general.log_level = DEBUG" in r.output


def test_set_warns_when_stored_differs(monkeypatch):
    """服务端存的和提交的对不上时不能喊成功。"""
    _stub_api(monkeypatch, lambda m, p, b: (
        200, _update_payload(_cfg(general={"log_level": "INFO"}))))
    r = _run(["settings", "set", "general.log_level", "DEBUG"])
    assert r.exit_code == 0
    assert "已提交，但服务端存的是 INFO" in r.output
    assert "✓" not in r.output


def test_set_offline_exit_1(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务"))
    r = _run(["settings", "set", "general.log_level", "DEBUG"])
    assert r.exit_code == 1
    assert "连不上服务" in r.output


def test_set_http_error(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (500, {"detail": "炸了"}))
    r = _run(["settings", "set", "general.log_level", "DEBUG"])
    assert r.exit_code == 1
    assert "失败（HTTP 500）: 炸了" in r.output


def test_every_updatable_key_settable(monkeypatch):
    """键表里 general/proxy/cookie 的每一项都得能设进去，漏一项就是死键。"""
    schema = cli._setting_schema()
    for sec, names in schema.items():
        if sec not in cli._UPDATABLE_SECTIONS:
            continue
        for name, default in names.items():
            if isinstance(default, bool):
                raw = "true" if default else "false"
            else:
                raw = str(default)
            calls = _stub_api(monkeypatch, lambda m, p, b: (
                _ok_dir() if "download-dir-info" in p
                else (200, _update_payload())))
            r = _run(["settings", "set", f"{sec}.{name}", raw])
            assert r.exit_code == 0, f"{sec}.{name}: {r.output}"
            upd = [c for c in calls if c["path"] == "/api/settings/update"]
            assert upd and upd[0]["body"] == {sec: {name: default}}, \
                f"{sec}.{name}: {upd}"


# ========================= proxy-test =========================

def _proxy_payload(ok=True, **over):
    d = {"ok": ok, "latency_ms": 23,
         "message": "连接成功（HTTP 200），延迟 23 ms"}
    if not ok:
        d = {"ok": False, "latency_ms": 10001,
             "message": "连接超时（10 秒无响应），代理地址或端口可能不对"}
    d.update(over)
    return d


def test_proxy_test_posts_both_fields_empty_by_default(monkeypatch):
    """不传 --url 就让服务端用自己的默认目标（公网），本地不替它挑。"""
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _proxy_payload()))
    r = _run(["settings", "proxy-test"])
    assert r.exit_code == 0
    assert calls[0]["path"] == "/api/proxy/test"
    assert calls[0]["body"] == {"proxy": "", "url": ""}


def test_proxy_test_ok_exit_0(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (200, _proxy_payload()))
    r = _run(["settings", "proxy-test"])
    assert r.exit_code == 0
    assert "连接成功（HTTP 200），延迟 23 ms" in r.output
    assert "✓" in r.output


def test_proxy_test_args_passed_through(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _proxy_payload()))
    r = _run(["settings", "proxy-test", "http://127.0.0.1:7890",
              "--url", "http://127.0.0.1:9000/"])
    assert r.exit_code == 0
    assert calls[0]["body"] == {"proxy": "http://127.0.0.1:7890",
                                "url": "http://127.0.0.1:9000/"}


def test_proxy_test_server_200_but_not_ok_exit_1(monkeypatch):
    """服务端永远 200，「代理不通」是测试结果不是故障 → 退出码定成败。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, _proxy_payload(ok=False)))
    r = _run(["settings", "proxy-test", "http://127.0.0.1:7890"])
    assert r.exit_code == 1
    assert "连接超时" in r.output
    assert "✗" in r.output


def test_proxy_test_json_ok(monkeypatch):
    payload = _proxy_payload()
    _stub_api(monkeypatch, lambda m, p, b: (200, payload))
    r = _run(["settings", "proxy-test", "--json"])
    assert r.exit_code == 0
    assert json.loads(r.output) == payload


def test_proxy_test_json_fail_exit_1(monkeypatch):
    payload = _proxy_payload(ok=False)
    _stub_api(monkeypatch, lambda m, p, b: (200, payload))
    r = _run(["settings", "proxy-test", "--json"])
    assert r.exit_code == 1
    assert json.loads(r.output) == payload


def test_proxy_test_offline_exit_1(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务"))
    r = _run(["settings", "proxy-test"])
    assert r.exit_code == 1
    assert "连不上服务" in r.output


def test_proxy_test_offline_json(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务"))
    r = _run(["settings", "proxy-test", "--json"])
    assert r.exit_code == 1
    assert json.loads(r.output) == {"error": "连不上服务"}


def test_proxy_test_http_error(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (500, {"detail": "炸了"}))
    r = _run(["settings", "proxy-test"])
    assert r.exit_code == 1
    assert "失败（HTTP 500）: 炸了" in r.output


# ============================ 组 ============================

def test_bare_settings_is_usage_error():
    """缺子命令 → exit 2，和 queue/files/bookmarks 一致。"""
    r = _run(["settings"])
    assert r.exit_code == 2


def test_settings_help_lists_all_commands():
    r = _run(["settings", "--help"])
    assert r.exit_code == 0
    for name in ("get", "set", "proxy-test"):
        assert name in r.output


def test_proxy_test_help_documents_exit_codes():
    r = _run(["settings", "proxy-test", "--help"])
    assert r.exit_code == 0
    # click 按 80 列折行，可能把「0 = 通，1 = 不通」从中间切开，先折行再找
    flat = " ".join(r.output.split())
    assert "0 = 通，1 = 不通" in flat
    assert "--url" in flat


def test_set_help_points_at_poller_for_subscription():
    r = _run(["settings", "set", "--help"])
    assert r.exit_code == 0
    assert "段名.键名" in r.output
