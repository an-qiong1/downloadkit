from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SongInfo:
    title: str
    artist: str
    album: str = ""
    duration: int = 0
    platform: str = ""
    song_id: str = ""
    url: str = ""
    cover: str = ""

    def __str__(self):
        return f"{self.title} - {self.artist}"


@dataclass
class PlaylistInfo:
    name: str
    description: str = ""
    cover: str = ""
    platform: str = ""
    song_count: int = 0
    songs: list[SongInfo] = field(default_factory=list)


class BasePlatform(ABC):
    name: str = "base"
    display_name: str = "Base"

    @abstractmethod
    async def search(self, keyword: str, limit: int = 20) -> list[SongInfo]:
        ...

    @abstractmethod
    async def get_song_url(self, song: SongInfo) -> str | None:
        ...

    @abstractmethod
    async def get_playlist(self, playlist_id: str) -> PlaylistInfo:
        ...

    @staticmethod
    @abstractmethod
    def match_url(url: str) -> bool:
        ...

    @staticmethod
    @abstractmethod
    def extract_playlist_id(url: str) -> str:
        ...
