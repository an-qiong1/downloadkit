"""歌单收藏 Pydantic 模型"""

from datetime import datetime
from pydantic import BaseModel
from typing import Optional


class TrackItem(BaseModel):
    """歌单中的单曲"""
    id: int
    title: str
    artist: str = ""
    album: str = ""
    song_id: str
    platform: str
    sort_order: int = 0

    class Config:
        from_attributes = True


class CollectionItem(BaseModel):
    """收藏歌单概要（列表用）"""
    id: int
    name: str
    url: str
    platform: str
    song_count: int = 0
    auto_name: bool = True
    created_at: str = ""
    refreshed_at: Optional[str] = None

    class Config:
        from_attributes = True


class CollectionDetail(BaseModel):
    """收藏歌单详情（含曲目列表）"""
    id: int
    name: str
    url: str
    platform: str
    song_count: int = 0
    auto_name: bool = True
    created_at: str = ""
    refreshed_at: Optional[str] = None
    tracks: list[TrackItem] = []

    class Config:
        from_attributes = True


class CreateCollectionRequest(BaseModel):
    """添加收藏请求"""
    url: str
    name: str = ""  # 可选自定义名称，为空则自动获取


class UpdateCollectionRequest(BaseModel):
    """更新收藏请求"""
    name: Optional[str] = None


class RefreshResponse(BaseModel):
    """刷新结果"""
    collection: CollectionDetail
    status: str = "ok"
    message: str = ""
