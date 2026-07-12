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


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
