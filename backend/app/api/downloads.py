import asyncio
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc

from app.core.dependencies import get_db
from app.models.download_task import DownloadTask
from app.models.media_item import MediaItem
from app.schemas.download import (
    ParseURLRequest, ParseURLResponse, CreateDownloadRequest,
    DownloadTaskResponse, DownloadListResponse,
)
from app.services.parser_factory import get_parser_for_url
from app.services.aria2_downloader import Aria2Downloader
from app.services.background import run_download

router = APIRouter()


@router.post("/parse", response_model=ParseURLResponse)
async def parse_url(req: ParseURLRequest):
    parser = get_parser_for_url(req.url)
    if not parser:
        raise HTTPException(400, f"不支持的 URL: {req.url}")
    return await parser.parse_url(req.url)


@router.post("/create", response_model=DownloadTaskResponse)
async def create_download(req: CreateDownloadRequest, db: Session = Depends(get_db)):
    task = DownloadTask(
        url=req.url,
        platform=req.platform,
        format_id=req.format_id,
        title=req.title,
        media_type=req.media_type,
        status="pending",
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    asyncio.create_task(run_download(task.id))
    await asyncio.sleep(0)  # 让后台任务立即开始调度

    return task


@router.get("", response_model=DownloadListResponse)
async def list_downloads(
    page: int = 1,
    size: int = 20,
    status: str = "",
    db: Session = Depends(get_db),
):
    query = db.query(DownloadTask)
    if status:
        query = query.filter(DownloadTask.status == status)
    total = query.count()
    items = query.order_by(desc(DownloadTask.created_at)).offset(
        (page - 1) * size
    ).limit(size).all()
    return DownloadListResponse(items=items, total=total)


@router.get("/{task_id}", response_model=DownloadTaskResponse)
async def get_download(task_id: str, db: Session = Depends(get_db)):
    task = db.query(DownloadTask).filter(DownloadTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.post("/{task_id}/cancel")
async def cancel_download(task_id: str, db: Session = Depends(get_db)):
    task = db.query(DownloadTask).filter(DownloadTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    task.status = "failed"
    task.error_message = "用户取消"
    db.commit()
    return {"message": "已取消"}


@router.post("/{task_id}/retry", response_model=DownloadTaskResponse)
async def retry_download(task_id: str, db: Session = Depends(get_db)):
    task = db.query(DownloadTask).filter(DownloadTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")
    task.status = "pending"
    task.progress = 0.0
    task.error_message = ""
    db.commit()

    asyncio.create_task(run_download(task.id))
    await asyncio.sleep(0)  # 让后台任务立即开始调度
    return task


@router.delete("/{task_id}")
async def delete_download(task_id: str, db: Session = Depends(get_db)):
    task = db.query(DownloadTask).filter(DownloadTask.id == task_id).first()
    if not task:
        raise HTTPException(404, "任务不存在")

    db.query(MediaItem).filter(MediaItem.task_id == task_id).delete()
    db.delete(task)
    db.commit()
    return {"message": "已删除"}


@router.post("/batch-delete")
async def batch_delete_downloads(ids: list[str], db: Session = Depends(get_db)):
    if not ids:
        raise HTTPException(400, "请提供要删除的 ID 列表")

    deleted = 0
    for tid in ids:
        task = db.query(DownloadTask).filter(DownloadTask.id == tid).first()
        if task:
            db.query(MediaItem).filter(MediaItem.task_id == tid).delete()
            db.delete(task)
            deleted += 1
    db.commit()
    return {"message": f"已删除 {deleted} 个任务"}


@router.post("/magnet")
async def download_magnet(magnet: str, title: str = ""):
    """通过磁力链接下载 BT 资源"""
    aria2 = Aria2Downloader()
    if not await aria2.is_available():
        raise HTTPException(400, "aria2c 未安装，请先安装 aria2")
    try:
        file_path = await aria2.download_magnet(magnet)
        return {"file_path": str(file_path) if file_path else None, "status": "completed"}
    except RuntimeError as e:
        raise HTTPException(500, str(e))
