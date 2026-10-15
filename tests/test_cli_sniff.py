#!/usr/bin/env python3
"""CLI 嗅探与书签命令（sniff / bookmarks）回归

2026-10-15 P5-5：L2 嗅探用的是服务进程里那个 DrissionPage 浏览器单例
（_lock 串行、headless/有头按站点在进程内记忆），CLI 自己再起一份就是两个
浏览器抢资源，还会丢掉「这个站回退过有头」的记忆，所以照样走 HTTP。

这一组的退出码和 queue / subscribe 不一样，是故意的：那两组是「状态查询」，
查到空状态也算查成功（0）；这一组是「探测器」——sniff 没抓到流、书签导不进
链接，都意味着命令没做成它该做的事，给 1，脚本据此分支，不必解析中文。

本文件覆盖：

  - sniff：命中/未命中/导航失败三条路、方法标签、流地址经 click.echo 整行
    输出不被 rich 按 80 列折断（P5-2 Task ID 同一个坑）、referer/player 透出
  - sniff：--json 纯 stdout（含服务端原样返回与结构化错误）、退出码约定、
    客户器超时给足 L2 预算余量、空 url / 非法流条目被滤掉
  - bookmarks import：缩进树、方括号不被 rich 标记吃掉、limit 截断与提示、
    --urls 去重保序、--json 原样返回、BOM / cp936 / 认不出的编码
  - bookmarks：空文件、0 链接、连不上服务、缺文件不发请求
"""

import json
import logging
import sys
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

import downloadkit.cli as cli
from downloadkit.bookmarks import parse_bookmarks_html


DEFAULT_SERVER = "http://127.0.0.1:8765"


@pytest.fixture(autouse=True)
def _reset_server(monkeypatch):
    """每个用例把 _SERVER 拨回默认，防 --server 用例污染后续。"""
    monkeypatch.setattr(cli, "_SERVER", DEFAULT_SERVER)


def _run(args, input=None):
    return CliRunner().invoke(cli.main, args, input=input,
                              catch_exceptions=False)


def _stub_api(monkeypatch, handler):
    """把 cli._queue_api 换成记录调用的替身；handler(method, path, body)。

    kw 也一并记下：sniff 必须传比 L2 预算更长的客户端超时，这条断言就是
    为了防有人哪天把 timeout 退回默认 30 秒。
    """
    calls = []

    def stub(method, path, body=None, **kw):
        calls.append({"method": method, "path": path, "body": body, **kw})
        return handler(method, path, body)

    monkeypatch.setattr(cli, "_queue_api", stub)
    return calls


# ============================ sniff ============================

# 故意做长：m3u8 地址动辄上百字符，折了就复制不全，这条断言就是防折行
LONG_M3U8 = ("https://cdn.example.com/hls/2026/10/15/"
             "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4/index.m3u8"
             "?sign=deadbeef0123456789deadbeef0123456789&expire=1792000000")


def _sniff_hit(**over):
    data = {
        "url": "https://example.com/watch/1",
        "ok": True,
        "method": "main",
        "streams": [
            {"url": LONG_M3U8, "kind": "m3u8",
             "referer": "https://example.com/watch/1", "ua": "Mozilla/5.0"},
            {"url": "https://cdn.example.com/v/2.mp4", "kind": "mp4",
             "referer": "", "ua": ""},
        ],
        "player_url": "",
        "page_url": "https://example.com/watch/1",
        "title": "测试视频",
        "referer": "https://example.com/watch/1",
        "ua": "Mozilla/5.0",
        "cookies": "",
        "requests_seen": 12,
        "elapsed": 3.5,
        "error": "",
        "nav_failed": False,
    }
    data.update(over)
    return data


def _sniff_miss(**over):
    data = _sniff_hit(ok=False, streams=[], error="页面未发现流地址",
                      elapsed=1.2)
    data.update(over)
    return data


def test_sniff_posts_to_api_sniff(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_hit()))
    r = _run(["sniff", "https://example.com/watch/1"])
    assert r.exit_code == 0
    assert calls[0]["method"] == "POST"
    assert calls[0]["path"] == "/api/sniff"
    assert calls[0]["body"] == {"url": "https://example.com/watch/1",
                                "timeout": 30.0}


