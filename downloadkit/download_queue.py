"""
下载队列模块
支持并发控制、暂停/恢复/取消、断点续传
"""

import asyncio
import logging
from typing import Callable, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from .exceptions import CancelException, PauseException

logger = logging.getLogger(__name__)


class TaskStatus(Enum):
    """任务状态"""
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    CANCELLED = "cancelled"


@dataclass
class DownloadTask:
    """下载任务"""
    task_id: str
    url: str
    platform: str
    title: str
    status: TaskStatus = TaskStatus.PENDING
    progress: float = 0.0
    filename: str = ""
    error: str = ""
    file_size: int = 0
    downloaded_size: int = 0
    download_func: Callable = None  # 保存下载函数引用，用于重试


class DownloadQueue:
    """下载队列"""
    
    def __init__(self, max_concurrent: int = 3, cleanup_interval: int = 300):
        self.max_concurrent = max_concurrent
        self.cleanup_interval = cleanup_interval  # 清理间隔（秒）
        self.queue = asyncio.Queue()
        self.active_tasks: dict[str, DownloadTask] = {}
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._running = False
        self._paused_tasks: set[str] = set()
        self._cancelled_tasks: set[str] = set()
        self._cleanup_callbacks: list[Callable] = []  # 清理回调函数
    
    def add_cleanup_callback(self, callback: Callable):
        """添加清理回调函数"""
        self._cleanup_callbacks.append(callback)
    
    async def add_task(self, task_id: str, url: str, platform: str, 
                       title: str, download_func: Callable) -> DownloadTask:
        """
        添加下载任务到队列
        
        Args:
            task_id: 任务ID
            url: 下载URL
            platform: 平台名称
            title: 视频标题
            download_func: 下载函数，接收 DownloadTask 参数
        
        Returns:
            DownloadTask 对象
        """
        task = DownloadTask(
            task_id=task_id,
            url=url,
            platform=platform,
            title=title,
            status=TaskStatus.PENDING,
            download_func=download_func  # 保存下载函数引用
        )
        self.active_tasks[task_id] = task
        await self.queue.put((task, download_func))
        return task
    
    async def start(self):
        """启动队列处理"""
        self._running = True
        # 启动定时清理任务
        asyncio.create_task(self._cleanup_loop())
        while self._running:
            task, download_func = await self.queue.get()
            await self._semaphore.acquire()
            asyncio.create_task(self._process_task(task, download_func))
    
    async def _cleanup_loop(self):
        """定时清理循环"""
        while self._running:
            await asyncio.sleep(self.cleanup_interval)
            self.cleanup_completed()
            # 调用注册的回调函数
            for callback in self._cleanup_callbacks:
                try:
                    callback()
                except Exception as e:
                    logger.warning(f"[Cleanup] 回调执行失败: {e}")
    
    async def _process_task(self, task: DownloadTask, download_func: Callable):
        """处理下载任务"""
        try:
            task.status = TaskStatus.DOWNLOADING
            result = await download_func(task)
            
            # 检查 download_func 是否已设置失败状态
            if task.status == TaskStatus.FAILED:
                # download_func 已标记失败，不再覆盖
                pass
            elif task.task_id in self._cancelled_tasks:
                task.status = TaskStatus.CANCELLED
                self._cancelled_tasks.discard(task.task_id)
            else:
                task.status = TaskStatus.COMPLETED
                task.progress = 1.0
        except CancelException:
            task.status = TaskStatus.CANCELLED
            self._cancelled_tasks.discard(task.task_id)
        except PauseException:
            task.status = TaskStatus.PAUSED
        except Exception as e:
            if task.task_id in self._paused_tasks:
                task.status = TaskStatus.PAUSED
            elif task.task_id in self._cancelled_tasks:
                task.status = TaskStatus.CANCELLED
                self._cancelled_tasks.discard(task.task_id)
            else:
                task.status = TaskStatus.FAILED
                task.error = str(e)
        finally:
            self._semaphore.release()
            self.queue.task_done()
    
    def pause_task(self, task_id: str):
        """暂停任务"""
        self._paused_tasks.add(task_id)
        if task_id in self.active_tasks:
            self.active_tasks[task_id].status = TaskStatus.PAUSED
    
    def resume_task(self, task_id: str):
        """恢复任务"""
        self._paused_tasks.discard(task_id)
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            task.status = TaskStatus.PENDING
            task.error = ""
            # 重新添加到队列
            if task.download_func:
                asyncio.create_task(self.queue.put((task, task.download_func)))
    
    def cancel_task(self, task_id: str):
        """取消任务"""
        self._cancelled_tasks.add(task_id)
        self._paused_tasks.discard(task_id)
        if task_id in self.active_tasks:
            self.active_tasks[task_id].status = TaskStatus.CANCELLED
    
    async def retry_task(self, task_id: str):
        """重试失败的任务"""
        if task_id not in self.active_tasks:
            return False
        
        task = self.active_tasks[task_id]
        if task.status != TaskStatus.FAILED:
            return False
        
        # 重置任务状态（P3-2 进度保留）：
        # downloader 断点续传看的是目标文件已有字节数（Range），重试是
        # 接着下 —— 这里把 progress/downloaded_size 清零只会让进度条在
        # 重试瞬间倒退，明明在续传却显示从头开始。error 必须清，
        # 否则旧报错会挂在已恢复的任务上。
        task.status = TaskStatus.PENDING
        task.error = ""
        
        # 清除取消和暂停状态
        self._cancelled_tasks.discard(task_id)
        self._paused_tasks.discard(task_id)
        
        # 重新添加到队列
        if task.download_func:
            await self.queue.put((task, task.download_func))
            return True
        return False
    
    def is_paused(self, task_id: str) -> bool:
        """检查任务是否暂停"""
        return task_id in self._paused_tasks
    
    def is_cancelled(self, task_id: str) -> bool:
        """检查任务是否取消"""
        return task_id in self._cancelled_tasks
    
    def update_progress(self, task_id: str, progress: float, 
                       downloaded_size: int = 0, file_size: int = 0):
        """更新任务进度"""
        if task_id in self.active_tasks:
            task = self.active_tasks[task_id]
            task.progress = progress
            if downloaded_size > 0:
                task.downloaded_size = downloaded_size
            if file_size > 0:
                task.file_size = file_size
    
    def set_filename(self, task_id: str, filename: str):
        """设置任务文件名"""
        if task_id in self.active_tasks:
            self.active_tasks[task_id].filename = filename
    
    def get_queue_status(self) -> dict:
        """获取队列状态"""
        downloading = sum(1 for t in self.active_tasks.values() 
                         if t.status == TaskStatus.DOWNLOADING)
        pending = sum(1 for t in self.active_tasks.values() 
                     if t.status == TaskStatus.PENDING)
        completed = sum(1 for t in self.active_tasks.values() 
                       if t.status == TaskStatus.COMPLETED)
        failed = sum(1 for t in self.active_tasks.values() 
                    if t.status == TaskStatus.FAILED)
        paused = sum(1 for t in self.active_tasks.values() 
                    if t.status == TaskStatus.PAUSED)
        
        return {
            "downloading": downloading,
            "pending": pending,
            "completed": completed,
            "failed": failed,
            "paused": paused,
            "max_concurrent": self.max_concurrent,
            "tasks": [
                {
                    "task_id": t.task_id,
                    "title": t.title,
                    "platform": t.platform,
                    "status": t.status.value,
                    "progress": t.progress,
                    "filename": t.filename,
                    "file_size": t.file_size,
                    "downloaded_size": t.downloaded_size,
                    "error": t.error
                }
                for t in self.active_tasks.values()
            ]
        }
    
    def cleanup_completed(self) -> list[str]:
        """清理已完成的任务，返回被清理的 task_id 列表"""
        completed_ids = [
            task_id for task_id, task in self.active_tasks.items()
            if task.status in (TaskStatus.COMPLETED, TaskStatus.CANCELLED, TaskStatus.FAILED)
        ]
        for task_id in completed_ids:
            del self.active_tasks[task_id]
            self._paused_tasks.discard(task_id)
            self._cancelled_tasks.discard(task_id)
        
        if completed_ids:
            logger.info(f"[Cleanup] 清理了 {len(completed_ids)} 个已完成任务")
        
        return completed_ids

    def dismiss_task(self, task_id: str) -> bool:
        """手动把任务移出队列（前端点已完成项后调用），返回是否真的移除了

        与 cleanup_completed 同一套清理：除了 active_tasks，还要把暂停/取消
        集合里的残留一起丢掉，否则同 id 复用时旧状态会串到新任务上。
        """
        existed = task_id in self.active_tasks
        self.active_tasks.pop(task_id, None)
        self._paused_tasks.discard(task_id)
        self._cancelled_tasks.discard(task_id)
        return existed


# 全局实例
download_queue = DownloadQueue(max_concurrent=3)
