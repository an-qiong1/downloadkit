# -*- coding: utf-8 -*-
"""点击「进行中」的已完成项：打开文件 + 移出列表（体验优化第 1 批）

背景（2026-09-27 用户实测的 Bug⑥）：已完成的任务在「进行中」列表里没有
任何可点的交互 —— 不打开文件也不打开目录，点了一片死寂。

守住四条：
  1. 文件解析只许落在下载目录内：../ 遍历、绝对路径越界必须抛错，
     不许因为「按文件名递归查找」开了安全后门。
  2. 队列任务只记文件名不带目录 —— 裸文件名必须能在分类子目录
     （videos/music/...）里递归找到。
  3. dismiss 只移除已结束的任务，进行中（pending/downloading/paused）
     必须拒绝：任务实体还在跑，删了列表会和真实进度脱钩。
  4. dismiss 必须同时清 _downloads —— queue/status 会把 _downloads 里的
     孤儿卡再拼回列表，只删一边等于没删，一刷新就复活。

顺带钉死 Bug⑤（files.js）：刷新不裁剪 selectedFiles、空列表不回位
工具栏、「删除选中 (N)」计数就一直残留。
"""

from pathlib import Path

import pytest
from fastapi import HTTPException

import server
from downloadkit.download_queue import DownloadQueue, DownloadTask, TaskStatus
from downloadkit.file_manager import PathTraversalError, FileOutsideBaseError

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "downloadkit" / "static"

VIDEO_NAME = "标题 2026-09-27.mp4"


def _noop(task):
    pass


def _task(tid, status):
    return DownloadTask(task_id=tid, url="u", platform="douyin", title=tid,
                        status=status, download_func=_noop)


@pytest.fixture
def dl_dir(tmp_path, monkeypatch):
    """下载根目录：videos 与 music 两个分类子目录各放一个文件"""
    (tmp_path / "videos").mkdir()
    (tmp_path / "videos" / VIDEO_NAME).write_bytes(b"x")
    (tmp_path / "music").mkdir()
    (tmp_path / "music" / "song.mp3").write_bytes(b"x")
    monkeypatch.setattr(server, "get_download_dir", lambda: tmp_path)
    return tmp_path


# ---------------- 文件名解析（_resolve_open_file）----------------


def test_resolve_bare_filename_finds_file_in_subdir(dl_dir):
    """队列任务只存文件名，必须能递归找到分类子目录里的文件"""
    got = server._resolve_open_file(VIDEO_NAME)
    assert got.resolve() == (dl_dir / "videos" / VIDEO_NAME).resolve()


def test_resolve_relative_subpath(dl_dir):
    got = server._resolve_open_file(f"videos/{VIDEO_NAME}")
    assert got.resolve() == (dl_dir / "videos" / VIDEO_NAME).resolve()


def test_resolve_rejects_traversal(dl_dir):
    with pytest.raises(PathTraversalError):
        server._resolve_open_file("../secret.mp4")


def test_resolve_rejects_absolute_outside(dl_dir):
    """绝对路径必须被拦在下载目录外 —— 递归查找不许变成越界后门"""
    with pytest.raises(FileOutsideBaseError):
        server._resolve_open_file(str(dl_dir.parent / "outside.mp4"))


def test_resolve_missing_file_404(dl_dir):
    with pytest.raises(HTTPException) as ei:
        server._resolve_open_file("不存在.mp4")
    assert ei.value.status_code == 404


def test_resolve_empty_path_400(dl_dir):
    with pytest.raises(HTTPException) as ei:
        server._resolve_open_file("")
    assert ei.value.status_code == 400


def test_resolve_directory_rejected(dl_dir):
    with pytest.raises(HTTPException) as ei:
        server._resolve_open_file("videos")
    assert ei.value.status_code == 400


# ---------------- POST /api/open-file ----------------


@pytest.mark.asyncio
async def test_api_open_file_headless_returns_file_paths(dl_dir, monkeypatch):
    """容器环境不调系统程序，返回文件的 NAS 路径信息（前端弹窗展示）"""
    monkeypatch.setattr(server, "_is_container", lambda: True)
    monkeypatch.setenv("NAS_FILES_PATH", "/volume1/files")

    info = await server.api_open_file(server.OpenFileRequest(path=VIDEO_NAME))

    assert info["status"] == "headless"
    assert info["title"] == "文件位置", "弹窗标题要说「文件」不是「目录」"
    assert info["nas_path"].endswith(f"videos/{VIDEO_NAME}")


@pytest.mark.asyncio
async def test_api_open_file_404_when_missing(dl_dir):
    with pytest.raises(HTTPException) as ei:
        await server.api_open_file(server.OpenFileRequest(path="不存在.mp4"))
    assert ei.value.status_code == 404


# ---------------- POST /api/queue/{task_id}/dismiss ----------------