def test_sniff_timeout_option_passes_through(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_hit()))
    r = _run(["sniff", "https://example.com/watch/1", "-t", "45"])
    assert r.exit_code == 0
    assert calls[0]["body"]["timeout"] == 45.0


def test_sniff_client_timeout_has_margin_for_l2(monkeypatch):
    """L2 预算服务端最多给 60 秒，客户端超时必须更长。

    退成默认 30 秒的话，服务端还在过 WAF、客户端先报超时——用户白等一场，
    和订阅抓主页那个坑是同一类。
    """
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_hit()))
    _run(["sniff", "https://example.com/watch/1"])
    assert calls[0]["timeout"] >= cli._API_TIMEOUT_SNIFF
    assert calls[0]["timeout"] > 60.0


def test_sniff_hit_header_and_streams(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_hit()))
    r = _run(["sniff", "https://example.com/watch/1"])
    assert r.exit_code == 0
    assert "命中 2 条流" in r.output
    assert "主页面监听" in r.output
    assert "3.5s" in r.output
    assert "页面：测试视频" in r.output


def test_sniff_stream_url_never_folded(monkeypatch):
    """流地址必须整行落地。

    走 console.print 会被 rich 按 80 列从中间切断，用户复制出来是个断的
    地址（P5-2 的 Task ID 就栽过一次，那次解法是 no_wrap，这里整行本身就
    比 80 宽，只能绕开 rich）。
    """
    _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_hit()))
    r = _run(["sniff", "https://example.com/watch/1"])
    assert f"[1] m3u8  {LONG_M3U8}" in r.output
    assert "[2] mp4  https://cdn.example.com/v/2.mp4" in r.output


def test_sniff_echoes_referer(monkeypatch):
    """防盗链站下载要带 referer，不透出用户就得自己再去查一遍。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_hit(
        referer="https://example.com/watch/1")))
    r = _run(["sniff", "https://example.com/watch/1"])
    assert r.exit_code == 0
    assert "referer: https://example.com/watch/1" in r.output


def test_sniff_skips_empty_referer_and_player(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_hit(
        referer="", player_url="")))
    r = _run(["sniff", "https://example.com/watch/1"])
    assert "referer:" not in r.output
    assert "player:" not in r.output


def test_sniff_echoes_player_url(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_hit(
        method="player",
        player_url="https://example.com/embed/player.html")))
    r = _run(["sniff", "https://example.com/watch/1"])
    assert r.exit_code == 0
    assert "播放器提升" in r.output
    assert "player: https://example.com/embed/player.html" in r.output


@pytest.mark.parametrize("method,label", [
    ("main", "主页面监听"),
    ("player", "播放器提升"),
    ("js", "JS Hook"),
])
def test_sniff_method_label(monkeypatch, method, label):
    _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_hit(method=method)))
    r = _run(["sniff", "https://example.com/watch/1"])
    assert label in r.output


def test_sniff_unknown_method_shows_raw(monkeypatch):
    """服务端加了新方法时别把人糊弄成「-」，原样显示至少能看出来。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_hit(method="magic")))
    r = _run(["sniff", "https://example.com/watch/1"])
    assert "magic" in r.output


