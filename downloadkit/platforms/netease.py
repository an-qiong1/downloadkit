"""网易云音乐 -- 搜索用 API，下载用外链重定向。"""

import re, httpx, logging
from typing import Optional
from datetime import datetime
from .base import BasePlatform, SongInfo, PlaylistInfo

logger = logging.getLogger(__name__)

OUTER_URL = "https://music.163.com/song/media/outer/url"
SEARCH_URL = "https://music.163.com/api/search/get"
PLAYLIST_URL = "https://music.163.com/api/playlist/detail"
SONG_DETAIL_URL = "https://music.163.com/api/song/detail"
LYRICS_URL = "https://music.163.com/api/song/lyric"


# ── API 响应格式辅助函数 ──────────────────────────────────────────
# 网易云 API 经历了格式变更：旧版用 ar/al，新版用 artists/album。
# 以下函数兼容两种格式。

def _extract_artists(item: dict) -> list[dict]:
    """兼容新旧 artist 字段格式。"""
    artists = item.get("artists") or item.get("ar")
    if isinstance(artists, list):
        return artists
    return []


def _extract_album(item: dict) -> dict:
    """兼容新旧 album 字段格式。"""
    album = item.get("album") or item.get("al")
    return album if isinstance(album, dict) else {}


def _get_cover_url(album: dict) -> str:
    """从 album 对象中提取封面 URL，兼容新旧格式。"""
    url = album.get("picUrl") or ""
    if not url and album.get("picId"):
        # 构造封面 URL: https://p4.music.126.net/{hash}/{picId}.jpg
        # 使用通用的格式
        url = f"https://p4.music.126.net/{album.get('picId')}/{album['picId']}.jpg"
    if not url and album.get("blurPicUrl"):
        url = album["blurPicUrl"]
    return url


def _get_album_name(album: dict) -> str:
    return album.get("name") or ""


def _get_artist_name(artist: dict) -> str:
    return artist.get("name") or ""


def _parse_song_item(item: dict, platform: str = "netease") -> Optional[SongInfo]:
    """从搜索/歌单/详情接口的歌曲对象中解析 SongInfo。"""
    try:
        artists = _extract_artists(item)
        album = _extract_album(item)
        return SongInfo(
            title=item.get("name", ""),
            artist="/".join(_get_artist_name(a) for a in artists if _get_artist_name(a)),
            album=_get_album_name(album),
            duration=item.get("dt", item.get("duration", 0)) // 1000,
            platform=platform,
            song_id=str(item.get("id", "")),
            cover=_get_cover_url(album),
            track_number=item.get("no", 0) or 0,
            year=_parse_year(album.get("publishTime")),
        )
    except Exception as e:
        logger.warning(f"[netease] 解析歌曲对象失败: {e}")
        return None


def _parse_year(publish_time) -> int:
    """从发布时间戳解析年份。"""
    if not publish_time:
        return 0
    try:
        return datetime.fromtimestamp(publish_time / 1000).year
    except (OSError, ValueError, OverflowError):
        return 0


