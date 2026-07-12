# -*- coding: utf-8 -*-
"""QQ 音乐解析器 - 使用官方搜索 API + yt-dlp 下载"""

import re
import httpx
from typing import Optional

from app.utils.ytdlp import ytdlp_dump_json, ytdlp_base_cmd
from app.services.parsers.base import BaseParser
from app.schemas.download import ParseURLResponse, FormatInfo, PlaylistParseResponse, PlaylistItem, SearchResult


_QQ_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://y.qq.com/",
}


class QQMusicParser(BaseParser):
    """QQ 音乐解析器"""

    @property
    def platform(self) -> str:
        return "qqmusic"

    @staticmethod
    def can_handle(url: str) -> bool:
        return bool(re.search(r'y\.qq\.com', url))

    async def _extract_song_mid(self, url: str) -> Optional[str]:
        m = re.search(r'song/(\w+)\.html', url)
        if not m:
            m = re.search(r'songDetail/(\w+)', url)
        if not m:
            m = re.search(r'songmid=(\w+)', url)
        return m.group(1) if m else None

    async def _extract_playlist_id(self, url: str) -> Optional[str]:
        m = re.search(r'playlist/(\d+)\.html', url)
        return m.group(1) if m else None

    async def parse_url(self, url: str) -> ParseURLResponse:
        # 尝试 yt-dlp，失败则返回基本元数据
        try:
            data = await ytdlp_dump_json(url)
            title = data.get("title", "QQ音乐歌曲")
            duration = data.get("duration", 0)
            thumbnail = data.get("thumbnail", "")
            formats = [
                FormatInfo(format_id="bestaudio", quality="最佳音质", ext="mp3",
                          is_audio=True, is_video=False),
                FormatInfo(format_id="bestaudio[ext=m4a]", quality="AAC 格式", ext="m4a",
                          is_audio=True, is_video=False),
            ]
            return ParseURLResponse(
                title=title, platform=self.platform, media_type="music",
                formats=formats, thumbnail=thumbnail, duration=duration,
            )
        except Exception:
            # yt-dlp 提取器失败时，从 URL 提取歌曲 mid 并返回基本信息
            mid = await self._extract_song_mid(url)
            if not mid:
                raise ValueError("无法解析此 QQ 音乐链接")
            return ParseURLResponse(
                title=f"QQ音乐 - {mid}",
                platform=self.platform,
                media_type="music",
                formats=[
                    FormatInfo(format_id="bestaudio", quality="最佳音质", ext="mp3",
                              is_audio=True, is_video=False),
                ],
                thumbnail="",
                duration=0,
            )

    async def get_download_command(self, url: str, format_id: str, output_path: str) -> list[str]:
        # yt-dlp QQ 音乐提取器需要 songDetail/xxx 格式（非 song/xxx.html）
        fixed_url = re.sub(r'/song/[^/]+\.html', lambda m: '/songDetail/' + m.group(0).split('/')[-1].split('.')[0], url)
        if fixed_url == url:
            fixed_url = re.sub(r'/song/([^/]+)', r'/songDetail/\1', url)
        cmd = ytdlp_base_cmd() + ["-f", format_id, "-o", output_path]
        if format_id == "bestaudio":
            cmd.extend(["--extract-audio", "--audio-format", "mp3",
                       "--embed-thumbnail", "--add-metadata"])
        return cmd + [fixed_url]

    async def parse_playlist(self, url: str) -> Optional[PlaylistParseResponse]:
        playlist_id = await self._extract_playlist_id(url)
        if not playlist_id:
            return None

        # yt-dlp 解析播放列表
        data = await ytdlp_dump_json(url, flat=True)
        if isinstance(data, dict):
            data = [data]

        items = []
        title = "QQ音乐歌单"
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
        """使用 QQ 音乐官方搜索 API"""
        url = f"https://c.y.qq.com/splcloud/fcgi-bin/smartbox_new.fcg?key={keyword}"
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, headers=_QQ_HEADERS)
            data = resp.json()
            songs = data.get("data", {}).get("song", {}).get("itemlist", [])

        results = []
        for s in songs:
            mid = s.get("mid", "")
            name = s.get("name", "")
            singer = s.get("singer", "")
            results.append(SearchResult(
                platform=self.platform,
                title=name,
                artist=singer,
                url=f"https://y.qq.com/n/ryqq/songDetail/{mid}",
                duration=s.get("interval", 0),
                thumbnail=f"https://y.gtimg.cn/music/photo_new/T002R300x300M000{s.get('pic', '')}.jpg" if s.get('pic') else "",
            ))
        return results
