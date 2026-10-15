#!/usr/bin/env python3
"""CLI 文件管理命令（files 命令组）回归

2026-10-14 P5-4：下载根目录是服务端按配置算出来的（get_download_dir()，
可能指向 NAS、也可能带自定义分类子目录），CLI 在本地猜一个路径很容易对
不上；删除与打开还必须过服务端的 safe_delete_path —— `..` 遍历和越出
下载目录由它统一挡成 403。所以 files 命令组和 queue / subscribe 一样，
一律走 HTTP 读写正在运行的服务。

本文件覆盖：

  - files ls：按修改时间倒序、分类过滤、空目录/空分类提示、--json 纯
    stdout（含结构化错误）、文件名里的方括号不被 rich 当标记吃掉、汇总行
  - files rm：删之前摊开列出目标并确认（拒绝则一个请求都不发）、--yes
    放行、批量逐条记账（部分失败不能只报成功）、遍历 403 透传
  - files open：打开文件 / --dir 打开目录、headless 只转述 NAS 路径
    （不谎称「已打开」）、404 detail 透传
  - 尺寸与时间格式化、确认辅助函数
"""

import json
import re
import sys
from pathlib import Path

import click
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
    """把 cli._queue_api 换成记录调用的替身；handler(method, path, body)。

    接受 **kw 是因为真实签名还有 timeout（订阅那组会传更长的值），
    files 这组虽然不传，替身也别卡在这个细节上。
    """
    calls = []

    def stub(method, path, body=None, **kw):
        calls.append((method, path, body))
        return handler(method, path, body)

    monkeypatch.setattr(cli, "_queue_api", stub)
    return calls


def _files_payload():
    """一份覆盖分类目录 + 根目录散文件的 /api/files 响应。

    time 故意打乱：排序断言要能证明 CLI 确实按 mtime 倒序重排了，
    而不是照抄服务端给的顺序。
    """
    return {"files": [
        {"name": "old.mp3", "path": "music/old.mp3", "size": 1024,
         "time": 1000.0, "category": "music", "category_label": "音乐"},
        {"name": "new.mp4", "path": "videos/new.mp4", "size": 2048,
         "time": 5000.0, "category": "videos", "category_label": "视频"},
        {"name": "pic.jpg", "path": "images/pic.jpg", "size": 512,
         "time": 3000.0, "category": "images", "category_label": "图片"},
        {"name": "loose.mp3", "path": "loose.mp3", "size": 64,
         "time": 2000.0, "category": "others", "category_label": "其他"},
    ]}


def _one(name, cat="music", label="音乐", size=100, ts=1.0):
    return {"name": name, "path": f"{cat}/{name}", "size": size,
            "time": ts, "category": cat, "category_label": label}


# ------------------------------------------------------- 格式化与确认辅助


class TestFmt:
    @pytest.mark.parametrize("n,expect", [
        (0, "0 B"), (512, "512 B"), (1023, "1023 B"),
        (1024, "1.0 KB"), (1536, "1.5 KB"),
        (5 * 1024 * 1024, "5.0 MB"),
        (1024 ** 3, "1.0 GB"),
        (1024 ** 4, "1.0 TB"),      # 单位表封顶在 TB
        (1024 ** 5, "1024.0 TB"),   # 再大也得给出数，不许抛异常
        (None, "-"), ("abc", "-"), (-1, "-"),
    ])
    def test_fmt_size(self, n, expect):
        assert cli._fmt_size(n) == expect

    def test_file_time_is_readable(self):
        assert re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$",
                        cli._file_time(1700000000))

    @pytest.mark.parametrize("bad", [None, "oops", [], {}])
    def test_file_time_falls_back_to_dash(self, bad):
        assert cli._file_time(bad) == "-"


class TestConfirm:
    def test_yes_flag_never_asks(self, monkeypatch):
        def boom(*a, **k):
            raise AssertionError("--yes 时不该弹确认")
        monkeypatch.setattr(cli.click, "confirm", boom)
        assert cli._confirm_or_skip("删吗", True) is True

    def test_accept_returns_true(self, monkeypatch):
        monkeypatch.setattr(cli.click, "confirm",
                            lambda prompt, abort=False: True)
        assert cli._confirm_or_skip("删吗", False) is True

    def test_decline_returns_false_and_says_cancelled(self, monkeypatch,
                                                      capsys):
        def fake_confirm(prompt, abort=False):
            raise click.Abort()
        monkeypatch.setattr(cli.click, "confirm", fake_confirm)
        assert cli._confirm_or_skip("删吗", False) is False
        assert "已取消" in capsys.readouterr().out


