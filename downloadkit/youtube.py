"""
YouTube视频解析下载模块
基于yt-dlp，支持无水印高清视频下载
支持代理和Cookie
"""

import re
import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import httpx

from .proxy import get_yt_dlp_proxy
from .utils import load_config
from .download_queue import download_queue

logger = logging.getLogger(__name__)


@dataclass
class YouTubeVideo:
    """YouTube视频信息"""
    video_id: str
    title: str
    description: str
    author: str
    cover: str
    duration: int
    url: str
    file_ext: str = "mp4"


def extract_video_id(url: str) -> Optional[str]:
    """从URL中提取视频ID"""
    patterns = [
        r'(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})',
        r'(?:shorts/)([a-zA-Z0-9_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def is_youtube_url(url: str) -> bool:
    """判断是否为YouTube链接"""
    return bool(re.search(r'(youtube\.com|youtu\.be)', url))


async def get_video_info(url: str) -> Optional[dict]:
    """
    获取YouTube视频信息（使用yt-dlp）
    
    Args:
        url: YouTube视频URL
        
    Returns:
        视频信息字典
    """
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("yt-dlp未安装，请运行: pip install yt-dlp")
    
    # 获取代理
    proxy = get_yt_dlp_proxy('youtube', load_config())
    
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
    }
    
    if proxy:
        ydl_opts['proxy'] = proxy
        logger.info(f"使用代理: {proxy}")
    
    def _extract():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)
    
    # 在线程池中运行（避免阻塞）
    loop = asyncio.get_event_loop()
    info = await loop.run_in_executor(None, _extract)
    
    return info


async def parse_youtube(url: str) -> YouTubeVideo:
    """
    解析YouTube视频
    
    Args:
        url: YouTube视频URL
        
    Returns:
        YouTubeVideo对象
    """
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError("无法提取视频ID")
    
        logger.info(f"解析视频: {video_id}")
    
    info = await get_video_info(url)
    if not info:
        raise ValueError("获取视频信息失败")
    
    title = info.get("title", "")
    description = info.get("description", "")
    author = info.get("uploader", "") or info.get("channel", "")
    cover = info.get("thumbnail", "")
    duration = info.get("duration", 0)
    
    logger.info(f"标题: {title}")
    logger.info(f"作者: {author}")
    
    return YouTubeVideo(
        video_id=video_id,
        title=title,
        description=description,
        author=author,
        cover=cover,
        duration=duration,
        url=url,
    )


async def download_youtube_video(
    video: YouTubeVideo,
    output_dir: Path,
    quality: str = "best",
    task_id: str = None,
    progress_callback=None,
    rename_strategy: str | None = None
) -> Path:
    """
    下载YouTube视频（使用yt-dlp）
    
    Args:
        video: YouTubeVideo对象
        output_dir: 输出目录
        quality: 视频质量 (best, 1080, 720, 480, 360)
        task_id: 任务ID（用于暂停/取消检测）
        progress_callback: 进度回调函数
        rename_strategy: 转发给底层下载函数（yt-dlp原生支持断点续传和自动重命名）
        
    Returns:
        下载文件路径
    """
    try:
        import yt_dlp
    except ImportError:
        raise RuntimeError("yt-dlp未安装，请运行: pip install yt-dlp")
    
    from .utils import sanitize_filename
    from .exceptions import PauseException, CancelException
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 文件名
    filename = sanitize_filename(f"youtube_{video.video_id}_{video.title}")
    output_path = output_dir / f"{filename}.mp4"
    
    # 获取代理
    proxy = get_yt_dlp_proxy('youtube', load_config())
    
    # 清晰度格式选择
    if quality == "best":
        format_str = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
    elif quality == "2160":
        format_str = 'bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/best[height<=2160][ext=mp4]'
    elif quality == "1440":
        format_str = 'bestvideo[height<=1440][ext=mp4]+bestaudio[ext=m4a]/best[height<=1440][ext=mp4]'
    elif quality == "1080":
        format_str = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]'
    elif quality == "720":
        format_str = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]'
    elif quality == "480":
        format_str = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]'
    else:
        format_str = 'best[ext=mp4]/best'
    
    # yt-dlp选项
    ydl_opts = {
        'format': format_str,
        'outtmpl': str(output_dir / f"{filename}.%(ext)s"),
        'merge_output_format': 'mp4',
        'quiet': True,
        'no_warnings': True,
        'continuedl': True,  # 启用断点续传
        'part': True,        # 保留部分文件
    }
    
    # 添加代理
    if proxy:
        ydl_opts['proxy'] = proxy
        logger.info(f"使用代理: {proxy}")
    
    # 进度钩子
    def progress_hook(d):
        if d['status'] == 'downloading':
            # 检查是否暂停
            if task_id and download_queue.is_paused(task_id):
                raise yt_dlp.utils.DownloadError("下载已暂停")
            
            # 检查是否取消
            if task_id and download_queue.is_cancelled(task_id):
                raise yt_dlp.utils.DownloadError("下载已取消")
            
            total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
            downloaded = d.get('downloaded_bytes', 0)
            if total > 0:
                progress = downloaded / total
                if progress_callback:
                    progress_callback(progress)
                if task_id:
                    download_queue.update_progress(task_id, progress, downloaded, total)
        elif d['status'] == 'finished':
            if progress_callback:
                progress_callback(1.0)
            if task_id:
                download_queue.update_progress(task_id, 1.0)
    
    ydl_opts['progress_hooks'] = [progress_hook]
    
    def _download():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video.url])
    
        logger.info("开始下载...")
    
    # 在线程池中运行
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _download)
    
    # 查找下载的文件
    for f in output_dir.glob(f"{filename}.*"):
        if f.suffix in ('.mp4', '.mkv', '.webm'):
            logger.info(f"下载完成: {f.name}")
            return f
    
    raise RuntimeError("下载失败，未找到输出文件")


async def fetch_and_download(url: str, output_dir: Path, quality: str = "best") -> Path:
    """
    一站式解析下载
    
    Args:
        url: YouTube视频URL
        output_dir: 输出目录
        quality: 视频质量
        
    Returns:
        下载文件路径
    """
    video = await parse_youtube(url)
    return await download_youtube_video(video, output_dir, quality)

