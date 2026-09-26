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
    lyrics: str = ""         # 原文歌词
    lyrics_trans: str = ""   # 翻译歌词
    track_number: int = 0
    year: int = 0
    genre: str = ""

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

    # ── 可选方法：元数据补全 ──────────────────────────────────────
    async def get_song_detail(self, song_id: str) -> SongInfo | None:
        """获取歌曲完整元数据（含专辑、年份、音轨号等）。返回 None 表示未实现。"""
        return None

    async def get_lyrics(self, song_id: str) -> tuple[str, str] | None:
        """获取歌词。返回 (原文, 翻译) 或 None。"""
        return None
