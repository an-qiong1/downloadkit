# -*- coding: utf-8 -*-
"""Spotify 解析器 - 使用 yt-dlp 解析和下载"""

import re
from typing import Optional

from app.utils.ytdlp import ytdlp_dump_json, ytdlp_base_cmd
from app.services.parsers.base import BaseParser
from app.schemas.download import ParseURLResponse, FormatInfo, PlaylistParseResponse, PlaylistItem, SearchResult


class SpotifyParser(BaseParser):
    """Spotify 解析器"""

    @property
    def platform(self) -> str:
        return "spotify"

    @staticmethod
    def can_handle(url: str) -> bool:
        return bool(re.search(r'open\.spotify\.com', url))

    async def _extract_track_id(self, url: str) -> Optional[str]:
        m = re.search(r'track/([a-zA-Z0-9]+)', url)
        return m.group(1) if m else None

    async def _extract_playlist_id(self, url: str) -> Optional[str]:
        m = re.search(r'playlist/([a-zA-Z0-9]+)', url)
        return m.group(1) if m else None

    async def parse_url(self, url: str) -> ParseURLResponse:
        data = await ytdlp_dump_json(url)

        title = data.get("title", "Spotify 歌曲")
        duration = data.get("duration", 0)
        thumbnail = data.get("thumbnail", "")

        formats = [
            FormatInfo(format_id="bestaudio", quality="最佳音质", ext="mp3",
                      is_audio=True, is_video=False),
            FormatInfo(format_id="bestaudio[ext=m4a]", quality="AAC 格式", ext="m4a",
                      is_audio=True, is_video=False),
        ]

        return ParseURLResponse(
            title=title,
            platform=self.platform,
            media_type="music",
            formats=formats,
            thumbnail=thumbnail,
            duration=duration,
        )

    async def get_download_command(self, url: str, format_id: str, output_path: str) -> list[str]:
        cmd = ytdlp_base_cmd() + ["-f", format_id, "-o", output_path]
        if format_id == "bestaudio":
            cmd.extend(["--extract-audio", "--audio-format", "mp3",
                       "--embed-thumbnail", "--add-metadata"])
        return cmd + [url]

    async def parse_playlist(self, url: str) -> Optional[PlaylistParseResponse]:
        playlist_id = await self._extract_playlist_id(url)
        if not playlist_id:
            return None

        data = await ytdlp_dump_json(url, flat=True)
        if isinstance(data, dict):
            data = [data]

        items = []
        title = "Spotify 歌单"
        for entry in data:
            if "playlist_title" in entry and entry["playlist_title"]:
                title = entry["playlist_title"]
            items.append(PlaylistItem(
                url=entry.get("webpage_url", ""),
                title=entry.get("title", ""),
                duration=entry.get("duration", 0) or 0,
                thumbnail=entry.get("thumbnail", ""),
            ))

        return PlaylistParseResponse(title=title, platform=self.platform, items=items) if items else None

    async def search(self, keyword: str) -> list[SearchResult]:
        """Spotify 搜索 API 不可用，返回空"""
        return []
