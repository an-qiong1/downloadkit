#!/usr/bin/env python3
"""
歌单解析模块测试用例
"""

import sys
import pytest
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from downloadkit.playlist import parse_playlist


class TestParsePlaylist:
    """歌单解析测试"""
    
    @pytest.mark.asyncio
    async def test_parse_playlist_invalid_url(self):
        """无效URL解析"""
        with pytest.raises(ValueError, match="不支持的歌单链接格式"):
            await parse_playlist('https://example.com/playlist')
    
    @pytest.mark.asyncio
    async def test_parse_playlist_empty_url(self):
        """空URL解析"""
        with pytest.raises(ValueError):
            await parse_playlist('')
    
    @pytest.mark.asyncio
    async def test_parse_playlist_none_url(self):
        """None URL解析"""
        with pytest.raises((ValueError, TypeError)):
            await parse_playlist(None)
    
    @pytest.mark.asyncio
    async def test_parse_playlist_netease_format(self):
        """网易云歌单链接格式检测"""
        # 这个测试需要网络连接，跳过
        pytest.skip("需要网络连接")
        result = await parse_playlist('https://music.163.com/playlist?id=2884035')
        assert result is not None
        assert hasattr(result, 'name')
        assert hasattr(result, 'songs')
    
    @pytest.mark.asyncio
    async def test_parse_playlist_qq_format(self):
        """QQ音乐歌单链接格式检测"""
        # 这个测试需要网络连接，跳过
        pytest.skip("需要网络连接")
        result = await parse_playlist('https://y.qq.com/n/ryqq/playlist/xxx')
        assert result is not None


class TestSodaPlaylistDuration:
    """P0-2 前置：汽水歌单解析必须把 duration_ms 换算进 SongInfo.duration

    试听片段拦截（downloader._looks_like_preview）拿它做期望时长；
    此前 _parse_soda_playlist 建 SongInfo 时把 duration_ms 丢掉了，
    链上收到的永远是 0（=时长未知），比例判据形同虚设。
    """

    @pytest.mark.asyncio
    async def test_duration_ms_converted_to_seconds(self, monkeypatch):
        from downloadkit import playlist

        async def _fake_soda_parse(url):
            return {
                "name": "测试歌单",
                "songs": [
                    {"track_id": "1", "name": "晴天", "artist": "周杰伦",
                     "album": "", "duration_ms": 269000},
                    {"track_id": "2", "name": "稻香", "artist": "周杰伦",
                     "album": "", "duration_ms": 223500},
                    # 无时长字段 → 0（未知），拦截只走绝对阈值
                    {"track_id": "3", "name": "无时长", "artist": "某人",
                     "album": ""},
                ],
                "song_count": 3,
            }

        monkeypatch.setattr(playlist, "soda_parse_playlist", _fake_soda_parse)
        info = await playlist._parse_soda_playlist(
            "https://qishui.douyin.com/s/xxx")

        assert [s.duration for s in info.songs] == [269, 223, 0], \
            "duration_ms 没换算成秒传进 SongInfo——试听拦截拿不到期望时长"

    @pytest.mark.asyncio
    async def test_duration_reaches_stream_download(self, monkeypatch):
        """download_song 链上各级 _stream_download 收到 song.duration"""
        from downloadkit import downloader
        from downloadkit.platforms.base import SongInfo

        seen = []

        async def _capture_stream(url, filepath, task_id=None, duration_sec=0):
            seen.append(duration_sec)
            return False  # 本级失败，链继续 —— 重点是每级都拿到时长

        async def _no_extra(*a, **k):
            return None

        async def _mk_url():
            return "https://example.com/direct.mp3"

        monkeypatch.setattr(downloader, "_stream_download", _capture_stream)
        # Step 1 给直链；Step 2-7 全 mock 掉不发网络；Step 8 ytdlp 返 None
        monkeypatch.setattr(downloader, "_get_download_url",
                            lambda song: _mk_url())
        for name in ("itzo_search", "gequbao_search", "migu_search",
                     "kuwo_search", "kugou_search", "soda_search"):
            monkeypatch.setattr(downloader, name, _no_extra)
        monkeypatch.setattr(downloader, "_download_via_ytdlp", _no_extra)

        import tempfile
        song = SongInfo(title="歌", artist="手", platform="soda",
                        song_id="1", duration=269)
        with tempfile.TemporaryDirectory() as td:
            r = await downloader.download_song(song, output_dir=td)
        assert r is None
        assert seen and all(d == 269 for d in seen), \
            f"链上 _stream_download 没收到 song.duration: {seen}"


class TestPlaylistIntegration:
    """歌单模块集成测试"""
    
    def test_playlist_import(self):
        """测试playlist模块可以正常导入"""
        from downloadkit import playlist
        assert hasattr(playlist, 'parse_playlist')
    
    def test_playlist_info_structure(self):
        """测试PlaylistInfo数据结构"""
        from downloadkit.platforms.base import PlaylistInfo
        
        # 创建一个PlaylistInfo实例
        info = PlaylistInfo(name="测试歌单", songs=[])
        assert info.name == "测试歌单"
        assert info.songs == []
        assert isinstance(info.songs, list)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
