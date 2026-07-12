# -*- coding: utf-8 -*-
"""抖音解析器 - 去水印 + 动态照片识别"""

import re
import httpx
from typing import Optional

from app.utils.ytdlp import ytdlp_dump_json, ytdlp_base_cmd
from app.services.parsers.base import BaseParser
from app.schemas.download import ParseURLResponse, FormatInfo, PlaylistParseResponse, PlaylistItem, SearchResult


_DOUYIN_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.douyin.com/",
}


class DouyinParser(BaseParser):
    """抖音解析器"""

    @property
    def platform(self) -> str:
        return "douyin"

    @staticmethod
    def can_handle(url: str) -> bool:
        return bool(re.search(r'(douyin\.com|iesdouyin\.com|dy\d+)', url))

    async def parse_url(self, url: str) -> ParseURLResponse:
        # 使用 yt-dlp 获取视频信息
        data = await ytdlp_dump_json(url)

        title = data.get("title", "抖音视频") or data.get("description", "抖音视频")
        duration = data.get("duration", 0)
        thumbnail = data.get("thumbnail", "")

        # 检测动态照片（短视频 <= 30s + 有视频流）
        is_live_photo = 0 < duration <= 30
        media_type = "live_photo" if is_live_photo else "video"

        formats = [
            FormatInfo(
                format_id="bestvideo+bestaudio/best",
                quality="高清无水印" if not is_live_photo else "动态照片",
                ext="mp4",
                is_audio=False,
                is_video=True,
            ),
            FormatInfo(
                format_id="bestvideo[height<=1080]+bestaudio/best",
                quality="1080P 视频" if not is_live_photo else "1080P 动态照片",
                ext="mp4",
                is_audio=False,
                is_video=True,
            ),
        ]

        return ParseURLResponse(
            title=title,
            platform=self.platform,
            media_type=media_type,
            formats=formats,
            thumbnail=thumbnail,
            duration=duration,
        )

    async def get_download_command(self, url: str, format_id: str, output_path: str) -> list[str]:
        cmd = ytdlp_base_cmd() + ["-f", format_id, "-o", output_path, "--merge-output-format", "mp4", "--no-playlist"]
        return cmd + [url]

    async def parse_playlist(self, url: str) -> Optional[PlaylistParseResponse]:
        return None
