# -*- coding: utf-8 -*-
"""网易云音乐解析器 - 使用官方搜索 API + yt-dlp 下载"""

import re
import httpx
from typing import Optional

from app.utils.ytdlp import ytdlp_dump_json, ytdlp_base_cmd
from app.services.parsers.base import BaseParser
from app.schemas.download import ParseURLResponse, FormatInfo, PlaylistParseResponse, PlaylistItem, SearchResult


_NETEASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://music.163.com/",
}


class NeteaseParser(BaseParser):
    """网易云音乐解析器"""

    @property
    def platform(self) -> str:
        return "netease"

    @staticmethod
    def can_handle(url: str) -> bool:
        return bool(re.search(r'music\.163\.com', url))

    @staticmethod
    def _from_timestamp(ms: int) -> int:
        return ms // 1000 if ms else 0

    async def _api_get(self, endpoint: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://music.163.com{endpoint}",
                headers=_NETEASE_HEADERS,
            )
            return resp.json()

    async def _extract_song_id(self, url: str) -> Optional[str]:
        m = re.search(r'(?:song\?id=|song/)(\d+)', url)
        return m.group(1) if m else None

    async def _extract_playlist_id(self, url: str) -> Optional[str]:
        m = re.search(r'(?:playlist\?id=|playlist/)(\d+)', url)
        return m.group(1) if m else None

    async def _parse_from_page(self, url: str, song_id: str) -> Optional[ParseURLResponse]:
        """从歌曲页面 HTML 中提取元数据（OG 标签）"""
        async with httpx.AsyncClient(timeout=15, headers=_NETEASE_HEADERS) as client:
            try:
                resp = await client.get(f"https://music.163.com/song?id={song_id}")
                text = resp.text
                og_title = re.search(r'<meta property="og:title"[^>]+content="([^"]+)"', text)
                og_image = re.search(r'<meta property="og:image"[^>]+content="([^"]+)"', text)
                if og_title:
                    title = og_title.group(1)
                    thumbnail = og_image.group(1) if og_image else ""
                    # 去掉 og:title 中的歌手前缀 "artist - title"
                    parts = title.split(" - ", 1)
                    clean_title = parts[-1].strip() if len(parts) > 1 else title
                    return ParseURLResponse(
                        title=clean_title,
                        platform=self.platform,
                        media_type="music",
                        formats=[
                            FormatInfo(format_id="bestaudio", quality="最佳音质", ext="mp3",
                                      is_audio=True, is_video=False),
                            FormatInfo(format_id="bestaudio[ext=m4a]", quality="AAC 格式", ext="m4a",
                                      is_audio=True, is_video=False),
                        ],
                        thumbnail=thumbnail,
                        duration=0,
                    )
            except Exception:
                pass
        return None

    async def parse_url(self, url: str) -> ParseURLResponse:
        song_id = await self._extract_song_id(url)
        if not song_id:
            raise ValueError("无法从 URL 中提取歌曲 ID")

        # 先尝试 yt-dlp（新版可能修好），失败则降级到页面提取
        try:
            data = await ytdlp_dump_json(url)
            title = data.get("title", "网易云音乐")
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
            page = await self._parse_from_page(url, song_id)
            if page:
                return page
            raise ValueError("网易云音乐暂时无法解析此歌曲（API 限制），请尝试使用搜索或其他平台下载")

    async def get_download_command(self, url: str, format_id: str, output_path: str) -> list[str]:
        # yt-dlp 的网易云提取器在 2026.03.17 版本损坏（IndexError）
        # 返回命令时加 --ignore-errors 确保不卡住，
        # 如果失败会在 execute_download 中标记为 failed 并给出友好提示
        cmd = ytdlp_base_cmd() + ["-f", format_id, "-o", output_path,
                                  "--ignore-errors"]
        if format_id == "bestaudio":
            cmd.extend(["--extract-audio", "--audio-format", "mp3",
                       "--embed-thumbnail", "--add-metadata"])
        return cmd + [url]

    async def parse_playlist(self, url: str) -> Optional[PlaylistParseResponse]:
        playlist_id = await self._extract_playlist_id(url)
        if not playlist_id:
            return None

        # yt-dlp 解析播放列表
        data = await ytdlp_dump_json(url, flat=True)
        if isinstance(data, dict):
            data = [data]

        items = []
        title = "网易云歌单"
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
        """使用网易云官方搜索 API"""
        data = await self._api_get(f"/api/search/get?s={keyword}&type=1&limit=20")
        if data.get("code") != 200:
            return []

        songs = data.get("result", {}).get("songs", [])
        results = []
        for s in songs:
            sid = str(s.get("id", ""))
            artists = ", ".join(a.get("name", "") for a in s.get("artists", []))
            album = s.get("album", {})
            pic_url = album.get("picUrl", "") if album else ""
            results.append(SearchResult(
                platform=self.platform,
                title=s.get("name", ""),
                artist=artists,
                url=f"https://music.163.com/song?id={sid}",
                duration=self._from_timestamp(s.get("duration", 0)),
                thumbnail=pic_url,
            ))
        return results
