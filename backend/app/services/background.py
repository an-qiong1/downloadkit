# -*- coding: utf-8 -*-
"""后台下载执行器 - 替代 Celery，直接异步执行下载任务"""

import asyncio
import logging
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.download_task import DownloadTask
from app.services.downloader import DownloadManager

logger = logging.getLogger("background")

# 延迟加载 WebSocket manager，避免模块导入时序问题
_ws_manager = None


def _get_ws_manager():
    global _ws_manager
    if _ws_manager is None:
        from app.api.ws import manager as ws
        _ws_manager = ws
    return _ws_manager


async def run_download(task_id: str):
    """在后台执行下载任务，通过 WebSocket 推送进度"""
    await asyncio.sleep(0)  # 确保事件循环正确调度

    ws = _get_ws_manager()
    db: Session = SessionLocal()
    try:
        task = db.query(DownloadTask).filter(DownloadTask.id == task_id).first()
        if not task:
            logger.error("任务 %s 不存在", task_id)
            return

        logger.info("开始下载任务 %s: %s", task_id, task.title)

        async def progress_callback(tid: str, progress: float, status: str):
            try:
                t = db.query(DownloadTask).filter(DownloadTask.id == tid).first()
                if t:
                    t.progress = progress
                    t.status = status
                    db.commit()
                await ws.send_progress(tid, progress, status)
            except Exception:
                pass

        manager = DownloadManager(db)
        await manager.execute_download(task, progress_callback)

        logger.info("下载任务 %s 完成, 状态: %s", task_id, task.status)

    except Exception as e:
        logger.exception("下载任务 %s 异常", task_id)
        try:
            task = db.query(DownloadTask).filter(DownloadTask.id == task_id).first()
            if task:
                task.status = "failed"
                task.error_message = str(e)[:500]
                db.commit()
        except Exception:
            pass
        try:
            await ws.send_progress(task_id, 0, "failed")
        except Exception:
            pass
    finally:
        db.close()
