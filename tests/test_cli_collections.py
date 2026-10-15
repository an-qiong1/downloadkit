#!/usr/bin/env python3
"""CLI 收藏歌单命令（collections 命令组）回归

2026-10-15 P5-7：歌单缓存在**服务端**的 ~/.downloadkit/collections.db，
而且 add / refresh 都会真去解析歌单（网络 + 各平台适配器）。CLI 自己再实现
一遍就是两套解析逻辑，两边对不上时谁也说不清哪个是真的，所以走 HTTP。

退出码约定（写在 `_coll_api` 的 docstring 里）：本组是状态查询与数据管理，
「歌单不存在」「歌单解析失败」是**业务结果**而不是「没做成该做的事」，所以
沿用 queue / subscribe / files 的约定——提示完 return，退出码仍是 0；只有
用法错误才是 2。和 sniff / bookmarks / proxy-test 那组探测器的「没抓到就 1」
不混用。

三个从服务端契约里挖出来的点：

  - 歌单 ID 直接拼进 /api/collections/{id}，非数字会打到 FastAPI 匹配不上
    的路径回 404 —— 用户会以为「歌单不存在」，其实是自己 ID 敲错了，必须
    本地拦下并区分这两种情况
  - `rm` 是逐个 DELETE（没有批量端点），所以要先 GET 列表把 ID 换成
    「ID + 名称」再确认；让人对着一个干巴巴的 ID 确认是逼他记错
  - `list` 的表格**不放 URL**：网易云歌单链接动辄 60+ 字符，塞进去会把名称
    列挤没，而真正要复制给别的命令的是 ID；歌单链接本身走 click.echo 不走
    console.print（m3u8 那次的教训，长地址过 rich 会被从中间折断）

本文件覆盖：list（空/有/JSON/长 URL 不进表格）、show（截断/404/非整数 ID）、
add（重复收藏/解析失败/空链接）、rename、rm（确认/部分不存在/去重/全不存在）、
refresh（逐个进行/单个失败继续）、组级用法错误。
"""
import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

import downloadkit.cli as cli


DEFAULT_SERVER = "http://127.0.0.1:8765"
LONG_URL = "https://music.163.com/#/playlist?id=999999999999999999"


@pytest.fixture(autouse=True)
def _reset_server(monkeypatch):
    """每个用例把 _SERVER 拨回默认，防 --server 用例污染后续。"""
    monkeypatch.setattr(cli, "_SERVER", DEFAULT_SERVER)


def _run(args, input=None):
    return CliRunner().invoke(cli.main, args, input=input,
                              catch_exceptions=False)


def _stub_api(monkeypatch, handler):
    """把 cli._queue_api 换成记录调用的替身；记录 method/path/body。"""
    calls = []

    def stub(method, path, body=None, **kw):
        calls.append({"method": method, "path": path, "body": body})
        return handler(method, path, body)

    monkeypatch.setattr(cli, "_queue_api", stub)
    return calls


def _row(cid, **over):
    d = {"id": cid, "name": "我的歌单", "url": LONG_URL, "platform": "netease",
         "song_count": 3, "auto_name": 1,
         "created_at": "2026-10-15 10:00:00",
         "refreshed_at": "2026-10-15 12:00:00"}
    d.update(over)
    return d


def _tracks(n=3):
    return [{"id": i, "title": f"曲目{i}", "artist": f"歌手{i}", "album": "专辑A",
             "song_id": f"sid{i}", "platform": "netease", "sort_order": i - 1}
            for i in range(1, n + 1)]


def _detail(cid, tracks=None, **over):
    d = _row(cid, **over)
    d["tracks"] = _tracks() if tracks is None else tracks
    return d


def _rows(*cids):
    return [_row(c) for c in cids]


# ============================ list ============================

def test_list_is_get_request(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, []))
    r = _run(["collections", "list"])
    assert r.exit_code == 0
    assert calls[0]["method"] == "GET"
    assert calls[0]["path"] == "/api/collections"


def test_list_empty_is_not_an_error(monkeypatch):
    """查到空状态也算查成功 —— 和 queue / subscribe 一致。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, []))
    r = _run(["collections", "list"])
    assert r.exit_code == 0
    assert "还没有收藏歌单" in r.output
    assert "collections add" in r.output


def test_list_shows_id_name_platform_count(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (200, _rows(1, 2)))
    r = _run(["collections", "list"])
    assert r.exit_code == 0
    for needle in ("1", "2", "我的歌单", "netease", "3"):
        assert needle in r.output, needle
    assert "共 2 个" in r.output


def test_list_url_stays_out_of_table(monkeypatch):
    """长 URL 塞进表格会把名称列挤没；要完整字段走 --json。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, _rows(1)))
    r = _run(["collections", "list"])
    assert LONG_URL not in r.output
    r = _run(["collections", "list", "--json"])
    assert LONG_URL in r.output


