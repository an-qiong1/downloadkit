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
