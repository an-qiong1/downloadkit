from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class MediaItemResponse(BaseModel):
    id: str
    task_id: Optional[str] = None
    title: str
    artist: str
    album: str
    duration: int
    platform: str
    media_type: str
    file_path: str
    file_size: int
    cover_path: str
    bitrate: int
    resolution: str
    tags: str
    created_at: datetime

    class Config:
        from_attributes = True


class MediaListResponse(BaseModel):
    items: list[MediaItemResponse]
    total: int


class MediaUpdateRequest(BaseModel):
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    tags: Optional[str] = None
