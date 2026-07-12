#!/usr/bin/env python3
"""
搜索模块测试用例
"""

import sys
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from downloadkit.searcher import search_all


class TestSearchAll:
    """音乐搜索测试"""
    
    @pytest.mark.asyncio
    async def test_search_all_empty_keyword(self):
        """空关键词搜索"""
        result = await search_all('')
        assert isinstance(result, list)
    
    @pytest.mark.asyncio
    async def test_search_all_none_keyword(self):
        """None关键词搜索"""
        # search_all(None) 可能返回空列表或抛出异常
        try:
            result = await search_all(None)
            assert isinstance(result, list)
        except (TypeError, AttributeError):
            pass  # 预期的异常
    
    @pytest.mark.asyncio
    async def test_search_all_normal_keyword(self):
        """正常关键词搜索（需要网络）"""
        # 这个测试需要网络连接，跳过
        pytest.skip("需要网络连接")
        result = await search_all('周杰伦')
        assert isinstance(result, list)
        if len(result) > 0:
            assert hasattr(result[0], 'title')
            assert hasattr(result[0], 'artist')


class TestSearcherIntegration:
    """搜索模块集成测试"""
    
    def test_searcher_import(self):
        """测试searcher模块可以正常导入"""
        from downloadkit import searcher
        assert hasattr(searcher, 'search_all')
    
    def test_match_score(self):
        """测试匹配度计算函数"""
        from downloadkit.searcher import _match_score
        
        # 完全匹配
        assert _match_score('test', 'test', 'artist') == 100
        
        # 标题包含关键词
        assert _match_score('test', 'test song', 'artist') == 80
        
        # 歌手包含关键词
        assert _match_score('test', 'song', 'test artist') == 60
        
        # 不匹配
        assert _match_score('test', 'other', 'other') == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
