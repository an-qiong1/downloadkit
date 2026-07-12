#!/usr/bin/env python3
"""
边界条件测试用例
"""

import sys
import pytest
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from downloadkit.file_manager import (
    safe_download_path,
    safe_delete_path,
    has_traversal_pattern,
    normalize_path,
    get_media_type,
    PathTraversalError,
    FileOutsideBaseError
)
from fastapi import HTTPException


class TestPathTraversal:
    """路径遍历检测测试"""
    
    def test_basic_traversal(self):
        """基本路径遍历"""
        assert has_traversal_pattern('../test') == True
        assert has_traversal_pattern('..\\test') == True
        assert has_traversal_pattern('../../test') == True
    
    def test_encoded_traversal(self):
        """编码路径遍历"""
        assert has_traversal_pattern('%2e%2e/test') == True
        assert has_traversal_pattern('..%2f/test') == True
        assert has_traversal_pattern('%2e%2e%2ftest') == True
    
    def test_mixed_traversal(self):
        """混合编码遍历"""
        assert has_traversal_pattern('..%2f..%2f') == True
        assert has_traversal_pattern('%2e%2e/..') == True
    
    def test_no_traversal(self):
        """正常路径"""
        assert has_traversal_pattern('test.txt') == False
        assert has_traversal_pattern('videos/test.mp4') == False
        assert has_traversal_pattern('dir/subdir/file.txt') == False
    
    def test_path_segment_traversal(self):
        """路径段遍历"""
        # 完整的 ".." 段应该被检测
        assert has_traversal_pattern('videos/../../server.py') == True
        assert has_traversal_pattern('videos/%2e%2e/%2e%2e/server.py') == True
    
    def test_null_byte_traversal(self):
        """空字节遍历"""
        assert has_traversal_pattern('..%00/test.txt') == True
        assert has_traversal_pattern('%00../../etc/passwd') == True
    
    def test_encoded_backslash(self):
        """编码反斜杠"""
        assert has_traversal_pattern('..%5c/test.txt') == True
        assert has_traversal_pattern('%2e%2e%5c/test.txt') == True
    
    def test_empty_path(self):
        """空路径"""
        assert has_traversal_pattern('') == False
    
    def test_dot_only(self):
        """单点号"""
        assert has_traversal_pattern('.') == False
        assert has_traversal_pattern('./test') == False
    
    def test_multiple_dots(self):
        """多点号"""
        # 连续点号但不是完整的 ".." 段，应该允许
        assert has_traversal_pattern('...') == False
        assert has_traversal_pattern('....') == False
        
        # 包含连续点号的文件名，应该允许
        assert has_traversal_pattern('歌名..现场版.mp3') == False
        assert has_traversal_pattern('photo...backup.jpg') == False
        assert has_traversal_pattern('videos/第1集..修复版.mp4') == False


class TestPathNormalization:
    """路径标准化测试"""
    
    def test_remove_leading_slash(self):
        """移除前导斜杠"""
        assert normalize_path('/test.txt') == 'test.txt'
        assert normalize_path('//test.txt') == 'test.txt'
        assert normalize_path('///test.txt') == 'test.txt'
    
    def test_remove_dotslash(self):
        """移除当前目录标记"""
        assert normalize_path('./test.txt') == 'test.txt'
        assert normalize_path('.//test.txt') == 'test.txt'
    
    def test_preserve_subdirs(self):
        """保留子目录"""
        assert normalize_path('videos/test.mp4') == 'videos/test.mp4'
        assert normalize_path('dir/subdir/file.txt') == 'dir/subdir/file.txt'
    
    def test_null_byte(self):
        """空字节处理"""
        assert normalize_path('test\x00.txt') == 'test.txt'
        assert normalize_path('\x00test.txt') == 'test.txt'
    
    def test_backslash(self):
        """反斜杠处理"""
        # PurePosixPath 会保留反斜杠
        result = normalize_path('dir\\file.txt')
        assert 'file.txt' in result