# ------------------------------------------------------------------ ls


class TestFilesLs:
    def test_calls_get_files(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: (200, _files_payload()))
        r = _run(["files", "ls"])
        assert r.exit_code == 0
        assert calls == [("GET", "/api/files", None)]

    def test_sorted_newest_first_not_server_order(self, monkeypatch):
        """服务端给的是「按分类分组、组内倒序」，CLI 要重排成全局倒序。"""
        _stub_api(monkeypatch, lambda m, p, b: (200, _files_payload()))
        out = _run(["files", "ls"]).output
        order = [out.index(n) for n in
                 ("new.mp4", "pic.jpg", "loose.mp3", "old.mp3")]
        assert order == sorted(order), out

    @pytest.mark.parametrize("cat,kept,dropped", [
        ("videos", ["new.mp4"], ["old.mp3", "pic.jpg", "loose.mp3"]),
        ("others", ["loose.mp3"], ["old.mp3", "new.mp4", "pic.jpg"]),
        ("images", ["pic.jpg"], ["old.mp3", "new.mp4", "loose.mp3"]),
    ])
    def test_category_filter(self, monkeypatch, cat, kept, dropped):
        calls = _stub_api(monkeypatch, lambda m, p, b: (200, _files_payload()))
        out = _run(["files", "ls", cat]).output
        for name in kept:
            assert name in out
        for name in dropped:
            assert name not in out
        assert calls == [("GET", "/api/files", None)]  # 过滤在本地做

    def test_json_is_pure_stdout(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, _files_payload()))
        rows = json.loads(_run(["files", "ls", "--json"]).output)
        assert len(rows) == 4
        assert rows[0]["path"] == "music/old.mp3"  # --json 保留服务端原序

    def test_json_with_category_filter(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, _files_payload()))
        rows = json.loads(_run(["files", "ls", "videos", "--json"]).output)
        assert [r["name"] for r in rows] == ["new.mp4"]

    def test_json_error_shape(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (404, {"detail": "boom"}))
        err = json.loads(_run(["files", "ls", "--json"]).output)
        assert "404" in err["error"] and "boom" in err["error"]

    def test_json_network_error_shape(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务 X（ConnectError）。"))
        err = json.loads(_run(["files", "ls", "--json"]).output)
        assert "连不上服务" in err["error"]

    def test_empty_dir_hint_points_to_download(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, {"files": []}))
        out = _run(["files", "ls"]).output
        assert "下载目录里还没有文件" in out

    def test_empty_category_says_which_one(self, monkeypatch):
        payload = {"files": [_one("a.mp3")]}  # 只有音乐
        _stub_api(monkeypatch, lambda m, p, b: (200, payload))
        out = _run(["files", "ls", "videos"]).output
        assert "视频分类下没有文件" in out

    def test_bracket_in_filename_is_not_eaten(self, monkeypatch):
        """文件名是用户内容。`[1]` 不 escape 的话会被 rich 当标记吃掉，
        用户看到的名字就和真实文件名对不上了。"""
        payload = {"files": [_one("坏[1].mp3")]}
        _stub_api(monkeypatch, lambda m, p, b: (200, payload))
        out = _run(["files", "ls"]).output
        assert "坏[1].mp3" in out

    def test_summary_counts_and_total_size(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, _files_payload()))
        out = _run(["files", "ls"]).output
        # 1024+2048+512+64 = 3648 字节 ≈ 3.6 KB
        assert "共 4 个" in out and "3.6 KB" in out
        # 汇总按固定分类顺序排，不跟着文件出现顺序乱跳
        assert "音乐 1" in out and "视频 1" in out
        summary = next(l for l in out.splitlines() if "共 4 个" in l)
        assert summary.index("音乐 1") < summary.index("视频 1")

    def test_network_error_hint(self, monkeypatch):
        # 替身文案照抄真实 _queue_api 的原话，断言得认得出指引在哪
        _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务 X（ConnectError）。"
                                                 "这个命令需要 DownloadKit 正在运行，"
                                                 "换地址用 --server 指定。"))
        out = _run(["files", "ls"]).output
        assert "连不上服务" in out and "--server" in out

    def test_non_json_response_does_not_crash(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, "<html>不是 JSON</html>"))
        out = _run(["files", "ls"]).output
        assert "失败" in out

    def test_list_alias_matches_ls(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: (200, _files_payload()))
        out = _run(["files", "list"]).output
        assert "new.mp4" in out
        assert calls == [("GET", "/api/files", None)]

    def test_unknown_category_is_usage_error(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: (200, _files_payload()))
        r = _run(["files", "ls", "photos"])
        assert r.exit_code != 0
        assert calls == []


