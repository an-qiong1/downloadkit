"""
下载队列重试功能测试
"""

import pytest
from downloadkit.download_queue import DownloadQueue, TaskStatus


@pytest.mark.asyncio
async def test_retry_failed_task_requeues():
    """测试失败任务可以重新进入队列"""
    queue = DownloadQueue(max_concurrent=1)
    calls = {"count": 0}

    async def download_func(task):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("first failure")
        task.filename = "ok.mp3"

    task = await queue.add_task(
        task_id="task-1",
        url="song-1",
        platform="netease",
        title="测试歌曲",
        download_func=download_func,
    )

    await queue._process_task(task, download_func)
    assert task.status == TaskStatus.FAILED

    result = await queue.retry_task("task-1")
    assert result is True
    assert task.status == TaskStatus.PENDING


@pytest.mark.asyncio
async def test_retry_completed_task_fails():
    """测试已完成任务不能重试"""
    queue = DownloadQueue(max_concurrent=1)

    async def download_func(task):
        task.filename = "ok.mp3"

    task = await queue.add_task(
        task_id="task-2",
        url="song-2",
        platform="netease",
        title="测试歌曲2",
        download_func=download_func,
    )

    await queue._process_task(task, download_func)
    assert task.status == TaskStatus.COMPLETED

    result = await queue.retry_task("task-2")
    assert result is False


@pytest.mark.asyncio
async def test_retry_nonexistent_task_fails():
    """测试不存在的任务不能重试"""
    queue = DownloadQueue(max_concurrent=1)

    result = await queue.retry_task("nonexistent")
    assert result is False