def test_sniff_miss_exit_code_1(monkeypatch):
    """探测器没探测到就是没做成，退出码必须让脚本能分支。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_miss(
        error="页面被 WAF 拦了")))
    r = _run(["sniff", "https://example.com/watch/1"])
    assert r.exit_code == 1
    assert "嗅探未命中：页面被 WAF 拦了" in r.output


def test_sniff_miss_default_message(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_miss(error="")))
    r = _run(["sniff", "https://example.com/watch/1"])
    assert r.exit_code == 1
    assert "页面未发现流地址" in r.output


def test_sniff_nav_failed_hint(monkeypatch):
    """导航失败（死域名）和被 WAF 拦不是一回事。

    混在一个提示里，用户会对着一个根本打不开的地址反复重试。
    """
    _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_miss(
        error="无法访问该地址", nav_failed=True)))
    r = _run(["sniff", "https://dead.example.com/watch/1"])
    assert r.exit_code == 1
    assert "导航失败" in r.output


def test_sniff_no_nav_hint_when_nav_succeeded(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_miss(
        error="页面未发现流地址", nav_failed=False)))
    r = _run(["sniff", "https://example.com/watch/1"])
    assert r.exit_code == 1
    assert "导航失败" not in r.output


def test_sniff_drops_empty_and_malformed_streams(monkeypatch):
    """流条目里混进空 url 或非 dict（服务端拼包出错）不能算命中。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_hit(streams=[
        {"url": "", "kind": "m3u8"},
        "not-a-dict",
        {"kind": "mp4"},
        {"url": "https://cdn.example.com/only.mp4", "kind": "mp4"},
    ])))
    r = _run(["sniff", "https://example.com/watch/1"])
    assert r.exit_code == 0
    assert "命中 1 条流" in r.output
    assert "https://cdn.example.com/only.mp4" in r.output


def test_sniff_all_streams_bad_counts_as_miss(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_hit(
        streams=[{"url": "", "kind": "m3u8"}], error="")))
    r = _run(["sniff", "https://example.com/watch/1"])
    assert r.exit_code == 1
    assert "嗅探未命中" in r.output


def test_sniff_json_hit(monkeypatch):
    payload = _sniff_hit()
    _stub_api(monkeypatch, lambda m, p, b: (200, payload))
    r = _run(["sniff", "https://example.com/watch/1", "--json"])
    assert r.exit_code == 0
    assert json.loads(r.output) == payload


def test_sniff_json_miss_exit_1_still_json(monkeypatch):
    """未命中时 --json 也得是合法 JSON——管道侧只吐半截文本就断了。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_miss()))
    r = _run(["sniff", "https://example.com/watch/1", "--json"])
    assert r.exit_code == 1
    assert json.loads(r.output)["streams"] == []


def test_sniff_http_error(monkeypatch):
    _stub_api(monkeypatch,
              lambda m, p, b: (400, {"detail": "无效 URL"}))
    r = _run(["sniff", "not-a-url"])
    assert r.exit_code == 1
    assert "失败（HTTP 400）: 无效 URL" in r.output


def test_sniff_http_error_json(monkeypatch):
    _stub_api(monkeypatch,
              lambda m, p, b: (400, {"detail": "无效 URL"}))
    r = _run(["sniff", "not-a-url", "--json"])
    assert r.exit_code == 1
    assert json.loads(r.output) == {"error": "HTTP 400: 无效 URL"}


def test_sniff_offline_exit_1(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务"))
    r = _run(["sniff", "https://example.com/watch/1"])
    assert r.exit_code == 1
    assert "连不上服务" in r.output


def test_sniff_offline_json(monkeypatch):
    _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务"))
    r = _run(["sniff", "https://example.com/watch/1", "--json"])
    assert r.exit_code == 1
    assert json.loads(r.output) == {"error": "连不上服务"}


def test_sniff_non_dict_body_treated_as_error(monkeypatch):
    """200 但 body 不是对象：不能当成功往下解析属性（会 KeyError）。"""
    _stub_api(monkeypatch, lambda m, p, b: (200, ["weird"]))
    r = _run(["sniff", "https://example.com/watch/1"])
    assert r.exit_code == 1


def test_sniff_missing_url_is_usage_error(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_hit()))
    r = _run(["sniff"])
    assert r.exit_code != 0
    assert calls == []


def test_sniff_help_documents_exit_codes():
    r = _run(["sniff", "--help"])
    assert r.exit_code == 0
    assert "退出码" in r.output
    assert "L2" in r.output


# ======================= --json 不被日志污染 =======================

class _StdoutHandler(logging.Handler):
    """emit 时现取 sys.stdout。

    CliRunner 会把 sys.stdout 换成内存流，import 时就绑死老 stdout 的
    handler 抓不到污染，测了等于没测。
    """

    def emit(self, record):
        try:
            sys.stdout.write(self.format(record) + "\n")
        except Exception:  # noqa: BLE001 — 日志不该把命令打挂
            pass


@pytest.fixture
def restore_downloadkit_logger():
    lg = logging.getLogger("downloadkit")
    saved_level = lg.level
    saved = [(h, h.level) for h in lg.handlers]
    yield
    lg.setLevel(saved_level)
    for h, lvl in saved:
        h.setLevel(lvl)


def test_sniff_json_survives_info_logs(monkeypatch, restore_downloadkit_logger):
    """downloadkit logger 的 INFO 混进 stdout 会把 JSON 挤成非法文本。"""
    lg = logging.getLogger("downloadkit")
    handler = _StdoutHandler()
    handler.setLevel(logging.INFO)
    lg.addHandler(handler)
    lg.setLevel(logging.INFO)

    _stub_api(monkeypatch, lambda m, p, b: (200, _sniff_hit()))
    r = _run(["sniff", "https://example.com/watch/1", "--json"])
    assert r.exit_code == 0
    assert json.loads(r.output)["ok"] is True


# ============================ bookmarks ============================

_NETSCAPE_HTML = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3>书签栏</H3>
    <DL><p>
        <DT><A HREF="https://a.com/v/1">第一个视频</A>
        <DT><H3>追剧 [2024]</H3>
        <DL><p>
            <DT><A HREF="https://a.com/v/2">第 [1] 集</A>
            <DT><A HREF="https://a.com/v/1">第一个视频（重复）</A>
        </DL><p>
    </DL><p>
    <DT><A HREF="https://top.example.com/">顶层</A>
</DL><p>
"""


