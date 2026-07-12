import uuid
from sqlalchemy import Column, String, Text
from app.core.database import Base


def generate_uuid() -> str:
    return str(uuid.uuid4())


class PlatformConfig(Base):
    __tablename__ = "platform_configs"

    id = Column(String(36), primary_key=True, default=generate_uuid)
    platform = Column(String(50), nullable=False, index=True)
    config_key = Column(String(100), nullable=False)
    config_value = Column(Text, default="")
