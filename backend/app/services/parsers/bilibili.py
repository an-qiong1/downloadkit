# -*- coding: utf-8 -*-
"""Bilibili 解析器 - 视频+合集"""

import re
import json as j
import httpx
from typing import Optional

from app.utils.ytdlp import ytdlp_base_cmd, ytdlp_run
from app.services.parsers.base import BaseParser
from app.schemas.download import ParseURLResponse, FormatInfo, PlaylistParseResponse, PlaylistItem, SearchResult


# Bilibili API 请求头（反爬规避）
_BILI_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.bilibili.com/",
    "Origin": "https://www.bilibili.com",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


class BilibiliParser(BaseParser):
    """Bilibili 解析器"""

    @property
    def platform(self) -> str:
        return "bilibili"

    @staticmethod
    def can_handle(url: str) -> bool:
        return bool(re.search(r'bilibili\.com', url))

    async def _extract_bvid(self, url: str) -> Optional[str]:
        m = re.search(r'video/(BV[a-zA-Z0-9]+)', url)
        return m.group(1) if m else None

    async def _extract_series_id(self, url: str) -> Optional[str]:
        m = re.search(r'series/(\d+)', url)
        if m:
            return m.group(1)
        m = re.search(r'sid=(\d+)', url)
        return m.group(1) if m else None

    async def _get_video_info(self, bvid: str) -> dict:
        api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(api_url, headers=_BILI_HEADERS)
            data = resp.json()
            if data.get("code") != 0:
                raise ValueError(f"Bilibili API 错误: {data.get('message', '')}")
            return data.get("data", {})

    async def parse_url(self, url: str) -> ParseURLResponse:
        bvid = await self._extract_bvid(url)
        if not bvid:
            raise ValueError("无法解析 BV 号")

        info = await self._get_video_info(bvid)
        title = info.get("title", "Bilibili 视频")
        duration = info.get("duration", 0)
        pic = info.get("pic", "")

        formats = [
            FormatInfo(format_id="bestvideo+bestaudio/best",
                      quality="最高画质 (自动)", ext="mp4", is_audio=False, is_video=True),
            FormatInfo(format_id="bestvideo[height<=1080]+bestaudio/best",
                      quality="1080P 视频", ext="mp4", is_audio=False, is_video=True),
            FormatInfo(format_id="bestaudio",
                      quality="仅音频 (MP3)", ext="mp3", is_audio=True, is_video=False),
        ]

        return ParseURLResponse(
            title=title,
            platform=self.platform,
            media_type="video",
            formats=formats,
            thumbnail=pic,
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
        series_id = await self._extract_series_id(url)
        bvid = await self._extract_bvid(url)

        if series_id:
            api_url = (
                f"https://api.bilibili.com/x/web-interface/series/archives"
                f"?series_id={series_id}&pn=1&ps=100"
            )
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(api_url, headers=_BILI_HEADERS)
                data = resp.json()
                archives = data.get("data", {}).get("archives", [])
                title = data.get("data", {}).get("series", {}).get("title", "Bilibili 合集")
                items = []
                for a in archives:
                    items.append(PlaylistItem(
                        url=f"https://www.bilibili.com/video/{a.get('bvid', '')}",
                        title=a.get("title", ""),
                        duration=a.get("duration", 0),
                        thumbnail=a.get("pic", ""),
                    ))
                return PlaylistParseResponse(title=title, platform=self.platform, items=items)

        # 单个视频 → yt-dlp 获取系列
        try:
            output = await ytdlp_run("--flat-playlist", "--dump-json", "--no-download", url, timeout=30)
        except (RuntimeError, TimeoutError):
            return None

        items = []
        title = "Bilibili 播放列表"
        for line in output.strip().split("\n"):
            if not line:
                continue
            try:
                entry = j.loads(line)
                if "playlist_title" in entry and entry["playlist_title"]:
                    title = entry["playlist_title"]
                items.append(PlaylistItem(
                    url=entry.get("webpage_url", ""),
                    title=entry.get("title", ""),
                    duration=entry.get("duration", 0) or 0,
                    thumbnail=entry.get("thumbnail", ""),
                ))
            except j.JSONDecodeError:
                continue

        return PlaylistParseResponse(title=title, platform=self.platform, items=items) if items else None

    async def search(self, keyword: str) -> list[SearchResult]:
        search_url = (
            f"https://api.bilibili.com/x/web-interface/search/type"
            f"?search_type=video&keyword={keyword}&page=1"
        )
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(search_url, headers=_BILI_HEADERS)
            data = resp.json()
            if data.get("code") != 0:
                return []
            videos = data.get("data", {}).get("result", [])

        results = []
        for v in videos:
            bvid = v.get("bvid", "")
            if not bvid:
                continue
            title = v.get("title", "").replace("<em>", "").replace("</em>", "")
            results.append(SearchResult(
                platform=self.platform,
                title=title,
                artist=v.get("author", ""),
                url=f"https://www.bilibili.com/video/{bvid}",
                duration=v.get("duration", ""),
                thumbnail=v.get("pic", ""),
            ))
        return results
