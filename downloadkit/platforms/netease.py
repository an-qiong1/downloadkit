"""网易云音乐 -- 搜索用 API，下载用外链重定向。"""

import re, httpx, logging
from .base import BasePlatform, SongInfo, PlaylistInfo

logger = logging.getLogger(__name__)

OUTER_URL = "https://music.163.com/song/media/outer/url"
SEARCH_URL = "https://music.163.com/api/search/get"
# v6 API 需要登录凭证，使用旧版 API
PLAYLIST_URL = "https://music.163.com/api/playlist/detail"
SONG_DETAIL_URL = "https://music.163.com/api/song/detail"

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
            # 访问首页获取基础cookie
            resp = await self._client.get("https://music.163.com/")
            # 设置必要的cookie
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
        if data.get("code") != 200: return []
        songs = []
        for item in data.get("result", {}).get("songs", [])[:limit]:
            ar = item.get("ar", [{}]); al = item.get("al", {})
            songs.append(SongInfo(
                title=item.get("name", ""),
                artist="/".join(a.get("name", "") for a in ar if a.get("name")),
                album=al.get("name", "") if isinstance(al, dict) else "",
                duration=item.get("dt", 0) // 1000, platform=self.name,
                song_id=str(item.get("id", "")),
                cover=al.get("picUrl", "") if isinstance(al, dict) else "",
            ))
        return songs

    async def get_song_url(self, song: SongInfo) -> str | None:
        """Use the public outer URL which redirects to CDN."""
        return f"{OUTER_URL}?id={song.song_id}.mp3"

    async def get_song_info(self, song_id: str) -> SongInfo | None:
        """获取单曲详情"""
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
                    s = songs_data[0]
                    ar = s.get("ar", [{}])
                    al = s.get("al", {})
                    return SongInfo(
                        title=s.get("name", ""),
                        artist="/".join(a.get("name", "") for a in ar if a.get("name")),
                        album=al.get("name", "") if isinstance(al, dict) else "",
                        duration=s.get("dt", 0) // 1000,
                        platform=self.name,
                        song_id=str(s.get("id", "")),
                        cover=al.get("picUrl", "") if isinstance(al, dict) else "",
                    )
        except Exception as e:
            logger.warning(f"获取歌曲详情失败: {e}")
        return None

    async def get_playlist(self, playlist_id: str) -> PlaylistInfo:
        """获取歌单详情，使用旧版API（不需要登录）"""
        await self._ensure_session()
        
        # 使用旧版 API（不需要登录凭证）
        try:
            resp = await self._client.get(PLAYLIST_URL, params={"id": playlist_id})
            data = resp.json()
            
            logger.info(f"歌单API响应: code={data.get('code')}, keys={list(data.keys())[:5]}")
            
            if data.get("code") != 200:
                raise ValueError(f"API返回错误: {data.get('message', data.get('code'))}")
            
            # 旧版API使用 result 字段
            pl = data.get("result", {})
            if not pl:
                # 尝试新版格式
                pl = data.get("playlist", {})
            
            if not pl:
                raise ValueError("歌单数据为空")
            
            songs = []
            tracks = pl.get("tracks", [])
            
            # 如果 tracks 为空但有 trackIds，尝试批量获取歌曲详情
            if not tracks and pl.get("trackIds"):
                track_ids = pl.get("trackIds", [])
                logger.info(f"tracks为空，尝试从 {len(track_ids)} 个trackIds获取歌曲详情")
                
                # 分批获取（每批最多1000个）
                batch_size = 1000
                for i in range(0, len(track_ids), batch_size):
                    batch = track_ids[i:i+batch_size]
                    ids_str = ",".join(str(t.get("id", t) if isinstance(t, dict) else t) for t in batch)
                    try:
                        detail_resp = await self._client.get(
                            SONG_DETAIL_URL,
                            params={"ids": f"[{ids_str}]"}
                        )
                        detail_data = detail_resp.json()
                        if detail_data.get("code") == 200:
                            for s in detail_data.get("songs", []):
                                ar = s.get("ar", [{}])
                                al = s.get("al", {})
                                songs.append(SongInfo(
                                    title=s.get("name", ""),
                                    artist="/".join(a.get("name", "") for a in ar if a.get("name")),
                                    album=al.get("name", ""),
                                    duration=s.get("dt", 0) // 1000,
                                    platform=self.name,
                                    song_id=str(s.get("id", "")),
                                    cover=al.get("picUrl", ""),
                                ))
                    except Exception as e:
                        logger.warning(f"批量获取歌曲详情失败: {e}")
                        continue
            else:
                # 直接从 tracks 解析
                for track in tracks:
                    ar = track.get("ar", [{}]); al = track.get("al", {})
                    songs.append(SongInfo(
                        title=track.get("name", ""),
                        artist="/".join(a.get("name", "") for a in ar if a.get("name")),
                        album=al.get("name", ""),
                        duration=track.get("dt", 0) // 1000,
                        platform=self.name,
                        song_id=str(track.get("id", "")),
                        cover=al.get("picUrl", ""),
                    ))
            
            return PlaylistInfo(
                name=pl.get("name", ""),
                description=pl.get("description", "") or "",
                cover=pl.get("coverImgUrl", "") or pl.get("coverImgUrl", ""),
                platform=self.name,
                song_count=pl.get("trackCount", len(songs)),
                songs=songs
            )
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"歌单解析异常: {e}")
            raise ValueError(f"歌单解析失败: {str(e)}")

    @staticmethod
    def match_url(url: str) -> bool:
        return bool(re.search(r"music\.163\.com", url))

    @staticmethod
    def extract_playlist_id(url: str) -> str:
        # 排除单曲链接格式
        if '/song' in url and '/song' in url.split('?')[0]:
            raise ValueError("This is a single song URL, not a playlist URL")
        
        # 匹配歌单ID
        m = re.search(r"[?&]id=(\d+)", url)
        if m: return m.group(1)
        m = re.search(r"/playlist/(\d+)", url)
        if m: return m.group(1)
        raise ValueError(f"Cannot extract playlist ID: {url}")
