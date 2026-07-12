import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, DateTime, Text, BigInteger
from app.core.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class DownloadTask(Base):
    __tablename__ = "download_tasks"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    url = Column(Text, nullable=False)
    platform = Column(String(50), nullable=False, index=True)
    title = Column(String(500), default="")
    media_type = Column(String(20), default="music")
    format_id = Column(String(100), default="")
    quality = Column(String(50), default="")
    status = Column(String(20), default="pending", index=True)
    progress = Column(Float, default=0.0)
    file_path = Column(Text, default="")
    file_size = Column(BigInteger, default=0)
    error_message = Column(Text, default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime, nullable=True)