class NeteasePlatform(BasePlatform):
    name = "netease"
    display_name = "NetEase Cloud Music"

    def __init__(self):
        self._client = httpx.AsyncClient(timeout=30, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://music.163.com/",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        self._session_initialized = False

    async def _ensure_session(self):
        """确保获取有效的会话cookie"""
        if self._session_initialized:
            return
        try:
            resp = await self._client.get("https://music.163.com/")
            self._client.cookies.set("os", "pc")
            self._client.cookies.set("appver", "2.10.15")
            self._client.cookies.set("channel", "netease")
            self._session_initialized = True
        except Exception as e:
            logger.warning(f"网易云session初始化失败: {e}")

    async def search(self, keyword: str, limit: int = 20) -> list[SongInfo]:
        await self._ensure_session()
        params = {"s": keyword, "type": 1, "limit": min(limit, 100), "offset": 0}
        resp = await self._client.post(SEARCH_URL, data=params)
        data = resp.json()
        if data.get("code") != 200:
            return []
        songs = []
        for item in data.get("result", {}).get("songs", [])[:limit]:
            parsed = _parse_song_item(item, self.name)
            if parsed:
                songs.append(parsed)
        return songs

    async def get_song_url(self, song: SongInfo) -> str | None:
        return f"{OUTER_URL}?id={song.song_id}.mp3"

    async def get_song_detail(self, song_id: str) -> SongInfo | None:
        """获取歌曲完整元数据（含音轨号、年份）。"""
        if not song_id:
            return None
        await self._ensure_session()
        try:
            resp = await self._client.get(
                SONG_DETAIL_URL,
                params={"id": song_id, "ids": f"[{song_id}]"}
            )
            data = resp.json()
            if data.get("code") == 200:
                songs_data = data.get("songs", [])
                if songs_data:
                    return _parse_song_item(songs_data[0], self.name)
        except Exception as e:
            logger.warning(f"[netease] 获取歌曲详情失败: {e}")
        return None

    async def get_lyrics(self, song_id: str) -> tuple[str, str] | None:
        """获取歌词，返回 (原文歌词, 翻译歌词)。"""
        if not song_id:
            return None
        await self._ensure_session()
        try:
            resp = await self._client.get(
                LYRICS_URL,
                params={"id": song_id, "lv": 1, "kv": 1, "tv": -1}
            )
            data = resp.json()
            if data.get("code") != 200:
                return None
            original = (data.get("lrc") or {}).get("lyric", "") or ""
            translation = (data.get("tlyric") or {}).get("lyric", "") or ""
            if not original:
                return None
            return (original, translation)
        except Exception as e:
            logger.warning(f"[netease] 获取歌词失败: {e}")
            return None

    async def get_song_info(self, song_id: str) -> SongInfo | None:
        """获取单曲详情（兼容旧接口调用方）。"""
        return await self.get_song_detail(song_id)

    async def get_playlist(self, playlist_id: str) -> PlaylistInfo:
        await self._ensure_session()

        try:
            resp = await self._client.get(PLAYLIST_URL, params={"id": playlist_id})
            data = resp.json()

            if data.get("code") != 200:
                raise ValueError(f"API返回错误: {data.get('message', data.get('code'))}")

            pl = data.get("result") or data.get("playlist") or {}
            if not pl:
                raise ValueError("歌单数据为空")

            songs = []
            tracks = pl.get("tracks", [])

            # tracks 为空但有 trackIds 时，逐批拉取
            if not tracks and pl.get("trackIds"):
                track_ids = pl.get("trackIds", [])
                logger.info(f"从 {len(track_ids)} 个 trackIds 批量获取歌曲详情")
                batch_size = 1000
                for i in range(0, len(track_ids), batch_size):
                    batch = track_ids[i:i + batch_size]
                    ids_str = ",".join(
                        str(t.get("id", t) if isinstance(t, dict) else t) for t in batch
                    )
                    try:
                        detail_resp = await self._client.get(
                            SONG_DETAIL_URL,
                            params={"ids": f"[{ids_str}]"}
                        )
                        detail_data = detail_resp.json()
                        if detail_data.get("code") == 200:
                            for s in detail_data.get("songs", []):
                                parsed = _parse_song_item(s, self.name)
                                if parsed:
                                    songs.append(parsed)
                    except Exception as e:
                        logger.warning(f"批量获取歌曲详情失败: {e}")
                        continue
            else:
                for track in tracks:
                    parsed = _parse_song_item(track, self.name)
                    if parsed:
                        songs.append(parsed)

            cover = (pl.get("coverImgUrl") or pl.get("coverImgUrl") or
                     _get_cover_url(pl) or "")
            return PlaylistInfo(
                name=pl.get("name", ""),
                description=pl.get("description") or "",
                cover=cover,
                platform=self.name,
                song_count=pl.get("trackCount", len(songs)),
                songs=songs,
            )
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"歌单解析异常: {e}")
            raise ValueError(f"歌单解析失败: {str(e)}") from e

    @staticmethod
    def match_url(url: str) -> bool:
        return bool(re.search(r"music\.163\.com", url))

    @staticmethod
    def extract_playlist_id(url: str) -> str:
        if '/song' in url and '/song' in url.split('?')[0]:
            raise ValueError("This is a single song URL, not a playlist URL")
        m = re.search(r"[?&]id=(\d+)", url)
        if m:
            return m.group(1)
        m = re.search(r"/playlist/(\d+)", url)
        if m:
            return m.group(1)
        raise ValueError(f"Cannot extract playlist ID: {url}")