class TestSafeDownloadPath:
    """安全路径解析测试"""
    
    @pytest.fixture
    def download_dir(self, tmp_path):
        """创建临时下载目录"""
        # 创建测试文件
        (tmp_path / 'test.txt').write_text('test content')
        (tmp_path / 'videos').mkdir()
        (tmp_path / 'videos' / 'video.mp4').write_text('video content')
        (tmp_path / 'images').mkdir()
        (tmp_path / 'images' / 'photo.jpg').write_text('photo content')
        return tmp_path
    
    def test_valid_file(self, download_dir):
        """有效文件路径"""
        result = safe_download_path('test.txt', download_dir, check_exists=True)
        assert result == (download_dir / 'test.txt').resolve()
    
    def test_valid_subdir(self, download_dir):
        """有效子目录路径"""
        result = safe_download_path('videos/video.mp4', download_dir, check_exists=True)
        assert result == (download_dir / 'videos' / 'video.mp4').resolve()
    
    def test_traversal_attack(self, download_dir):
        """路径遍历攻击"""
        with pytest.raises(PathTraversalError):
            safe_download_path('../README.md', download_dir)
    
    def test_double_traversal(self, download_dir):
        """双重路径遍历"""
        with pytest.raises(PathTraversalError):
            safe_download_path('../../etc/passwd', download_dir)
    
    def test_encoded_traversal(self, download_dir):
        """编码路径遍历"""
        with pytest.raises(PathTraversalError):
            safe_download_path('%2e%2e/README.md', download_dir)
    
    def test_nonexistent_file(self, download_dir):
        """不存在的文件"""
        with pytest.raises(HTTPException) as exc_info:
            safe_download_path('nonexistent.txt', download_dir, check_exists=True)
        assert exc_info.value.status_code == 404
    
    def test_no_check_exists(self, download_dir):
        """不检查存在性"""
        # 应该成功，即使文件不存在
        result = safe_download_path('nonexistent.txt', download_dir, check_exists=False)
        assert result.name == 'nonexistent.txt'
    
    def test_no_subdirs(self, download_dir):
        """禁止子目录"""
        # 只允许根目录文件
        result = safe_download_path('test.txt', download_dir, allow_subdirs=False)
        assert result.name == 'test.txt'
        
        # 子目录文件会被剥离目录部分，只保留文件名
        # videos/video.mp4 -> video.mp4
        result = safe_download_path('videos/video.mp4', download_dir, allow_subdirs=False, check_exists=False)
        assert result.name == 'video.mp4'
        # 验证路径在下载目录内
        assert result.parent == download_dir.resolve()


class TestSafeDeletePath:
    """安全删除路径测试"""
    
    @pytest.fixture
    def download_dir(self, tmp_path):
        """创建临时下载目录"""
        (tmp_path / 'delete_me.txt').write_text('delete content')
        return tmp_path
    
    def test_valid_delete(self, download_dir):
        """有效删除路径"""
        result = safe_delete_path('delete_me.txt', download_dir)
        assert result.exists()
    
    def test_traversal_delete(self, download_dir):
        """路径遍历删除"""
        with pytest.raises(PathTraversalError):
            safe_delete_path('../README.md', download_dir)
    
    def test_nonexistent_delete(self, download_dir):
        """删除不存在的文件"""
        with pytest.raises(HTTPException) as exc_info:
            safe_delete_path('nonexistent.txt', download_dir)
        assert exc_info.value.status_code == 404


class TestMediaType:
    """媒体类型测试"""
    
    def test_video_types(self):
        """视频类型"""
        assert get_media_type(Path('test.mp4')) == 'video/mp4'
        assert get_media_type(Path('test.webm')) == 'video/webm'
        assert get_media_type(Path('test.avi')) == 'video/x-msvideo'
        assert get_media_type(Path('test.mkv')) == 'video/x-matroska'
    
    def test_image_types(self):
        """图片类型"""
        assert get_media_type(Path('test.jpg')) == 'image/jpeg'
        assert get_media_type(Path('test.jpeg')) == 'image/jpeg'
        assert get_media_type(Path('test.png')) == 'image/png'
        assert get_media_type(Path('test.webp')) == 'image/webp'
        assert get_media_type(Path('test.gif')) == 'image/gif'
    
    def test_audio_types(self):
        """音频类型"""
        assert get_media_type(Path('test.mp3')) == 'audio/mpeg'
        assert get_media_type(Path('test.m4a')) == 'audio/mp4'
        assert get_media_type(Path('test.flac')) == 'audio/flac'
        assert get_media_type(Path('test.wav')) == 'audio/wav'
    
    def test_unknown_type(self):
        """未知类型"""
        assert get_media_type(Path('test.xyz')) == 'application/octet-stream'
        assert get_media_type(Path('test')) == 'application/octet-stream'
    
    def test_case_insensitive(self):
        """大小写不敏感"""
        assert get_media_type(Path('test.MP4')) == 'video/mp4'
        assert get_media_type(Path('test.JPG')) == 'image/jpeg'
        assert get_media_type(Path('test.MP3')) == 'audio/mpeg'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
