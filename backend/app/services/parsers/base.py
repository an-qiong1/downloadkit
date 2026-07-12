from abc import ABC, abstractmethod
from typing import Optional
from app.schemas.download import ParseURLResponse, FormatInfo, PlaylistParseResponse, SearchResult


class BaseParser(ABC):
    """所有平台解析器的抽象基类"""

    @property
    @abstractmethod
    def platform(self) -> str:
        pass

    @abstractmethod
    async def parse_url(self, url: str) -> ParseURLResponse:
        pass

    @abstractmethod
    async def get_download_command(self, url: str, format_id: str, output_path: str) -> list[str]:
        pass

    async def parse_playlist(self, url: str) -> Optional[PlaylistParseResponse]:
        return None

    async def search(self, keyword: str) -> list[SearchResult]:
        return []

    @staticmethod
    def can_handle(url: str) -> bool:
        return False