# ------------------------------------------------------------------ rm


class TestFilesRm:
    def test_declined_confirm_sends_no_request(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: (200, {}))
        r = _run(["files", "rm", "music/a.mp3"], input="n\n")
        assert r.exit_code == 0
        assert "已取消" in r.output
        assert calls == []

    def test_targets_are_listed_before_confirming(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, {}))
        out = _run(["files", "rm", "music/a.mp3", "videos/b.mp4"],
                   input="n\n").output
        assert "不可恢复" in out
        assert "music/a.mp3" in out and "videos/b.mp4" in out

    def test_yes_skips_confirm_and_posts_all_targets(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: (
            200, {"deleted": ["music/a.mp3", "videos/b.mp4"], "errors": []}))
        r = _run(["files", "rm", "music/a.mp3", "videos/b.mp4", "--yes"])
        assert r.exit_code == 0
        assert calls == [("POST", "/api/files/batch-delete",
                          {"files": ["music/a.mp3", "videos/b.mp4"]})]
        assert "已删除 music/a.mp3" in r.output
        assert "已删除 videos/b.mp4" in r.output
        assert "已删除 2 个" in r.output

    def test_partial_failure_is_reported(self, monkeypatch):
        """batch-delete 逐条记账：单条失败整个请求仍是 200，
        所以失败必须逐条列出来，否则用户以为全删干净了。"""
        _stub_api(monkeypatch, lambda m, p, b: (200, {
            "deleted": ["music/ok.mp3"],
            "errors": [{"path": "music/missing.mp3", "error": "文件不存在"}]}))
        out = _run(["files", "rm", "music/ok.mp3", "music/missing.mp3",
                    "--yes"]).output
        assert "已删除 music/ok.mp3" in out
        assert "删不掉 music/missing.mp3" in out
        assert "文件不存在" in out
        assert "已删除 1 个" in out and "失败 1 个" in out

    def test_all_failed_does_not_claim_success(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, {
            "deleted": [], "errors": [{"path": "a", "error": "文件不存在"}]}))
        out = _run(["files", "rm", "a", "--yes"]).output
        assert "已删除 0 个" in out and "失败 1 个" in out

    def test_empty_receipt_is_flagged(self, monkeypatch):
        """服务端既没回 deleted 也没回 errors：不能默默当成删成功了。"""
        _stub_api(monkeypatch, lambda m, p, b: (200, {"deleted": [], "errors": []}))
        out = _run(["files", "rm", "a", "--yes"]).output
        assert "服务端没回任何删除结果" in out

    def test_traversal_is_passed_through_as_403(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: (
            403, {"detail": "检测到路径遍历尝试: ../../etc/passwd"}))
        out = _run(["files", "rm", "../../etc/passwd", "--yes"]).output
        assert "HTTP 403" in out
        assert "路径遍历" in out
        # 路径校验是服务端的事，CLI 只负责把参数原样送过去
        assert calls[0][2] == {"files": ["../../etc/passwd"]}

    def test_outside_base_is_passed_through_as_403(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (403, {"detail": "文件路径超出允许范围"}))
        out = _run(["files", "rm", "C:/Windows/notepad.exe", "--yes"]).output
        assert "HTTP 403" in out and "超出允许范围" in out

    def test_no_target_is_usage_error(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: (200, {}))
        r = _run(["files", "rm"])
        assert r.exit_code != 0
        assert calls == []

    def test_blank_target_is_rejected_before_request(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: (200, {}))
        r = _run(["files", "rm", "   "])
        assert r.exit_code != 0
        assert calls == []

    def test_network_error_is_chinese_hint(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务 X（ConnectError）。"
                                                 "这个命令需要 DownloadKit 正在运行。"))
        out = _run(["files", "rm", "a.mp3", "--yes"]).output
        assert "连不上服务" in out

    def test_trailing_spaces_are_trimmed(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: (
            200, {"deleted": ["music/a.mp3"], "errors": []}))
        _run(["files", "rm", "  music/a.mp3  ", "--yes"])
        assert calls[0][2] == {"files": ["music/a.mp3"]}