def _bm_payload(text=_NETSCAPE_HTML):
    """用真解析器生成响应，保证 CLI 测的是真实树结构而不是我编的形状。"""
    tree, stats = parse_bookmarks_html(text)
    return {"tree": tree, "links": stats["links"], "folders": stats["folders"]}


def _write(tmp_path, raw, name="bookmarks.html"):
    p = tmp_path / name
    p.write_bytes(raw)
    return str(p)


def test_bm_import_posts_html_file(monkeypatch, tmp_path):
    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    calls = _stub_api(monkeypatch,
                      lambda m, p, b: (200, _bm_payload()))
    r = _run(["bookmarks", "import", path])
    assert r.exit_code == 0
    assert calls[0]["path"] == "/api/bookmarks/import"
    assert calls[0]["body"]["html"] == _NETSCAPE_HTML


def test_bm_import_tree_view(monkeypatch, tmp_path):
    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    _stub_api(monkeypatch, lambda m, p, b: (200, _bm_payload()))
    r = _run(["bookmarks", "import", path])
    assert r.exit_code == 0
    assert "导入成功：4 条链接 / 2 个文件夹" in r.output
    assert "书签栏/" in r.output
    assert "第一个视频" in r.output
    assert "第 [1] 集" in r.output
    # 树视图显示的是标题；URL 要走 --urls / --json
    assert "• 顶层" in r.output


def test_bm_tree_indentation(monkeypatch, tmp_path):
    """一层两格缩进，不缩进就读不出层级。"""
    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    _stub_api(monkeypatch, lambda m, p, b: (200, _bm_payload()))
    r = _run(["bookmarks", "import", path])
    assert "  • 第一个视频" in r.output
    assert "    • 第 [1] 集" in r.output


def test_bm_brackets_not_eaten_by_rich(monkeypatch, tmp_path):
    """书名号/方括号是 rich 标记，不 escape 就会被当样式吞掉或抛错。"""
    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    _stub_api(monkeypatch, lambda m, p, b: (200, _bm_payload()))
    r = _run(["bookmarks", "import", path])
    assert "追剧 [2024]/" in r.output


def test_bm_urls_dedup_and_pure_stdout(monkeypatch, tmp_path):
    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    _stub_api(monkeypatch, lambda m, p, b: (200, _bm_payload()))
    r = _run(["bookmarks", "import", path, "--urls"])
    assert r.exit_code == 0
    lines = [x for x in r.output.splitlines() if x]
    # 浏览器书签里同一条链接存三份是常事，喂给下游前必须去重
    assert lines == ["https://a.com/v/1", "https://a.com/v/2",
                     "https://top.example.com/"]