def test_list_json_raw_payload(monkeypatch):
    payload = _rows(1, 2)
    _stub_api(monkeypatch, lambda m, p, b: (200, payload))
    r = _run(["collections", "list", "--json"])
    assert r.exit_code == 0
    assert json.loads(r.output) == payload


def test_list_offline_stays_exit_0(monkeypatch):
    """状态查询组：连不上也只提示，退出码仍是 0。

    （`--server` 指引那段文案是 _queue_api 出的，替身把它整个换掉了，
    那条归 P5-2 的测试管，这里只验退出码与提示。）
    """
    _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务"))
    r = _run(["collections", "list"])
    assert r.exit_code == 0
    assert "连不上服务" in r.output


def test_list_http_error_stays_exit_0(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (500, {"detail": "炸了"}))
    r = _run(["collections", "list"])
    assert r.exit_code == 0
    assert "失败（HTTP 500）: 炸了" in r.output


def test_list_http_error_json(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (500, {"detail": "炸了"}))
    r = _run(["collections", "list", "--json"])
    assert r.exit_code == 0
    assert json.loads(r.output) == {"error": "HTTP 500: 炸了"}


# ============================ show ============================

def test_show_gets_detail(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _detail(1)))
    r = _run(["collections", "show", "1"])
    assert r.exit_code == 0
    assert calls[0]["method"] == "GET"
    assert calls[0]["path"] == "/api/collections/1"


def test_show_lists_tracks(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (200, _detail(1)))
    r = _run(["collections", "show", "1"])
    assert r.exit_code == 0
    for needle in ("曲目1", "曲目2", "曲目3", "歌手1", "专辑A"):
        assert needle in r.output, needle
    assert "3 首" in r.output


def test_show_limit_truncates(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (200, _detail(1)))
    r = _run(["collections", "show", "1", "-n", "2"])
    assert r.exit_code == 0
    assert "曲目1" in r.output and "曲目2" in r.output
    assert "曲目3" not in r.output
    assert "只显示前 2 首" in r.output


def test_show_limit_zero_shows_all(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (200, _detail(1, _tracks(6))))
    r = _run(["collections", "show", "1", "-n", "0"])
    assert "曲目6" in r.output
    assert "只显示前" not in r.output


def test_show_url_echoed_not_folded(monkeypatch):
    """歌单链接走 click.echo——rich 按 80 列会把长地址从中间切断。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, _detail(1)))
    r = _run(["collections", "show", "1"])
    assert r.output.splitlines()[-1] == LONG_URL


def test_show_empty_tracks(monkeypatch):
    """缓存曲目为空也算查到了，不是错误。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, _detail(1, tracks=[])))
    r = _run(["collections", "show", "1"])
    assert r.exit_code == 0
    assert "0 首" in r.output


def test_show_not_found_stays_exit_0(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (404, {"detail": "收藏歌单不存在"}))
    r = _run(["collections", "show", "999"])
    assert r.exit_code == 0
    assert "收藏歌单不存在" in r.output


def test_show_json(monkeypatch):
    payload = _detail(1)
    _stub_api(monkeypatch, lambda m, p, b: (200, payload))
    r = _run(["collections", "show", "1", "--json"])
    assert r.exit_code == 0
    assert json.loads(r.output) == payload


def test_show_non_int_id_exit_2_without_request(monkeypatch):
    """非整数 ID 会被 FastAPI 当成匹配不上的路径回 404，
    用户会以为歌单不存在 —— 本地就得拦下。"""
    calls = _stub_api(monkeypatch, lambda m, p, b: (404, {"detail": "x"}))
    r = _run(["collections", "show", "abc"])
    assert r.exit_code == 2
    assert calls == []
    assert "必须是整数" in (r.stderr or "")


def test_show_offline_stays_exit_0(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务"))
    r = _run(["collections", "show", "1"])
    assert r.exit_code == 0
    assert "连不上服务" in r.output


# ============================ add ============================

def test_add_posts_url(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _detail(7)))
    r = _run(["collections", "add", LONG_URL])
    assert r.exit_code == 0
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"] == "/api/collections"
    assert calls[0]["body"] == {"url": LONG_URL, "name": ""}