# ------------------------------------------------------------------ open


class TestFilesOpen:
    def test_open_file_endpoint(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: (
            200, {"status": "opened", "path": r"C:\dl\music\a.mp3"}))
        r = _run(["files", "open", "music/a.mp3"])
        assert r.exit_code == 0
        assert calls == [("POST", "/api/open-file", {"path": "music/a.mp3"})]
        assert "已打开" in r.output
        assert r"C:\dl\music\a.mp3" in r.output

    def test_dir_flag_opens_containing_folder(self, monkeypatch):
        calls = _stub_api(monkeypatch, lambda m, p, b: (
            200, {"status": "opened", "path": r"C:\dl\music"}))
        r = _run(["files", "open", "music/a.mp3", "--dir"])
        assert calls == [("POST", "/api/open-dir", {"path": "music/a.mp3"})]
        assert "已打开" in r.output

    def test_headless_reports_path_without_claiming_open(self, monkeypatch):
        """容器里根本弹不开程序。服务端回的是「它在哪」，CLI 必须照转述，
        不能谎称已打开——不然用户以为文件已经在本机播放器里了。"""
        _stub_api(monkeypatch, lambda m, p, b: (200, {
            "status": "headless", "path": "/data/music/a.mp3",
            "title": "文件位置", "nas_path": "//nas/files/music/a.mp3"}))
        out = _run(["files", "open", "music/a.mp3"]).output
        assert "文件位置" in out
        assert "/data/music/a.mp3" in out
        assert "//nas/files/music/a.mp3" in out
        assert "已打开" not in out

    def test_headless_dir_uses_its_own_title(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (200, {
            "status": "headless", "path": "/data/music",
            "title": "目录位置", "nas_path": ""}))
        out = _run(["files", "open", "music/a.mp3", "--dir"]).output
        assert "目录位置" in out
        assert "nas_path" not in out  # 没配 NAS 路径就别印空行

    def test_missing_file_detail_passed_through(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (
            404, {"detail": "文件不存在或已被移动"}))
        out = _run(["files", "open", "gone.mp3"]).output
        assert "HTTP 404" in out
        assert "文件不存在或已被移动" in out

    def test_traversal_is_passed_through(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (403, {"detail": "路径遍历攻击被拒绝"}))
        out = _run(["files", "open", "../../secret.txt"]).output
        assert "HTTP 403" in out and "路径遍历" in out

    def test_network_error_is_chinese_hint(self, monkeypatch):
        _stub_api(monkeypatch, lambda m, p, b: (0, "连不上服务 X（ConnectError）。"
                                                 "这个命令需要 DownloadKit 正在运行。"))
        out = _run(["files", "open", "a.mp3"]).output
        assert "连不上服务" in out

    def test_target_without_path_falls_back_to_argument(self, monkeypatch):
        """服务端万一没回 path，也要告诉用户打开的是哪个（别印个空串）。"""
        _stub_api(monkeypatch, lambda m, p, b: (200, {"status": "opened"}))
        out = _run(["files", "open", "music/a.mp3"]).output
        assert "music/a.mp3" in out


# ------------------------------------------------------------------ 帮助


class TestHelp:
    def test_group_help_lists_subcommands(self):
        r = _run(["files", "--help"])
        assert r.exit_code == 0
        for name in ("ls", "rm", "open"):
            assert name in r.output

    def test_ls_help_documents_categories(self):
        r = _run(["files", "ls", "--help"])
        assert r.exit_code == 0
        for cat in ("music", "videos", "images", "animated", "others"):
            assert cat in r.output

    def test_rm_help_mentions_relative_paths(self):
        r = _run(["files", "rm", "--help"])
        assert r.exit_code == 0
        assert "files ls" in r.output
