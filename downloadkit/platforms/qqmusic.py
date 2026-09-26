import re
import json
import base64
import logging
import httpx
from .base import BasePlatform, SongInfo, PlaylistInfo

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://c.y.qq.com/soso/fcgi-bin/client_search_cp"
_SONG_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"
_PLAYLIST_URL = "https://c.y.qq.com/v8/fcg-bin/fcg_v8_playlist_cp.fcg"
_LYRICS_URL = "https://i.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg"


class QQMusicPlatform(BasePlatform):
    name = "qqmusic"
    display_name = "QQ Music"

    def __init__(self):
        self._client = httpx.AsyncClient(
            timeout=30,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://y.qq.com/",
            },
        )

    async def search(self, keyword: str, limit: int = 20) -> list[SongInfo]:
        params = {"w": keyword, "n": limit, "format": "json", "p": 1, "t": 0, "aggr": 1, "lossless": 1, "cr": 1}
        resp = await self._client.get(_SEARCH_URL, params=params)
        data = resp.json()
        songs = []
        for item in data.get("data", {}).get("song", {}).get("list", []):
            singers = item.get("singer", [])
            songs.append(SongInfo(
                title=item.get("songname", "") or item.get("name", "") or item.get("title", ""),
                artist="/".join(s.get("name", "") for s in singers),
                album=item.get("albumname", "") or (item.get("album") or {}).get("name", ""),
                duration=item.get("interval", 0),
                platform=self.name,
                song_id=item.get("songmid", "") or item.get("mid", ""),
                cover=f"https://y.qq.com/music/photo_new/T002R300x300M000{item.get('albummid', '') or (item.get('album') or {}).get('mid', '')}.jpg",
            ))
        return songs

    async def get_song_url(self, song: SongInfo) -> str | None:
        payload = {
            "req_0": {
                "module": "vkey.GetVkeyServer",
                "method": "CgiGetVkey",
                "param": {
                    "guid": "10000",
                    "songmid": [song.song_id],
                    "songtype": [0],
                    "uin": "0",
                    "loginflag": 1,
                    "platform": "20",
                },
            },
        }
        resp = await self._client.post(
            _SONG_URL,
            params={"format": "json", "data": json.dumps(payload)},
        )
        data = resp.json()
        midurlinfo = data.get("req_0", {}).get("data", {}).get("midurlinfo", [])
        if not midurlinfo:
            return None
        purl = midurlinfo[0].get("purl", "")
        if not purl:
            return None
        sip = data.get("req_0", {}).get("data", {}).get("sip", [])
        prefix = sip[0] if sip else "http://ws.stream.qqmusic.qq.com/"
        return prefix + purl

    async def get_song_detail(self, song_id: str) -> SongInfo | None:
        """获取歌曲完整元数据（含音轨号、年份）。"""
        if not song_id:
            return None
        try:
            payload = {
                "req": {
                    "module": "music.songSongGet",
                    "method": "uinner_get_song_detail",
                    "param": {"song_mid": song_id},
                },
            }
            resp = await self._client.post(
                _SONG_URL,
                params={"format": "json", "data": json.dumps(payload)},
            )
            data = resp.json()
            track = data.get("req", {}).get("data", {}).get("track_info", {})
            if not track:
                return None

            singers = track.get("singer", [])
            album = track.get("album", {})
            # year from time_public (string like "2024-01-01")
            year = 0
            time_public = track.get("time_public", "")
            if time_public and len(time_public) >= 4:
                try:
                    year = int(time_public[:4])
                except ValueError:
                    pass

            return SongInfo(
                title=track.get("title", ""),
                artist="/".join(s.get("name", "") for s in singers),
                album=album.get("name", ""),
                duration=track.get("interval", 0),
                platform=self.name,
                song_id=track.get("mid", ""),
                cover=f"https://y.qq.com/music/photo_new/T002R300x300M000{album.get('mid', '')}.jpg",
                track_number=track.get("track", 0) or 0,
                year=year,
            )
        except Exception as e:
            logger.warning(f"[QQMusic] 获取歌曲详情失败: {e}")
        return None

    async def get_lyrics(self, song_id: str) -> tuple[str, str] | None:
        """获取歌词，返回 (原文歌词, 翻译歌词)。"""
        if not song_id:
            return None
        try:
            resp = await self._client.get(
                _LYRICS_URL,
                params={"songmid": song_id, "format": "json"},
            )
            data = resp.json()
            if data.get("code") != 0:
                return None

            original = ""
            translation = ""

            lyric_b64 = data.get("lyric", "")
            if lyric_b64:
                try:
                    original = base64.b64decode(lyric_b64).decode("utf-8", errors="replace")
                except Exception:
                    pass

            trans_b64 = data.get("trans", "")
            if trans_b64:
                try:
                    translation = base64.b64decode(trans_b64).decode("utf-8", errors="replace")
                except Exception:
                    pass

            if not original:
                return None

            return (original, translation)
        except Exception as e:
            logger.warning(f"[QQMusic] 获取歌词失败: {e}")
            return None

    async def get_playlist(self, playlist_id: str) -> PlaylistInfo:
        params = {
            "id": playlist_id, "type": 1, "newsong": 1,
            "format": "json", "platform": "yqq.json",
        }
        resp = await self._client.get(_PLAYLIST_URL, params=params)
        data = resp.json()
        if data.get("code") != 0:
            raise ValueError(f"Failed to fetch playlist: {data}")
        cd = data.get("data", {}).get("cdlist", [{}])[0]
        songs = []
        for item in cd.get("songlist", []):
            singers = item.get("singer", [])
            songs.append(SongInfo(
                title=item.get("name", "") or item.get("title", ""),
                artist="/".join(s.get("name", "") for s in singers),
                album=(item.get("album") or {}).get("name", ""),
                duration=item.get("interval", 0),
                platform=self.name,
                song_id=item.get("mid", ""),
                cover=f"https://y.qq.com/music/photo_new/T002R300x300M000{(item.get('album') or {}).get('mid', '')}.jpg",
            ))
        return PlaylistInfo(
            name=cd.get("dissname", ""),
            description=cd.get("desc", "") or "",
            cover=cd.get("logo", ""),
            platform=self.name,
            song_count=cd.get("total_song_num", len(songs)),
            songs=songs,
        )

    @staticmethod
    def match_url(url: str) -> bool:
        return bool(re.search(r"y\.qq\.com", url))

    @staticmethod
    def extract_playlist_id(url: str) -> str:
        m = re.search(r"[?&]id=(\d+)", url)
        if m: return m.group(1)
        m = re.search(r"/(?:playlist|playlistDetail|taoge)/(\d+)", url)
        if m: return m.group(1)
        raise ValueError(f"Cannot extract playlist ID from URL: {url}")
