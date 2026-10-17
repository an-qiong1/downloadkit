#!/usr/bin/env python3
"""
下载模块测试用例
"""

import sys
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from downloadkit.downloader import download_song
from downloadkit.platforms.base import SongInfo


class TestDownloadSong:
    """歌曲下载测试"""
    
    def test_song_info_creation(self):
        """测试SongInfo数据结构"""
        song = SongInfo(
            title="测试歌曲",
            artist="测试歌手",
            platform="netease",
            song_id="12345"
        )
        assert song.title == "测试歌曲"
        assert song.artist == "测试歌手"
        assert song.platform == "netease"
        assert song.song_id == "12345"
    
    @pytest.mark.asyncio
    async def test_download_song_cancelled(self):
        """测试下载取消"""
        song = SongInfo(title="test", artist="test", platform="test", song_id="1")
        
        with patch('downloadkit.downloader.download_queue') as mock_queue:
            mock_queue.is_cancelled.return_value = True
            
            with pytest.raises(Exception):
                await download_song(song, task_id="test-task")
    
    @pytest.mark.asyncio
    async def test_download_song_paused_then_cancelled(self):
        """测试下载暂停后取消"""
        song = SongInfo(title="test", artist="test", platform="test", song_id="1")
        
        with patch('downloadkit.downloader.download_queue') as mock_queue:
            # 第一次检查暂停，第二次检查取消
            mock_queue.is_paused.side_effect = [True, False]
            mock_queue.is_cancelled.side_effect = [False, True]
            
            with pytest.raises(Exception):
                await download_song(song, task_id="test-task")


class TestDownloaderIntegration:
    """下载模块集成测试"""
    
    def test_downloader_import(self):
        """测试downloader模块可以正常导入"""
        from downloadkit import downloader
        assert hasattr(downloader, 'download_song')
    
    def test_downloader_has_required_functions(self):
        """测试downloader模块包含必要的函数"""
        from downloadkit import downloader
        assert callable(downloader.download_song)


class TestEmptyArtifactCleanup:
    """取消/失败后清理 0 字节产物空壳（2026-10-17 打包版实测回归）

    _stream_download 先 open(wb) 创建文件再流式写入；若在写出第一个
    字节前被取消或失败，磁盘上留下一个 0 字节 .mp3 —— 文件列表里显示成
    一首能看见、播不了的假歌。空壳对续传也无价值（续传看已有字节数，
    0 即从头下），download_song 失败/取消时必须清掉；非 0 的半截文件
    必须保留（那是同源续传的依据）。
    """

    def test_drop_empty_artifact_removes_zero_byte(self, tmp_path):
        from downloadkit.downloader import _drop_empty_artifact
        f = tmp_path / "歌 - 歌手.mp3"
        f.write_bytes(b"")  # 0 字节空壳
        _drop_empty_artifact(f)
        assert not f.exists(), "0 字节空壳没被清掉 → 文件列表会显示假歌"

    def test_drop_empty_artifact_keeps_partial(self, tmp_path):
        """非 0 半截文件必须保留（续传依据）"""
        from downloadkit.downloader import _drop_empty_artifact
        f = tmp_path / "歌 - 歌手.mp3"
        f.write_bytes(b"ID3xxx")  # 已有字节
        _drop_empty_artifact(f)
        assert f.exists(), "误删了半截文件 → 断点续传失效"
        assert f.stat().st_size == 6

    def test_drop_empty_artifact_missing_is_noop(self, tmp_path):
        from downloadkit.downloader import _drop_empty_artifact
        _drop_empty_artifact(tmp_path / "不存在.mp3")  # 不该抛

    @pytest.mark.asyncio
    async def test_download_song_all_fail_cleans_empty(self, tmp_path):
        """整条链都失败 → 不留空壳，且 download_song 返回 None"""
        from downloadkit.downloader import download_song
        from downloadkit.platforms.base import SongInfo
        song = SongInfo(title="不存在歌", artist="不存在人",
                        platform="soda", song_id="")

        # 全链失败：_get_download_url 返 None，各级 search 都抛，产物不落
        async def _boom(*a, **k):
            raise RuntimeError("无源")
        with patch('downloadkit.downloader._get_download_url',
                   new=AsyncMock(return_value=None)), \
             patch('downloadkit.downloader.itzo_search', new=_boom), \
             patch('downloadkit.downloader.gequbao_search', new=_boom), \
             patch('downloadkit.downloader.migu_search', new=_boom), \
             patch('downloadkit.downloader.kuwo_search', new=_boom), \
             patch('downloadkit.downloader.kugou_search', new=_boom), \
             patch('downloadkit.downloader.soda_search', new=_boom), \
             patch('downloadkit.downloader._download_via_ytdlp', new=_boom):
            r = await download_song(song, output_dir=str(tmp_path))

        assert r is None
        # 关键：失败后不许留下 0 字节空壳
        leftover = list(tmp_path.glob("*.mp3"))
        assert leftover == [], f"失败仍留产物: {[p.name for p in leftover]}"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
