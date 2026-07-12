"""
安全文件路径管理模块

防止路径遍历攻击（Path Traversal），确保所有文件操作限制在下载目录内。
"""

from pathlib import Path, PurePosixPath
from typing import Optional
from urllib.parse import unquote
from fastapi import HTTPException


class PathTraversalError(HTTPException):
    """路径遍历攻击尝试"""
    def __init__(self, detail: str = "路径遍历攻击被拒绝"):
        super().__init__(status_code=403, detail=detail)


class FileOutsideBaseError(HTTPException):
    """文件不在基础目录内"""
    def __init__(self, detail: str = "文件路径超出允许范围"):
        super().__init__(status_code=403, detail=detail)


def normalize_path(file_path: str) -> str:
    """
    标准化路径字符串，移除危险字符序列
    
    Args:
        file_path: 原始路径字符串
        
    Returns:
        标准化后的路径字符串
    """
    # 移除空字节（防止 null byte 注入）
    file_path = file_path.replace('\x00', '')
    
    # 使用 PurePosixPath 处理正斜杠，统一处理
    # 然后转换回字符串
    normalized = PurePosixPath(file_path).as_posix()
    
    # 移除开头的斜杠（防止绝对路径）
    while normalized.startswith('/'):
        normalized = normalized[1:]
    
    return normalized


def has_traversal_pattern(file_path: str) -> bool:
    """
    检测路径遍历模式
    
    Args:
        file_path: 路径字符串
        
    Returns:
        如果检测到遍历模式返回 True
    """
    # 1. URL 解码
    decoded = unquote(file_path)
    
    # 2. 移除空字节（防止 null byte 注入绕过）
    cleaned = decoded.replace('\x00', '')
    
    # 3. 统一斜杠
    normalized = cleaned.replace("\\", "/")
    
    # 4. 按路径段判断
    # 移除空段和当前目录标记
    parts = [p for p in normalized.split("/") if p not in ("", ".")]
    
    # 如果任何段是完整的 ".."，则为遍历
    if any(part == ".." for part in parts):
        return True
    
    # 5. 检测编码的遍历模式（双重编码等）
    lower_path = file_path.lower()
    encoded_patterns = [
        '%2e%2e',  # URL 编码的 ..
        '..%2f',   # 混合编码
        '%2e%2e/', # 混合编码
        '%2e%2e%2f', # 全编码
        '..%5c',   # 编码反斜杠
        '%2e%2e%5c', # 全编码反斜杠
    ]
    
    for pattern in encoded_patterns:
        if pattern in lower_path:
            return True
    
    return False


def safe_download_path(
    file_path: str,
    download_dir: Path,
    allow_subdirs: bool = True,
    check_exists: bool = False
) -> Path:
    """
    安全地解析下载目录内的文件路径
    
    Args:
        file_path: 用户提供的相对路径
        download_dir: 下载根目录（必须是绝对路径）
        allow_subdirs: 是否允许访问子目录
        check_exists: 是否检查文件是否存在
        
    Returns:
        安全的绝对路径
        
    Raises:
        PathTraversalError: 检测到路径遍历攻击
        FileOutsideBaseError: 路径超出下载目录范围
        HTTPException: 文件不存在（如果 check_exists=True）
    """
    # 1. 检测路径遍历模式
    if has_traversal_pattern(file_path):
        raise PathTraversalError(f"检测到路径遍历尝试: {file_path}")
    
    # 2. 标准化路径
    normalized = normalize_path(file_path)
    
    # 如果不允许子目录，移除所有目录部分
    if not allow_subdirs:
        normalized = Path(normalized).name
    
    # 3. 解析完整路径
    try:
        full_path = (download_dir / normalized).resolve()
    except (ValueError, OSError) as e:
        raise PathTraversalError(f"路径解析失败: {file_path}")
    
    # 4. 验证路径在下载目录内
    try:
        # Python 3.9+ 可以使用 is_relative_to
        full_path.relative_to(download_dir.resolve())
    except ValueError:
        raise FileOutsideBaseError(
            f"路径 {file_path} 解析后超出下载目录范围"
        )
    
    # 5. 可选：检查文件是否存在
    if check_exists and not full_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    
    return full_path


def safe_delete_path(
    file_path: str,
    download_dir: Path
) -> Path:
    """
    安全地获取要删除的文件路径
    
    Args:
        file_path: 用户提供的相对路径
        download_dir: 下载根目录
        
    Returns:
        安全的绝对路径
    """
    return safe_download_path(
        file_path,
        download_dir,
        allow_subdirs=True,
        check_exists=True
    )


def list_directory_safe(
    dir_path: Optional[str],
    download_dir: Path
) -> Path:
    """
    安全地获取目录路径用于列出内容
    
    Args:
        dir_path: 相对目录路径，None 表示根目录
        download_dir: 下载根目录
        
    Returns:
        安全的目录绝对路径
    """
    if dir_path is None or dir_path == '':
        return download_dir.resolve()
    
    return safe_download_path(
        dir_path,
        download_dir,
        allow_subdirs=True,
        check_exists=True
    )


def get_media_type(file_path: Path) -> str:
    """
    根据文件扩展名获取媒体类型
    
    Args:
        file_path: 文件路径
        
    Returns:
        MIME 类型字符串
    """
    ext = file_path.suffix.lower()
    
    media_map = {
        # 视频
        '.mp4': 'video/mp4',
        '.webm': 'video/webm',
        '.avi': 'video/x-msvideo',
        '.mkv': 'video/x-matroska',
        '.mov': 'video/quicktime',
        '.flv': 'video/x-flv',
        '.wmv': 'video/x-ms-wmv',
        
        # 图片
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.png': 'image/png',
        '.webp': 'image/webp',
        '.gif': 'image/gif',
        '.bmp': 'image/bmp',
        '.svg': 'image/svg+xml',
        
        # 音频
        '.mp3': 'audio/mpeg',
        '.m4a': 'audio/mp4',
        '.flac': 'audio/flac',
        '.wav': 'audio/wav',
        '.ogg': 'audio/ogg',
        '.aac': 'audio/aac',
    }
    
    return media_map.get(ext, 'application/octet-stream')
