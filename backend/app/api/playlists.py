from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session

from app.core.dependencies import get_db
from app.models.download_task import DownloadTask
from app.schemas.download import (
    PlaylistParseRequest, PlaylistParseResponse,
    BatchDownloadRequest, DownloadTaskResponse,
)
from app.services.parser_factory import get_parser_for_url
from app.tasks.download_tasks import download_media

router = APIRouter()


@router.post("/parse", response_model=PlaylistParseResponse)
async def parse_playlist(req: PlaylistParseRequest):
    parser = get_parser_for_url(req.url)
    if not parser:
        raise HTTPException(400, f"不支持的 URL: {req.url}")
    result = await parser.parse_playlist(req.url)
    if not result:
        raise HTTPException(400, "该 URL 不是歌单或无法解析")
    return result


@router.post("/batch-download", response_model=list[DownloadTaskResponse])
async def batch_download(req: BatchDownloadRequest, db: Session = Depends(get_db)):
    created_tasks = []
    for item in req.items:
        task = DownloadTask(
            url=item.url,
            platform=item.platform,
            format_id=item.format_id,
            title=item.title,
            media_type=item.media_type,
            status="pending",
        )
        db.add(task)
        db.flush()
        download_media.delay(task.id)
        created_tasks.append(task)
    db.commit()
    return created_tasks
