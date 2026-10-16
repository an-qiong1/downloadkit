"""P1-任务4+5 回归测试：--dry-run 模式与 status 命令

覆盖范围：
  - playlist --dry-run：解析后输出曲目，不触发下载
  - download --dry-run：解析后输出信息，不触发下载
  - collections add --dry-run：解析后输出预览，不实际 POST
  - bookmarks probe --dry-run：打印待探测链接列表，不启动后端任务
  - status：无服务时提示；有服务时返回各统计字段
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import downloadkit.cli as cli


DEFAULT_SERVER = "http://127.0.0.1:8765"


@pytest.fixture(autouse=True)
def _reset_server(monkeypatch):
    monkeypatch.setattr(cli, "_SERVER", DEFAULT_SERVER)


def _run(args, input=None):
    return CliRunner().invoke(cli.main, args, input=input, catch_exceptions=False)


# ============================ helpers ============================

def _make_pl(name="周杰伦全集", songs=None):
    songs = songs or [
        SimpleNamespace(title="晴天", artist="周杰伦", album="",
                        platform="netease", song_id="sid1"),
        SimpleNamespace(title="稻香", artist="周杰伦", album="",
                        platform="netease", song_id="sid2"),
    ]
    pl = SimpleNamespace(name=name, platform="netease",
                         song_count=len(songs), description="", songs=songs)
    return pl


def _patch_run_async(monkeypatch, value):
    """把 cli.run_async 替换为直接返回值，绕过 asyncio.run。"""
    def _noop(coro):
        return value
    monkeypatch.setattr(cli, "run_async", _noop)


# ============================ playlist --dry-run ============================

def test_playlist_dryrun_shows_tracks_no_download(monkeypatch, tmp_path):
    """--dry-run 时打印曲目列表，不触发下载。"""
    pl = _make_pl()
    _patch_run_async(monkeypatch, pl)

    r = _run(["playlist", "https://music.163.com/playlist?id=1", "--dry-run"])
    assert r.exit_code == 0
    assert "周杰伦全集" in r.output
    assert "晴天" in r.output
    assert "dry-run" in r.output.lower() or "dry_run" in r.output or "预览" in r.output


def test_playlist_no_dryrun_still_works(monkeypatch):
    """不用 --dry-run 时正常走下载逻辑（通过 run_async 拦截验证）。"""
    pl = _make_pl()
    _patch_run_async(monkeypatch, pl)

    # 自动确认下载（输入 y\n）
    r = _run(["playlist", "https://music.163.com/playlist?id=1"], input="y\n")
    assert r.exit_code == 0
    assert "周杰伦全集" in r.output


# ============================ download --dry-run ============================

def test_download_dryrun_no_network_call(monkeypatch, tmp_path):
    """--dry-run 时不应调用 download_song（可通过拦截验证）。"""
    call_count = {"n": 0}

    pl = SimpleNamespace(
        songs=[SimpleNamespace(title="晴天", artist="周杰伦", album="",
                               platform="netease", song_id="sid1")],
        name="晴天", platform="netease", song_count=1, description=""
    )
    _patch_run_async(monkeypatch, pl)

    async def fake_download(song, progress=None, output_dir=None):
        call_count["n"] += 1
        return None

    monkeypatch.setattr(cli, "download_song", fake_download)

    r = _run(["download", "https://music.163.com/song?id=1", "--dry-run"])
    assert r.exit_code == 0
    assert call_count["n"] == 0, "dry-run 不应触发真实下载"
    assert "dry-run" in r.output.lower() or "预览" in r.output or "跳过" in r.output


def test_download_no_dryrun_calls_download_song(monkeypatch, tmp_path):
    """不用 --dry-run 时会调用 download_song。"""
    pl = SimpleNamespace(
        songs=[SimpleNamespace(title="晴天", artist="周杰伦", album="",
                               platform="netease", song_id="sid1")],
        name="晴天", platform="netease", song_count=1, description=""
    )
    _patch_run_async(monkeypatch, pl)

    saved_result = tmp_path / "晴天.mp3"
    saved_result.write_bytes(b"x" * 1024)

    async def fake_download(song, progress=None, output_dir=None):
        return saved_result

    monkeypatch.setattr(cli, "download_song", fake_download)

    r = _run(["download", "https://music.163.com/song?id=1"])
    assert r.exit_code == 0
    assert "已保存" in r.output or "晴天" in r.output


# ============================ collections add --dry-run ============================

def test_collections_add_dryrun_no_post(monkeypatch):
    """dry-run 时不发 POST /api/collections，只做本地解析预览。"""
    pl = _make_pl(name="睡前歌单")
    _patch_run_async(monkeypatch, pl)

    # 用 _coll_api 的替身记录调用
    calls = []

    def stub_coll_api(method, path, body=None, *, as_json=False):
        calls.append({"method": method, "path": path})
        return None

    monkeypatch.setattr(cli, "_coll_api", stub_coll_api)

    r = _run(["collections", "add", "https://music.163.com/playlist?id=99", "--dry-run"])
    assert r.exit_code == 0
    post_calls = [c for c in calls if c["method"] == "POST" and "/api/collections" in c["path"]]
    assert len(post_calls) == 0, "dry-run 不应发 POST"
    assert "预览" in r.output or "dry-run" in r.output.lower()


def test_collections_add_without_dryrun_posts(monkeypatch):
    """不用 --dry-run 时正常发 POST。"""
    pl = _make_pl()
    _patch_run_async(monkeypatch, pl)

    calls = []

    def stub_coll_api(method, path, body=None, *, as_json=False):
        calls.append({"method": method, "path": path})
        if method == "POST":
            return {"id": 7, "name": "睡前歌单", "tracks": []}
        return []

    monkeypatch.setattr(cli, "_coll_api", stub_coll_api)

    r = _run(["collections", "add", "https://music.163.com/playlist?id=99"])
    assert r.exit_code == 0
    post_calls = [c for c in calls if c["method"] == "POST" and "/api/collections" in c["path"]]
    assert len(post_calls) == 1


# ============================ bookmarks probe --dry-run ============================

def test_bookmarks_probe_dryrun_no_post(monkeypatch, tmp_path):
    FAKE_HTML = (
        '<!DOCTYPE NETSCAPE-Bookmark-file-1>\n'
        '<DL><p>\n'
        '  <DT><A HREF="https://example.com/v/1">视频1</A>\n'
        '  <DT><A HREF="https://example.com/v/2">视频2</A>\n'
        '</DL><p>\n'
    )
    f = tmp_path / "bm.html"
    f.write_text(FAKE_HTML, encoding="utf-8")

    calls = []

    def stub_probe(method, path, body=None, **kw):
        calls.append({"method": method, "path": path})
        return (0, "dry-run 跳过")

    monkeypatch.setattr(cli, "_probe_api", stub_probe)
    monkeypatch.setattr(cli, "_read_bookmark_file", lambda p: FAKE_HTML)

    r = _run(["bookmarks", "probe", str(f), "--dry-run"])
    assert r.exit_code == 0
    post_calls = [c for c in calls if c["method"] == "POST" and "probe" in c["path"]]
    assert len(post_calls) == 0, "dry-run 不应发 POST 到 /api/bookmarks/probe"
    assert "example.com/v/1" in r.output
    assert "example.com/v/2" in r.output


# ============================ status command ============================

def test_status_no_server(monkeypatch):
    """服务未运行时给出中文提示，退出码 0。"""
    import httpx

    def boom(*args, **kwargs):
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(httpx, "request", boom)
    r = _run(["status"])
    assert r.exit_code == 0
    assert "服务未运行" in r.output or "无法连通" in r.output


def test_status_with_server(monkeypatch):
    """模拟服务在线，检查各字段。"""
    import httpx

    def fake_request(method, url, **kwargs):
        responses = {
            "http://127.0.0.1:8765/api/settings/get": (200, {"settings": {"proxy": {"mode": "direct"}}, "proxy_system": ""}),
            "http://127.0.0.1:8765/api/queue/status": (200, {"pending": 1, "downloading": 0, "paused": 0, "completed": 5, "failed": 1, "tasks": []}),
            "http://127.0.0.1:8765/api/subscriptions": (200, [{"sec_uid": "abc"}, {"sec_uid": "def"}]),
            "http://127.0.0.1:8765/api/collections": (200, [{"id": 1, "name": "歌单A"}, {"id": 2, "name": "歌单B"}]),
            "http://127.0.0.1:8765/api/history/count": (200, {"count": 42}),
        }
        code, body = responses.get(url, (200, {"settings": {}, "proxy_system": ""}))

        class Resp:
            status_code = code
            def json(self):
                return body
            @property
            def text(self):
                return json.dumps(body)
        return Resp()

    monkeypatch.setattr(httpx, "request", fake_request)
    r = _run(["status"])
    assert r.exit_code == 0
    assert "服务" in r.output
    assert "运行中" in r.output
    assert "42" in r.output  # history count
    assert "2" in r.output  # subscriptions or collections count
    assert "direct" in r.output.lower()


def test_status_json_mode(monkeypatch):
    """--json 输出合法 JSON。"""
    import httpx

    def fake_request(method, url, **kwargs):
        responses = {
            "http://127.0.0.1:8765/api/settings/get": (200, {"settings": {"proxy": {"mode": "manual"}}, "proxy_system": "127.0.0.1:7890"}),
            "http://127.0.0.1:8765/api/queue/status": (200, {"pending": 0, "downloading": 0, "paused": 0, "completed": 0, "failed": 0, "tasks": []}),
            "http://127.0.0.1:8765/api/subscriptions": (200, []),
            "http://127.0.0.1:8765/api/collections": (200, []),
            "http://127.0.0.1:8765/api/history/count": (200, {"count": 0}),
        }
        code, body = responses.get(url, (200, {"settings": {}, "proxy_system": ""}))

        class Resp:
            status_code = code
            def json(self):
                return body
            @property
            def text(self):
                return json.dumps(body)
        return Resp()

    monkeypatch.setattr(httpx, "request", fake_request)
    r = _run(["status", "--json"])
    assert r.exit_code == 0
    data = json.loads(r.output)
    assert data["server_up"] is True
    assert data["proxy_mode"] == "manual"
    assert isinstance(data["history_count"], int)
    assert isinstance(data["collections_count"], int) or data["collections_count"] is None