@pytest.fixture
def fake_queue(monkeypatch):
    """隔离的队列与 _downloads（不 start，不产生真实下载）"""
    q = DownloadQueue(max_concurrent=1)
    d = {}
    monkeypatch.setattr(server, "download_queue", q)
    monkeypatch.setattr(server, "_downloads", d)
    return q, d


@pytest.mark.asyncio
async def test_dismiss_removes_completed_from_both_sides(fake_queue):
    q, d = fake_queue
    q.active_tasks["a"] = _task("a", TaskStatus.COMPLETED)
    d["a"] = {"status": "done", "filename": VIDEO_NAME}

    r = await server.api_dismiss_task("a")

    assert r == {"status": "dismissed"}
    assert "a" not in q.active_tasks
    assert "a" not in d, "只删队列不删 _downloads，刷新时 queue/status 会把它拼回来"


@pytest.mark.asyncio
async def test_dismiss_orphan_card_in_downloads_only(fake_queue):
    """孤儿卡（任务实体已被清理）也要能移除，否则列表里永远挂着"""
    _q, d = fake_queue
    d["ghost"] = {"status": "done", "filename": "g.mp4"}

    r = await server.api_dismiss_task("ghost")

    assert r["status"] == "dismissed"
    assert "ghost" not in d


@pytest.mark.asyncio
async def test_dismiss_rejects_active_task(fake_queue):
    q, _d = fake_queue
    q.active_tasks["run"] = _task("run", TaskStatus.DOWNLOADING)

    with pytest.raises(HTTPException) as ei:
        await server.api_dismiss_task("run")

    assert ei.value.status_code == 409
    assert "run" in q.active_tasks, "进行中的任务不许被移除"


@pytest.mark.asyncio
async def test_dismiss_unknown_404(fake_queue):
    with pytest.raises(HTTPException) as ei:
        await server.api_dismiss_task("nope")
    assert ei.value.status_code == 404


def test_dismiss_task_method_cleans_paused_cancelled_sets():
    """同 id 复用时旧的暂停/取消状态不许串到新任务上"""
    q = DownloadQueue(max_concurrent=1)
    q.active_tasks["t"] = _task("t", TaskStatus.COMPLETED)
    q._paused_tasks.add("t")
    q._cancelled_tasks.add("t")

    assert q.dismiss_task("t") is True
    assert q.active_tasks == {}
    assert "t" not in q._paused_tasks
    assert "t" not in q._cancelled_tasks
    assert q.dismiss_task("t") is False


# ---------------- 前端接线 ----------------


FILES_JS = (STATIC / "js" / "files.js").read_text(encoding="utf-8")
QUEUE_JS = (STATIC / "js" / "queue.js").read_text(encoding="utf-8")
MAIN_CSS = (STATIC / "css" / "main.css").read_text(encoding="utf-8")


def test_files_js_prunes_selection_on_refresh():
    """Bug⑤：删完文件后「删除选中 (N)」计数残留"""
    assert "selectedFiles = pruned" in FILES_JS, "刷新没有裁剪选中集"
    assert "delete selectedFiles[filepath]" in FILES_JS, "单删没有同步移出选中集"
    assert "allBox.indeterminate" in FILES_JS, "重绘后没有回位全选框状态"
    # 空列表分支必须回位工具栏（原来的 early return 把计数挂在半空）
    empty_branch = FILES_JS.split("state.files.length === 0")[1].split("emptyEl.style.display = 'none'")[0]
    assert "updateFilesToolbar()" in empty_branch, "空列表没有重置「删除选中 (N)」"


def test_queue_js_opens_file_and_dismisses_completed_row():
    """Bug⑥：完成行要能点、点了开文件、开完移出列表"""
    assert "/api/open-file" in QUEUE_JS, "没有调用打开文件端点"
    assert "/dismiss" in QUEUE_JS, "打开后没有把任务移出「进行中」"
    assert "queue-item-done" in QUEUE_JS, "完成行没有可点样式类"
    assert "点击打开文件" in QUEUE_JS, "完成行没有悬停提示"
    assert "task.status !== 'completed'" in QUEUE_JS, "非完成行不许触发打开文件"
    assert "queue-item-done" in MAIN_CSS, "CSS 缺可点样式（cursor: pointer）"


def test_open_file_routes_registered_unshadowed():
    """新端点必须注册成功且不被参数路由吃掉（同 test_server_routes 的坑）"""
    from server import app

    def first_match(url):
        for route in app.routes:
            if "POST" not in (getattr(route, "methods", None) or set()):
                continue
            regex = getattr(route, "path_regex", None)
            if regex and regex.match(url):
                return route.path
        return None

    assert first_match("/api/open-file") == "/api/open-file"
    assert first_match("/api/queue/some-task/dismiss") == "/api/queue/{task_id}/dismiss"