def test_bm_json_raw_payload(monkeypatch, tmp_path):
    payload = _bm_payload()
    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    _stub_api(monkeypatch, lambda m, p, b: (200, payload))
    r = _run(["bookmarks", "import", path, "--json"])
    assert r.exit_code == 0
    assert json.loads(r.output) == payload


def test_bm_json_wins_over_urls(monkeypatch, tmp_path):
    """两个开关同给别猜，--json（更全）说了算，help 里写明了。"""
    payload = _bm_payload()
    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    _stub_api(monkeypatch, lambda m, p, b: (200, payload))
    r = _run(["bookmarks", "import", path, "--json", "--urls"])
    assert json.loads(r.output) == payload


def test_bm_limit_explicit(monkeypatch, tmp_path):
    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    _stub_api(monkeypatch, lambda m, p, b: (200, _bm_payload()))
    r = _run(["bookmarks", "import", path, "--limit", "1"])
    assert r.exit_code == 0
    assert "还有 3 条没显示" in r.output
    assert "第一个视频" in r.output
    assert "第 [1] 集" not in r.output


def test_bm_limit_zero_shows_all(monkeypatch, tmp_path):
    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    _stub_api(monkeypatch, lambda m, p, b: (200, _bm_payload()))
    r = _run(["bookmarks", "import", path, "-n", "0"])
    assert r.exit_code == 0
    assert "没显示" not in r.output
    assert "第 [1] 集" in r.output


def test_bm_limit_counts_links_not_folders(monkeypatch, tmp_path):
    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    _stub_api(monkeypatch, lambda m, p, b: (200, _bm_payload()))
    r = _run(["bookmarks", "import", path, "-n", "4"])
    # 4 条链接全显示 → 没到 cap → 不提示截断，文件夹也不占额度
    assert "没显示" not in r.output
    assert "第 [1] 集" in r.output


def test_bm_limit_capped_hint_points_to_alternatives(monkeypatch, tmp_path):
    """截断了就得告诉用户全量去哪看，不然只能靠猜。"""
    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    _stub_api(monkeypatch, lambda m, p, b: (200, _bm_payload()))
    r = _run(["bookmarks", "import", path, "-n", "2"])
    assert "--limit 0" in r.output
    assert "--urls" in r.output


def test_bm_empty_title_falls_back_to_url(monkeypatch, tmp_path):
    """标题为空时不能在树上留个光秃秃的点。

    真解析器不产出空标题（实测 `<A HREF>` 不带文字会被它略过），所以这条
    手搓 payload——防的是服务端哪天改了解析、把空标题放出来。
    """
    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    payload = {"tree": [
        {"type": "folder", "name": "无名", "add_date": 0, "children": [
            {"type": "link", "title": "", "url": "https://lonely.example.com/",
             "add_date": 0},
        ]},
    ], "links": 1, "folders": 1}
    _stub_api(monkeypatch, lambda m, p, b: (200, payload))
    r = _run(["bookmarks", "import", path, "-n", "0"])
    assert r.exit_code == 0
    assert "无名/" in r.output
    assert "• https://lonely.example.com/" in r.output


def test_bm_utf8_bom_stripped(monkeypatch, tmp_path):
    path = _write(tmp_path, b"\xef\xbb\xbf" + _NETSCAPE_HTML.encode("utf-8"))
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _bm_payload()))
    r = _run(["bookmarks", "import", path])
    assert r.exit_code == 0
    assert not calls[0]["body"]["html"].startswith("﻿")


def test_bm_cp936_fallback(tmp_path, monkeypatch):
    """中文 Windows 上被别的工具转过码的文件要能读，但 UTF-8 优先。"""
    path = _write(tmp_path, _NETSCAPE_HTML.encode("cp936"))
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _bm_payload()))
    r = _run(["bookmarks", "import", path])
    assert r.exit_code == 0
    assert "追剧" in calls[0]["body"]["html"]


def test_bm_undecodable_file_exits_1(tmp_path, monkeypatch):
    """两种编码都解不开就明说，别拿乱码硬发给服务端。"""
    path = _write(tmp_path, b"\xff\xfe\x01")
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _bm_payload()))
    r = _run(["bookmarks", "import", path])
    assert r.exit_code == 1
    assert "编码认不出" in r.output
    assert calls == []


