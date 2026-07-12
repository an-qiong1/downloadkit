# -*- coding: utf-8 -*-
"""YouTube 解析器 - 视频+音乐+播放列表"""

import re
from typing import Optional

from app.utils.ytdlp import ytdlp_dump_json, ytdlp_search, ytdlp_base_cmd
from app.services.parsers.base import BaseParser
from app.schemas.download import ParseURLResponse, FormatInfo, PlaylistParseResponse, PlaylistItem, SearchResult


class YouTubeParser(BaseParser):
    """YouTube 解析器"""

    @property
    def platform(self) -> str:
        return "youtube"

    @staticmethod
    def can_handle(url: str) -> bool:
        patterns = [
            r'youtube\.com/watch\?v=',
            r'youtu\.be/',
            r'youtube\.com/playlist\?list=',
            r'youtube\.com/@',
            r'youtube\.com/channel/',
        ]
        return any(re.search(p, url) for p in patterns)

    async def _extract_video_id(self, url: str) -> Optional[str]:
        m = re.search(r'(?:v=|youtu\.be/|shorts/)([a-zA-Z0-9_-]{11})', url)
        return m.group(1) if m else None

    async def _extract_playlist_id(self, url: str) -> Optional[str]:
        m = re.search(r'[?&]list=([a-zA-Z0-9_-]+)', url)
        return m.group(1) if m else None

    async def parse_url(self, url: str) -> ParseURLResponse:
        data = await ytdlp_dump_json(url)

        title = data.get("title", "YouTube 视频")
        duration = data.get("duration", 0)
        thumbnail = data.get("thumbnail", "")
        categories = data.get("categories", [])
        is_music = "Music" in categories or any(k in title.lower() for k in ["song", "music", "audio", "cover"])

        formats = []
        if is_music:
            formats.append(
                FormatInfo(format_id="bestaudio", quality="最佳音频 (MP3)", ext="mp3",
                          is_audio=True, is_video=False)
            )
        else:
            heights = [f.get("height", 0) for f in data.get("formats", []) if f.get("height")]
            max_h = max(heights) if heights else 0
            if max_h >= 2160:
                formats.append(
                    FormatInfo(format_id="bestvideo[height<=2160]+bestaudio/best",
                              quality="4K 视频", ext="mp4", is_audio=False, is_video=True)
                )
            if max_h >= 1080:
                formats.append(
                    FormatInfo(format_id="bestvideo[height<=1080]+bestaudio/best",
                              quality="1080p 视频", ext="mp4", is_audio=False, is_video=True)
                )
            formats.append(
                FormatInfo(format_id="best", quality="最佳画质", ext="mp4",
                          is_audio=False, is_video=True)
            )
            formats.append(
                FormatInfo(format_id="bestaudio", quality="仅音频 (MP3)", ext="mp3",
                          is_audio=True, is_video=False)
            )

        return ParseURLResponse(
            title=title,
            platform=self.platform,
            media_type="music" if is_music else "video",
            formats=formats,
            thumbnail=thumbnail,
            duration=duration,
        )

    async def get_download_command(self, url: str, format_id: str, output_path: str) -> list[str]:
        cmd = ytdlp_base_cmd() + ["-f", format_id, "-o", output_path, "--no-playlist"]
        if format_id == "bestaudio":
            cmd.extend(["--extract-audio", "--audio-format", "mp3",
                       "--embed-thumbnail", "--add-metadata"])
        elif "bestvideo" in format_id:
            cmd.extend(["--merge-output-format", "mp4"])
        return cmd + [url]

    async def parse_playlist(self, url: str) -> Optional[PlaylistParseResponse]:
        playlist_id = await self._extract_playlist_id(url)
        if not playlist_id:
            return None

        data = await ytdlp_dump_json(f"https://www.youtube.com/playlist?list={playlist_id}", flat=True)
        if isinstance(data, dict):
            data = [data]

        items = []
        title = "YouTube 播放列表"
        for entry in data:
            if "playlist_title" in entry and entry["playlist_title"]:
                title = entry["playlist_title"]
            video_id = entry.get("id", "")
            items.append(PlaylistItem(
                url=f"https://www.youtube.com/watch?v={video_id}",
                title=entry.get("title", "未知"),
                duration=entry.get("duration", 0) or 0,
                thumbnail=entry.get("thumbnail", ""),
            ))

        return PlaylistParseResponse(title=title, platform=self.platform, items=items)

    async def search(self, keyword: str) -> list[SearchResult]:
        entries = await ytdlp_search(keyword, limit=10)
        results = []
        for entry in entries:
            video_id = entry.get("id", "")
            results.append(SearchResult(
                platform=self.platform,
                title=entry.get("title", ""),
                artist=entry.get("channel", ""),
                url=f"https://www.youtube.com/watch?v={video_id}",
                duration=entry.get("duration", 0) or 0,
                thumbnail=entry.get("thumbnail", ""),
            ))
        return results
