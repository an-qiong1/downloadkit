from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    # Database
    DATABASE_URL: str = "sqlite:///D:/Dowland/media-fetch/backend/data/media_fetch.db"

    # Download
    DOWNLOAD_DIR: str = "D:/Dowland/media-fetch/downloads"
    MAX_CONCURRENT_DOWNLOADS: int = 3
    TEMP_DIR: str = "D:/Dowland/media-fetch/downloads/temp"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    @property
    def redis_url(self) -> str:
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"

    @property
    def celery_broker_url(self) -> str:
        return self.redis_url

    @property
    def celery_result_backend(self) -> str:
        return self.redis_url

    @property
    def download_dir_path(self) -> Path:
        return Path(self.DOWNLOAD_DIR)

    @property
    def temp_dir_path(self) -> Path:
        return Path(self.TEMP_DIR)

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
