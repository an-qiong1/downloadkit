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
    # 独立并发额度（lane）。空串 = 走全局额度。
    # 歌单批量下载用它把 batch_size 变成真实并发，而不被全局
    # max_concurrent 卡住、也不挤占其他任务（视频等）的额度。
    lane: str = ""
    # start() 取到的额度对象，release 时按同一对象归还，避免中途换额度导致失衡
    _limiter: Any = None


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
        # lane（按批独立额度）：lane 名 -> Semaphore，以及其额度大小（用于状态展示）
        self._lane_limiters: dict[str, asyncio.Semaphore] = {}
        self._lane_sizes: dict[str, int] = {}

    # ---------------- 并发额度（全局 + 按批 lane） ----------------

    def set_max_concurrent(self, max_concurrent: int) -> int:
        """调整全局并发上限，返回实际生效值。

        只换全局 Semaphore 对象：调用方应在启动阶段（无在跑任务）使用，
        或接受"在跑的任务持旧对象、新任务按新额度"的过渡。
        """
        value = max(1, int(max_concurrent))
        self.max_concurrent = value
        self._semaphore = asyncio.Semaphore(value)
        return value

    def ensure_lane(self, lane: str, size: int | None = None) -> asyncio.Semaphore:
        """取得（必要时创建）某批次的独立额度。

        额度一旦创建就不再改变——已经入队的任务正等着它，中途换对象会让
        等待者永远等不到。size 只在该 lane 首次创建时生效。
        """
        limit = max(1, int(size)) if size else self.max_concurrent
        limiter = self._lane_limiters.get(lane)
        if limiter is None:
            limiter = asyncio.Semaphore(limit)
            self._lane_limiters[lane] = limiter
            self._lane_sizes[lane] = limit
            logger.info(f"[Queue] 新建并发额度 lane={lane} size={limit}")
        elif size is not None and self._lane_sizes.get(lane) != limit:
            logger.warning(
                f"[Queue] lane={lane} 已有额度 {self._lane_sizes.get(lane)}，"
                f"忽略新的 size={limit}（在跑任务正等旧额度）"
            )
        return limiter

    def release_lane(self, lane: str) -> bool:
        """批次结束后释放额度对象，避免 _lane_limiters 无界增长。"""
        self._lane_sizes.pop(lane, None)
        existed = self._lane_limiters.pop(lane, None) is not None
        if existed:
            logger.info(f"[Queue] 释放并发额度 lane={lane}")
        return existed

    def _limiter_for(self, task: DownloadTask) -> asyncio.Semaphore:
        """任务该用哪个额度：有 lane 用独立额度，否则用全局。"""
        if task.lane:
            limiter = self._lane_limiters.get(task.lane)
            if limiter is None:
                limiter = self.ensure_lane(task.lane)
            return limiter
        return self._semaphore

    @property
    def lane_sizes(self) -> dict[str, int]:
        """当前活跃的按批额度（仅供状态展示/排查）。"""
        return dict(self._lane_sizes)
    
    def add_cleanup_callback(self, callback: Callable):
        """添加清理回调函数"""
        self._cleanup_callbacks.append(callback)
    
    async def add_task(self, task_id: str, url: str, platform: str, 
                       title: str, download_func: Callable,
                       lane: str = "", lane_size: int | None = None) -> DownloadTask:
        """
        添加下载任务到队列
        
        Args:
            task_id: 任务ID
            url: 下载URL
            platform: 平台名称
            title: 视频标题
            download_func: 下载函数，接收 DownloadTask 参数
            lane: 独立并发额度名（歌单批量用）；空串走全局额度
            lane_size: 该 lane 的并发数，仅首次创建时生效
        
        Returns:
            DownloadTask 对象
        """
        if lane:
            self.ensure_lane(lane, lane_size)
        task = DownloadTask(
            task_id=task_id,
            url=url,
            platform=platform,
            title=title,
            status=TaskStatus.PENDING,
            download_func=download_func,  # 保存下载函数引用
            lane=lane,
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
            if task is None:
                # stop() 放的停止哨兵
                self.queue.task_done()
                break
            # 不能在循环里 await 额度：某批 lane 占满时会卡住整个派发
            # 循环，排在后面的其他任务（视频、别的批）即使额度空闲也起
            # 不来 —— 队首阻塞会直接废掉"按批独立额度、互不影响"的设计。
            # 取额度交给每个任务自己的协程，循环只负责派发。
            asyncio.create_task(self._process_task(task, download_func))

    async def stop(self):
        """停止队列派发（放哨兵叫醒阻塞在 queue.get() 上的循环）。

        只停派发，不影响已在跑的任务；下次 start() 可重新启动。
        """
        self._running = False
        await self.queue.put((None, None))
    
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
        # 取并发额度（全局或按批 lane）。只在这里取，_process_task 直接
        # 被调用的路径（测试/手动，_running 为 False）不取也不归还，
        # 避免额度只涨不跌。
        if self._running:
            limiter = self._limiter_for(task)
            await limiter.acquire()
            # 记下取额度用的具体对象：set_max_concurrent 会换掉全局
            # Semaphore，归还时必须还回同一个，否则旧对象额度只涨、
            # 新对象被饿死。
            task._limiter = limiter
        try:
            task.status = TaskStatus.DOWNLOADING
            result = await download_func(task)
            
            # 检查 download_func 是否已设置失败状态
            if task.status == TaskStatus.FAILED:
                # download_func 已标记失败，不再覆盖
                pass
            elif task.status == TaskStatus.PAUSED:
                # 条目边界暂停：download_func 正常 return 但标记了暂停，
                # 不能被下面的 else 覆盖成 COMPLETED（resume 会重跑）
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
            # 只归还 start() 实际取到的那个额度对象。直接调用
            # _process_task 的路径（测试/手动）没有取额度，不能归还，
            # 否则 Semaphore 只涨不跌、并发上限形同虚设。
            limiter = task._limiter
            if limiter is not None:
                task._limiter = None
                limiter.release()
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
            "lane_sizes": dict(self._lane_sizes),
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
                    "error": t.error,
                    "lane": t.lane,
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
