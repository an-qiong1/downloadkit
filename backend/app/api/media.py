from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pathlib import Path

from app.core.dependencies import get_db
from app.models.media_item import MediaItem
from app.schemas.media import MediaItemResponse, MediaListResponse, MediaUpdateRequest

router = APIRouter()


@router.get("", response_model=MediaListResponse)
async def list_media(
    page: int = 1,
    size: int = 20,
    platform: str = "",
    media_type: str = "",
    search: str = "",
    db: Session = Depends(get_db),
):
    query = db.query(MediaItem)
    if platform:
        query = query.filter(MediaItem.platform == platform)
    if media_type:
        query = query.filter(MediaItem.media_type == media_type)
    if search:
        query = query.filter(MediaItem.title.contains(search))
    total = query.count()
    items = query.order_by(desc(MediaItem.created_at)).offset(
        (page - 1) * size
    ).limit(size).all()
    return MediaListResponse(items=items, total=total)


@router.get("/{item_id}", response_model=MediaItemResponse)
async def get_media(item_id: str, db: Session = Depends(get_db)):
    item = db.query(MediaItem).filter(MediaItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "媒体不存在")
    return item


@router.get("/{item_id}/stream")
async def stream_media(item_id: str, db: Session = Depends(get_db)):
    item = db.query(MediaItem).filter(MediaItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "媒体不存在")
    file_path = Path(item.file_path)
    if not file_path.exists():
        raise HTTPException(404, "文件不存在")
    return FileResponse(str(file_path))


@router.get("/{item_id}/cover")
async def get_cover(item_id: str, db: Session = Depends(get_db)):
    item = db.query(MediaItem).filter(MediaItem.id == item_id).first()
    if not item or not item.cover_path:
        raise HTTPException(404, "封面不存在")
    cover_path = Path(item.cover_path)
    if not cover_path.exists():
        raise HTTPException(404, "封面文件不存在")
    return FileResponse(str(cover_path))


@router.put("/{item_id}", response_model=MediaItemResponse)
async def update_media(item_id: str, req: MediaUpdateRequest, db: Session = Depends(get_db)):
    item = db.query(MediaItem).filter(MediaItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "媒体不存在")
    if req.title is not None:
        item.title = req.title
    if req.artist is not None:
        item.artist = req.artist
    if req.album is not None:
        item.album = req.album
    if req.tags is not None:
        item.tags = req.tags
    db.commit()
    return item


@router.delete("/{item_id}")
async def delete_media(item_id: str, db: Session = Depends(get_db)):
    item = db.query(MediaItem).filter(MediaItem.id == item_id).first()
    if not item:
        raise HTTPException(404, "媒体不存在")
    file_path = Path(item.file_path)
    if file_path.exists():
        file_path.unlink()
    db.delete(item)
    db.commit()
    return {"message": "已删除"}
