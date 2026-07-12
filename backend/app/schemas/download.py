from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class ParseURLRequest(BaseModel):
    url: str


class FormatInfo(BaseModel):
    format_id: str
    quality: str
    ext: str
    file_size: Optional[int] = None
    is_audio: bool = False
    is_video: bool = False


class ParseURLResponse(BaseModel):
    title: str
    platform: str
    media_type: str
    formats: list[FormatInfo]
    thumbnail: str = ""
    duration: int = 0


class CreateDownloadRequest(BaseModel):
    url: str
    platform: str
    format_id: str
    title: str = ""
    media_type: str = "music"


class DownloadTaskResponse(BaseModel):
    id: str
    url: str
    platform: str
    title: str
    status: str
    progress: float
    file_size: int
    file_path: str = ""
    error_message: str
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class DownloadListResponse(BaseModel):
    items: list[DownloadTaskResponse]
    total: int


class BatchDownloadRequest(BaseModel):
    items: list[CreateDownloadRequest]


class PlaylistParseRequest(BaseModel):
    url: str


class PlaylistItem(BaseModel):
    url: str
    title: str
    duration: int = 0
    thumbnail: str = ""


class PlaylistParseResponse(BaseModel):
    title: str
    platform: str
    items: list[PlaylistItem]


class SearchRequest(BaseModel):
    keyword: str
    platform: str = "all"


class SearchResult(BaseModel):
    platform: str
    title: str
    artist: str
    url: str
    duration: int = 0
    thumbnail: str = ""


class SearchResponse(BaseModel):
    results: list[SearchResult]
