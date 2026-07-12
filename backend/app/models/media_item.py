import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, Text, BigInteger, Integer
from app.core.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class MediaItem(Base):
    __tablename__ = "media_items"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    task_id = Column(String(36), nullable=True, index=True)
    title = Column(String(500), default="")
    artist = Column(String(200), default="")
    album = Column(String(200), default="")
    duration = Column(Integer, default=0)
    platform = Column(String(50), nullable=False, index=True)
    media_type = Column(String(20), default="music")
    file_path = Column(Text, default="")
    file_size = Column(BigInteger, default=0)
    cover_path = Column(Text, default="")
    bitrate = Column(Integer, default=0)
    resolution = Column(String(20), default="")
    tags = Column(Text, default="[]")
    file_hash = Column(String(64), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
