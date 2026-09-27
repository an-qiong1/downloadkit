"""P3-2 队列打磨：一键重试全部失败 + 进度保留

要守住的三条：

  1. **重试不清进度**：downloader 断点续传看文件字节数，重试是接着下，
     retry_task 把 progress/downloaded_size 清零会让进度条在重试瞬间
     倒退，明明在续传却显示从头开始。error 必须清（旧报错不许挂着）。
  2. **批量重试只碰队列里真实存在的 FAILED**：_downloads 的孤儿 failed 卡
     （任务实体已被 cleanup 清掉）重发不了 —— 视频条目不存原链接、
     音乐条目的 url 是 song_id 走视频接口必然立刻再失败，
     硬发只会批量制造新失败任务。孤儿如实统计成 orphaned 报给前端。
  3. **只放行失败状态**：completed / pending 不许被批量重试搅动。
"""

from pathlib import Path

import pytest

import server
from downloadkit.download_queue import DownloadQueue, DownloadTask, TaskStatus

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "downloadkit" / "static"


async def _noop(task):
    pass


def _task(tid, status, **kw):
    return DownloadTask(
        task_id=tid, url="u", platform="douyin", title=tid,
        status=status, download_func=_noop, **kw,
    )


# ---------------- 进度保留 ----------------


@pytest.mark.asyncio
async def test_retry_keeps_progress_and_sizes():
    """重试保留进度与已下字节，只清 error（P3-2 核心）"""
    q = DownloadQueue(max_concurrent=1)
    t = _task("t1", TaskStatus.FAILED, progress=0.62,
              downloaded_size=65536, file_size=100000, error="boom")
    q.active_tasks["t1"] = t

    assert await q.retry_task("t1") is True
    assert t.status == TaskStatus.PENDING
    assert t.error == "", "旧报错必须清掉"
    assert t.progress == 0.62, "重试把进度清零了，续传场景下进度条会倒退"
    assert t.downloaded_size == 65536
    assert t.file_size == 100000


@pytest.mark.asyncio
async def test_retry_still_rejects_non_failed():
    """批量之前，单任务语义不变：只有 FAILED 能重试"""
    q = DownloadQueue(max_concurrent=1)
    done = _task("done", TaskStatus.COMPLETED)
    q.active_tasks["done"] = done
    assert await q.retry_task("done") is False
    assert done.status == TaskStatus.COMPLETED


# ---------------- POST /api/queue/retry-failed ----------------


@pytest.fixture
def fake_queue(monkeypatch):
    """隔离的队列与 _downloads（不 start，重试只入队不执行下载）"""
    q = DownloadQueue(max_concurrent=1)
    d = {}
    monkeypatch.setattr(server, "download_queue", q)
    monkeypatch.setattr(server, "_downloads", d)
    return q, d


@pytest.mark.asyncio
async def test_retry_failed_requeues_all_failures(fake_queue):
    q, d = fake_queue
    q.active_tasks["a"] = _task("a", TaskStatus.FAILED)
    q.active_tasks["b"] = _task("b", TaskStatus.FAILED)
    q.active_tasks["c"] = _task("c", TaskStatus.COMPLETED)
    d["a"] = {"status": "failed", "error": "boom"}

    r = await server.api_retry_failed()

    assert r["retried"] == 2, "两个失败任务都要重新入队"
    assert q.active_tasks["a"].status == TaskStatus.PENDING
    assert q.active_tasks["b"].status == TaskStatus.PENDING
    assert q.active_tasks["c"].status == TaskStatus.COMPLETED, \
        "已完成的任务不许被批量重试搅动"
    # _downloads 同步翻成下载中，否则状态卡继续显示失败
    assert d["a"]["status"] == "downloading"
    assert "error" not in d["a"]
    assert r["orphaned"] == 0, "a 在队列里重试成功，不算孤儿"


@pytest.mark.asyncio
async def test_retry_failed_counts_stranded_cards(fake_queue):
    """孤儿 failed 卡（实体已出队）统计出来但不硬发"""
    q, d = fake_queue
    d["ghost"] = {"status": "failed", "error": "e"}

    r = await server.api_retry_failed()

    assert r["retried"] == 0
    assert r["orphaned"] == 1
    # 不许凭空造任务
    assert q.active_tasks == {}


@pytest.mark.asyncio
async def test_retry_failed_empty_queue(fake_queue):
    r = await server.api_retry_failed()
    assert r == {"status": "ok", "retried": 0, "orphaned": 0}


@pytest.mark.asyncio
async def test_retry_failed_ignores_pending_and_paused(fake_queue):
    q, d = fake_queue
    q.active_tasks["p"] = _task("p", TaskStatus.PENDING)
    q.active_tasks["z"] = _task("z", TaskStatus.PAUSED)

    r = await server.api_retry_failed()

    assert r["retried"] == 0
    assert q.active_tasks["p"].status == TaskStatus.PENDING
    assert q.active_tasks["z"].status == TaskStatus.PAUSED


# ---------------- 界面 ----------------

HTML = (STATIC / "index.html").read_text(encoding="utf-8")
QUEUE_JS = (STATIC / "js" / "queue.js").read_text(encoding="utf-8")


def test_queue_header_has_failed_stat_and_batch_button():
    assert 'id="queue-failed-stat"' in HTML, "统计区缺失败计数"
    assert 'id="queue-failed"' in HTML
    assert 'id="queue-retry-failed"' in HTML, "缺一键重试按钮"


def test_queue_js_wires_batch_retry():
    assert "/api/queue/retry-failed" in QUEUE_JS, "按钮没调批量端点"
    assert "uiConfirm(" in QUEUE_JS, "批量重试前没有确认（P4-4 起用 uiConfirm 弹窗）"
    assert "orphaned" in QUEUE_JS, "没把过期任务数转述给用户"
    assert "failedCount > 0" in QUEUE_JS, "按钮没按失败数显隐"
    assert "queue-failed-stat" in QUEUE_JS, "失败计数没回填"