def test_add_with_name(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _detail(7, name="睡前循环")))
    r = _run(["collections", "add", LONG_URL, "-n", "睡前循环"])
    assert r.exit_code == 0
    assert calls[0]["body"] == {"url": LONG_URL, "name": "睡前循环"}
    assert "睡前循环" in r.output and "7" in r.output


def test_add_reports_track_count(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (200, _detail(7, _tracks(5))))
    r = _run(["collections", "add", LONG_URL])
    assert "5 首" in r.output


def test_add_duplicate_stays_exit_0(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (
        400, {"detail": "该歌单已收藏（ID: 3），请勿重复添加"}))
    r = _run(["collections", "add", LONG_URL])
    assert r.exit_code == 0
    assert "该歌单已收藏" in r.output


def test_add_parse_failed_stays_exit_0(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (
        400, {"detail": "歌单解析失败: 模拟的解析错误"}))
    r = _run(["collections", "add", LONG_URL])
    assert r.exit_code == 0
    assert "歌单解析失败" in r.output


def test_add_json(monkeypatch):
    payload = _detail(7)
    _stub_api(monkeypatch, lambda m, p, b: (200, payload))
    r = _run(["collections", "add", LONG_URL, "--json"])
    assert json.loads(r.output) == payload


def test_add_empty_url_exit_2_without_request(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _detail(7)))
    r = _run(["collections", "add", ""])
    assert r.exit_code == 2
    assert calls == []
    assert "没给歌单链接" in (r.stderr or "")


# ============================ rename ============================

def test_rename_puts_name(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _detail(1, name="新名字")))
    r = _run(["collections", "rename", "1", "新名字"])
    assert r.exit_code == 0
    assert calls[0]["method"] == "PUT"
    assert calls[0]["path"] == "/api/collections/1"
    assert calls[0]["body"] == {"name": "新名字"}
    assert "新名字" in r.output


def test_rename_not_found_stays_exit_0(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (404, {"detail": "收藏歌单不存在"}))
    r = _run(["collections", "rename", "999", "新名字"])
    assert r.exit_code == 0
    assert "收藏歌单不存在" in r.output


def test_rename_empty_name_exit_2_without_request(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _detail(1)))
    r = _run(["collections", "rename", "1", ""])
    assert r.exit_code == 2
    assert calls == []
    assert "不能为空" in (r.stderr or "")


def test_rename_json(monkeypatch):
    payload = _detail(1, name="新名字")
    _stub_api(monkeypatch, lambda m, p, b: (200, payload))
    r = _run(["collections", "rename", "1", "新名字", "--json"])
    assert json.loads(r.output) == payload


def test_rename_non_int_id_exit_2(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _detail(1)))
    r = _run(["collections", "rename", "x", "新名字"])
    assert r.exit_code == 2
    assert calls == []


# ============================= rm =============================

def test_rm_confirm_no_sends_no_delete(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _rows(1, 2)))
    r = _run(["collections", "rm", "1", "2"], input="n\n")
    assert r.exit_code == 0
    assert "已取消" in r.output
    assert [c["method"] for c in calls] == ["GET"]


