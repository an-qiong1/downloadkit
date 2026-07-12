#!/usr/bin/env python3
"""
下载队列模块测试用例
"""

import sys
import pytest
import asyncio
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from downloadkit.download_queue import DownloadQueue, TaskStatus, DownloadTask
from downloadkit.exceptions import PauseException, CancelException


class TestTaskStatus:
    """任务状态枚举测试"""
    
    def test_task_status_values(self):
        """测试任务状态值"""
        assert TaskStatus.PENDING.value == "pending"
        assert TaskStatus.DOWNLOADING.value == "downloading"
        assert TaskStatus.COMPLETED.value == "completed"
        assert TaskStatus.FAILED.value == "failed"
        assert TaskStatus.PAUSED.value == "paused"
        assert TaskStatus.CANCELLED.value == "cancelled"
    
    def test_task_status_members(self):
        """测试任务状态成员数量"""
        assert len(TaskStatus) == 6


class TestDownloadTask:
    """下载任务测试"""
    
    def test_download_task_creation(self):
        """测试下载任务创建"""
        task = DownloadTask(
            task_id="test-1",
            url="https://example.com/file.mp4",
            platform="test",
            title="测试视频"
        )
        assert task.task_id == "test-1"
        assert task.url == "https://example.com/file.mp4"
        assert task.platform == "test"
        assert task.title == "测试视频"
        assert task.status == TaskStatus.PENDING
        assert task.progress == 0.0
        assert task.filename == ""
        assert task.error == ""
    
    def test_download_task_default_values(self):
        """测试下载任务默认值"""
        task = DownloadTask(
            task_id="test-2",
            url="https://example.com/file.mp4",
            platform="test",
            title="测试视频"
        )
        assert task.file_size == 0
        assert task.downloaded_size == 0
        assert task.download_func is None


class TestDownloadQueue:
    """下载队列测试"""
    
    def test_download_queue_creation(self):
        """测试下载队列创建"""
        queue = DownloadQueue(max_concurrent=5, cleanup_interval=600)
        assert queue.max_concurrent == 5
        assert queue.cleanup_interval == 600
        assert len(queue.active_tasks) == 0
    
    def test_download_queue_default_values(self):
        """测试下载队列默认值"""
        queue = DownloadQueue()
        assert queue.max_concurrent == 3
        assert queue.cleanup_interval == 300
    
    @pytest.mark.asyncio
    async def test_add_task(self):
        """测试添加任务"""
        queue = DownloadQueue()
        
        async def dummy_download(task):
            pass
        
        task = await queue.add_task(
            task_id="test-3",
            url="https://example.com/file.mp4",
            platform="test",
            title="测试视频",
            download_func=dummy_download
        )
        
        assert task.task_id == "test-3"
        assert task.status == TaskStatus.PENDING
        assert "test-3" in queue.active_tasks
    
    @pytest.mark.asyncio
    async def test_pause_resume_task(self):
        """测试暂停/恢复任务"""
        queue = DownloadQueue()
        
        async def dummy_download(task):
            pass
        
        await queue.add_task(
            task_id="test-4",
            url="https://example.com/file.mp4",
            platform="test",
            title="测试视频",
            download_func=dummy_download
        )
        
        # 暂停任务
        queue.pause_task("test-4")
        assert queue.is_paused("test-4") is True
        
        # 恢复任务
        queue.resume_task("test-4")
        assert queue.is_paused("test-4") is False
    
    @pytest.mark.asyncio
    async def test_cancel_task(self):
        """测试取消任务"""
        queue = DownloadQueue()
        
        async def dummy_download(task):
            pass
        
        await queue.add_task(
            task_id="test-5",
            url="https://example.com/file.mp4",
            platform="test",
            title="测试视频",
            download_func=dummy_download
        )
        
        # 取消任务
        queue.cancel_task("test-5")
        assert queue.is_cancelled("test-5") is True
    
    def test_nonexistent_task(self):
        """测试不存在的任务"""
        queue = DownloadQueue()
        
        # 暂停不存在的任务 - 会添加到_paused_tasks集合
        queue.pause_task("nonexistent")
        assert queue.is_paused("nonexistent") is True  # pause_task无条件添加
        
        # 恢复不存在的任务
        queue.resume_task("nonexistent")
        assert queue.is_paused("nonexistent") is False
        
        # 取消不存在的任务 - 会添加到_cancelled_tasks集合
        queue.cancel_task("nonexistent")
        assert queue.is_cancelled("nonexistent") is True  # cancel_task无条件添加


class TestDownloadQueueIntegration:
    """下载队列集成测试"""
    
    def test_download_queue_import(self):
        """测试download_queue模块可以正常导入"""
        from downloadkit import download_queue
        assert hasattr(download_queue, 'DownloadQueue')
        assert hasattr(download_queue, 'TaskStatus')
        assert hasattr(download_queue, 'DownloadTask')
    
    def test_download_queue_singleton(self):
        """测试download_queue单例"""
        from downloadkit.download_queue import download_queue
        assert isinstance(download_queue, DownloadQueue)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