def test_bm_missing_file_sends_no_request(monkeypatch):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _bm_payload()))
    r = _run(["bookmarks", "import", "nope.html"])
    assert r.exit_code != 0
    assert calls == []


def test_bm_directory_rejected(monkeypatch, tmp_path):
    calls = _stub_api(monkeypatch, lambda m, p, b: (200, _bm_payload()))
    r = _run(["bookmarks", "import", str(tmp_path)])
    assert r.exit_code != 0
    assert calls == []


def test_bm_empty_file_server_rejects(monkeypatch, tmp_path):
    path = _write(tmp_path, b"")
    calls = _stub_api(monkeypatch, lambda m, p, b: (400, {"detail": "文件为空"}))
    r = _run(["bookmarks", "import", path])
    assert r.exit_code == 1
    assert "失败（HTTP 400）: 文件为空" in r.output
    assert calls[0]["body"]["html"] == ""


def test_bm_zero_links_http_400_exit_1(monkeypatch, tmp_path):
    path = _write(tmp_path,
                  "<html><body>随便一个页面</body></html>".encode("utf-8"))
    _stub_api(monkeypatch, lambda m, p, b: (
        400, {"detail": "未解析到任何书签链接，请确认这是浏览器导出的书签 HTML 文件"}))
    r = _run(["bookmarks", "import", path])
    assert r.exit_code == 1
    assert "未解析到任何书签链接" in r.output


def test_bm_zero_links_200_still_exit_1(monkeypatch, tmp_path):
    """服务端哪天放宽了校验，200 + 0 条链接也不能算导入成功。"""
    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    _stub_api(monkeypatch, lambda m, p, b: (200, {"tree": [], "links": 0,
                                                  "folders": 0}))
    r = _run(["bookmarks", "import", path])
    assert r.exit_code == 1
    assert "没有可用链接" in r.output


def test_bm_zero_links_json(monkeypatch, tmp_path):
    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    _stub_api(monkeypatch, lambda m, p, b: (200, {"tree": [], "links": 0,
                                                  "folders": 0}))
    r = _run(["bookmarks", "import", path, "--json"])
    assert r.exit_code == 1
    assert json.loads(r.output) == {"error": "书签里没有可用链接"}


def test_bm_offline_exit_1(monkeypatch, tmp_path):
    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务"))
    r = _run(["bookmarks", "import", path])
    assert r.exit_code == 1
    assert "连不上服务" in r.output


def test_bm_offline_json(monkeypatch, tmp_path):
    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务"))
    r = _run(["bookmarks", "import", path, "--json"])
    assert r.exit_code == 1
    assert json.loads(r.output) == {"error": "连不上服务"}


def test_bm_json_survives_info_logs(monkeypatch, tmp_path,
                                    restore_downloadkit_logger):
    lg = logging.getLogger("downloadkit")
    handler = _StdoutHandler()
    handler.setLevel(logging.INFO)
    lg.addHandler(handler)
    lg.setLevel(logging.INFO)

    path = _write(tmp_path, _NETSCAPE_HTML.encode("utf-8"))
    payload = _bm_payload()
    _stub_api(monkeypatch, lambda m, p, b: (200, payload))
    r = _run(["bookmarks", "import", path, "--json"])
    assert r.exit_code == 0
    assert json.loads(r.output) == payload


def test_bm_bare_group_exits_2_like_other_groups():
    """裸命令 group 不是「看状态」，是缺子命令——和 queue/files/subscribe
    一样报用法错误（poller 那种裸命令有含义的才另设 invoke_without_command）。
    """
    r = _run(["bookmarks"])
    assert r.exit_code == 2


def test_bm_group_help_lists_import():
    r = _run(["bookmarks", "--help"])
    assert r.exit_code == 0
    assert "import" in r.output
    assert "书签" in r.output


def test_bm_import_help():
    r = _run(["bookmarks", "import", "--help"])
    assert r.exit_code == 0
    assert "退出码" in r.output
    assert "--urls" in r.output
    assert "--limit" in r.output