def test_rm_lists_targets_before_confirm(monkeypatch):
    """让人对着一个干巴巴的 ID 确认是逼他记错，先摊开名字和链接。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, _rows(1, 2)))
    r = _run(["collections", "rm", "1"], input="n\n")
    assert "我的歌单" in r.output
    assert LONG_URL in r.output


def test_rm_yes_deletes(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (
        200, {"status": "deleted"} if m == "DELETE" else _rows(1)))
    r = _run(["collections", "rm", "1", "--yes"])
    assert r.exit_code == 0
    deletes = [c for c in calls if c["method"] == "DELETE"]
    assert [c["path"] for c in deletes] == ["/api/collections/1"]
    assert "已删除 1 个" in r.output


def test_rm_unknown_id_reported_and_not_deleted(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _rows(1)))
    r = _run(["collections", "rm", "999", "--yes"])
    assert r.exit_code == 0
    assert "收藏歌单不存在：999" in r.output
    assert [c["method"] for c in calls] == ["GET"]      # 一个 DELETE 都没发


def test_rm_all_unknown_skips_confirm(monkeypatch):
    """全都不存在时不该还问一句「确认删除」。"""
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _rows(1)))
    r = _run(["collections", "rm", "998", "999"])
    assert r.exit_code == 0
    assert "确认删除" not in r.output
    assert [c["method"] for c in calls] == ["GET"]


def test_rm_partial_unknown_deletes_the_rest(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (
        200, {"status": "deleted"} if m == "DELETE" else _rows(1)))
    r = _run(["collections", "rm", "1", "999", "--yes"])
    assert r.exit_code == 0
    deletes = [c for c in calls if c["method"] == "DELETE"]
    assert [c["path"] for c in deletes] == ["/api/collections/1"]
    assert "收藏歌单不存在：999" in r.output
    assert "已删除 1 个" in r.output


def test_rm_duplicate_ids_deleted_once(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (
        200, {"status": "deleted"} if m == "DELETE" else _rows(1)))
    r = _run(["collections", "rm", "1", "1", "--yes"])
    deletes = [c for c in calls if c["method"] == "DELETE"]
    assert len(deletes) == 1


def test_rm_http_error_counted_as_failure(monkeypatch):
    def handler(m, p, b):
        if m == "DELETE":
            return 404, {"detail": "收藏歌单不存在"}
        return 200, _rows(1)
    _stub_api(monkeypatch, handler)
    r = _run(["collections", "rm", "1", "--yes"])
    assert r.exit_code == 0
    assert "已删除 0 个" in r.output and "失败 1 个" in r.output


def test_rm_offline_stays_exit_0(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务"))
    r = _run(["collections", "rm", "1", "--yes"])
    assert r.exit_code == 0
    assert "连不上服务" in r.output


def test_rm_non_int_id_exit_2_without_request(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _rows(1)))
    r = _run(["collections", "rm", "abc", "--yes"])
    assert r.exit_code == 2
    assert calls == []


def test_rm_requires_ids():
    r = _run(["collections", "rm"])
    assert r.exit_code == 2


# =========================== refresh ===========================

def test_refresh_posts_each_id(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (
        200, {"collection": _detail(1), "status": "ok",
              "message": "刷新成功，共 3 首歌曲"}))
    r = _run(["collections", "refresh", "1"])
    assert r.exit_code == 0
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"] == "/api/collections/1/refresh"
    assert calls[0]["body"] is None


def test_refresh_uses_server_message(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (
        200, {"collection": _detail(2, name="夏日歌单"), "status": "ok",
              "message": "刷新成功，共 7 首歌曲"}))
    r = _run(["collections", "refresh", "2"])
    assert "刷新成功，共 7 首歌曲" in r.output
    assert "夏日歌单" in r.output


def test_refresh_continues_after_404(monkeypatch):
    """逐个进行：一个 404 不该让后面几个也不刷。"""
    def handler(m, p, b):
        if p == "/api/collections/1/refresh":
            return 404, {"detail": "收藏歌单不存在"}
        return 200, {"collection": _detail(2), "status": "ok",
                     "message": "刷新成功，共 3 首歌曲"}
    calls = _stub_api(monkeypatch, handler)
    r = _run(["collections", "refresh", "1", "2"])
    assert r.exit_code == 0
    posts = [c["path"] for c in calls if c["method"] == "POST"]
    assert posts == ["/api/collections/1/refresh", "/api/collections/2/refresh"]
    assert "收藏歌单不存在" in r.output
    assert "刷新成功" in r.output


def test_refresh_json(monkeypatch):
    payload = {"collection": _detail(1), "status": "ok",
               "message": "刷新成功，共 3 首歌曲"}
    _stub_api(monkeypatch, lambda m, p, b: (200, payload))
    r = _run(["collections", "refresh", "1", "--json"])
    assert json.loads(r.output) == payload


def test_refresh_non_int_id_exit_2_without_request(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, {}))
    r = _run(["collections", "refresh", "x"])
    assert r.exit_code == 2
    assert calls == []


def test_refresh_requires_ids():
    r = _run(["collections", "refresh"])
    assert r.exit_code == 2


# ============================= 组 =============================

def test_bare_collections_is_usage_error():
    """缺子命令 → exit 2，和 queue / files / bookmarks 一致。"""
    r = _run(["collections"])
    assert r.exit_code == 2


def test_help_lists_all_commands():
    r = _run(["collections", "--help"])
    assert r.exit_code == 0
    for name in ("list", "show", "add", "rename", "rm", "refresh"):
        assert name in r.output


def test_rm_help_documents_confirmation():
    r = _run(["collections", "rm", "--help"])
    assert r.exit_code == 0
    assert "--yes" in r.output
    assert "确认" in r.output
