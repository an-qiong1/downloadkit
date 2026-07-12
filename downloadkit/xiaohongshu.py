"""
小红书内容解析下载模块
支持无水印图片和视频下载
"""

import re
import json
import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List

import httpx

from .utils import download_file, sanitize_filename, get_download_subdir

logger = logging.getLogger(__name__)


class ContentType(Enum):
    """内容类型"""
    VIDEO = "video"
    IMAGE = "image"


@dataclass
class XhsContent:
    """小红书内容信息"""
    note_id: str
    content_type: ContentType
    title: str
    desc: str
    author: str
    cover: str
    video_url: Optional[str] = None
    images: List[str] = field(default_factory=list)
    file_ext: str = "mp4"


# 请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def extract_note_id(url: str) -> Optional[str]:
    """从URL中提取笔记ID"""
    patterns = [
        r'xiaohongshu\.com/(?:explore/|discovery/item/)([a-f0-9]+)',
        r'xhslink\.com/\w+',
        r'xiaohongshu\.com/user/profile/\w+',
    ]
    
    # 处理短链接
    if 'xhslink.com' in url:
        # 需要跟随重定向获取真实URL
        return None  # 需要异步处理
    
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1) if match.lastindex else None
    
    return None


def is_xiaohongshu_url(url: str) -> bool:
    """判断是否为小红书链接"""
    return bool(re.search(r'(xiaohongshu\.com|xhslink\.com)', url))


def remove_watermark(url: str) -> str:
    """
    去除图片URL中的水印参数
    
    Args:
        url: 原始图片URL
        
    Returns:
        去除水印后的URL
    """
    # 移除imageView2参数
    url = re.sub(r'\?imageView2.*$', '', url)
    # 移除!后缀
    url = re.sub(r'![^!]*$', '', url)
    # 移除?后缀
    url = re.sub(r'\?[^?]*$', '', url)
    return url


async def resolve_short_url(url: str) -> str:
    """
    解析短链接，获取真实URL
    
    Args:
        url: 短链接
        
    Returns:
        真实URL
    """
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code in (301, 302, 303, 307, 308):
            return resp.headers.get("location", url)
    return url


async def fetch_page(url: str) -> str:
    """
    获取页面HTML
    
    Args:
        url: 页面URL
        
    Returns:
        HTML内容
    """
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=HEADERS) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text


def parse_initial_state(html: str) -> Optional[dict]:
    """
    从HTML中提取__INITIAL_STATE__数据
    
    Args:
        html: HTML内容
        
    Returns:
        解析后的数据
    """
    # 尝试多种模式
    patterns = [
        r'window\.__INITIAL_STATE__\s*=\s*({.+?})\s*</script>',
        r'window\.__INITIAL_STATE__\s*=\s*({.+?})\s*;\s*\(function',
        r'__INITIAL_STATE__\s*=\s*({.+?})\s*</script>',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, html, re.DOTALL)
        if match:
            try:
                json_str = match.group(1)
                # 处理undefined
                json_str = re.sub(r':\s*undefined', ': null', json_str)
                return json.loads(json_str)
            except json.JSONDecodeError:
                continue
    
    return None


async def parse_xiaohongshu(url: str) -> XhsContent:
    """
    解析小红书内容
    
    Args:
        url: 小红书URL
        
    Returns:
        XhsContent对象
    """
    # 处理短链接
    if 'xhslink.com' in url:
        url = await resolve_short_url(url)
    
    # 提取笔记ID
    note_id = extract_note_id(url)
    if not note_id:
        # 尝试从URL中提取
        match = re.search(r'/([a-f0-9]{24})', url)
        if match:
            note_id = match.group(1)
        else:
            raise ValueError("无法提取笔记ID")
    
        logger.info(f"解析笔记: {note_id}")
    
    # 构造完整URL
    if not url.startswith('http'):
        url = f"https://www.xiaohongshu.com/explore/{note_id}"
    
    # 获取页面HTML
    html = await fetch_page(url)
    
    # 提取数据
    data = parse_initial_state(html)
    if not data:
        raise ValueError("无法提取页面数据")
    
    # 查找笔记数据
    note_data = None
    
    # 尝试从note.noteDetailMap获取
    note_map = data.get("note", {}).get("noteDetailMap", {})
    if note_map:
        note_id_key = list(note_map.keys())[0]
        note_data = note_map[note_id_key].get("note", {})
    
    # 尝试从note.note获取
    if not note_data:
        note_data = data.get("note", {}).get("note", {})
    
    if not note_data:
        raise ValueError("无法获取笔记数据")
    
    # 提取基本信息
    title = note_data.get("title", "")
    desc = note_data.get("desc", "")
    author = note_data.get("user", {}).get("nickname", "")
    cover = note_data.get("cover", {}).get("url", "")
    
    # 判断内容类型
    note_type = note_data.get("type", "")
    
    if note_type == "video" or note_data.get("video"):
        # 视频类型
        content_type = ContentType.VIDEO
        
        # 提取视频URL
        video_data = note_data.get("video", {})
        media_data = video_data.get("media", {})
        stream_data = media_data.get("stream", {})
        
        # 尝试获取h264编码的视频
        h264_streams = stream_data.get("h264", [])
        if h264_streams:
            video_url = h264_streams[0].get("masterUrl", "")
        else:
            # 尝试其他编码
            for codec in ["h265", "av1"]:
                streams = stream_data.get(codec, [])
                if streams:
                    video_url = streams[0].get("masterUrl", "")
                    break
            else:
                video_url = ""
        
        return XhsContent(
            note_id=note_id,
            content_type=content_type,
            title=title,
            desc=desc,
            author=author,
            cover=cover,
            video_url=video_url,
        )
    
    else:
        # 图文类型
        content_type = ContentType.IMAGE
        
        # 提取图片列表
        image_list = note_data.get("imageList", [])
        images = []
        
        for img in image_list:
            img_url = img.get("urlDefault", "") or img.get("url", "")
            if img_url:
                # 去除水印
                img_url = remove_watermark(img_url)
                images.append(img_url)
        
        return XhsContent(
            note_id=note_id,
            content_type=content_type,
            title=title,
            desc=desc,
            author=author,
            cover=cover,
            images=images,
        )


async def download_xhs_content(
    content: XhsContent,
    output_dir: Path,
    task_id: str = None,
    progress_callback=None,
    rename_strategy: str | None = None
) -> List[Path]:
    """
    下载小红书内容
    
    Args:
        content: XhsContent对象
        output_dir: 输出目录
        task_id: 任务ID（用于暂停/取消检测）
        progress_callback: 进度回调函数
        rename_strategy: 文件重名策略 (skip/overwrite/rename)，None则从配置读取
        
    Returns:
        下载文件路径列表
    """
    from .exceptions import PauseException, CancelException
    
    downloaded = []
    
    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Referer": "https://www.xiaohongshu.com/",
    }
    
    async with httpx.AsyncClient(timeout=120, headers=headers) as client:
        if content.content_type == ContentType.VIDEO and content.video_url:
            # 下载视频
            video_dir = get_download_subdir("videos")
            filename = sanitize_filename(f"xhs_{content.note_id}_{content.title}")
            filepath = video_dir / f"{filename}.mp4"
            
            logger.info("下载视频...")
            await download_file(client, content.video_url, filepath, task_id, progress_callback, rename_strategy=rename_strategy)
            downloaded.append(filepath)
            logger.info(f"下载完成: {filepath.name}")
        
        elif content.content_type == ContentType.IMAGE and content.images:
            # 下载图片
            images_dir = get_download_subdir("images")
            filename_base = sanitize_filename(f"xhs_{content.note_id}_{content.title}")
            
            for idx, img_url in enumerate(content.images):
                # 检查是否暂停/取消
                from .utils import check_download_status
                check_download_status(task_id)
                
                filename = f"{filename_base}_{idx + 1}.jpg"
                filepath = images_dir / filename
                
                logger.info(f"下载图片 {idx + 1}/{len(content.images)}...")
                await download_file(client, img_url, filepath, rename_strategy=rename_strategy)
                downloaded.append(filepath)
                
                if progress_callback:
                    progress_callback((idx + 1) / len(content.images))
                if task_id:
                    from .download_queue import download_queue
                    download_queue.update_progress(task_id, (idx + 1) / len(content.images))
            
            logger.info(f"下载完成: {len(downloaded)} 张图片")
    
    return downloaded


async def fetch_and_download(url: str, output_dir: Path) -> List[Path]:
    """
    一站式解析下载
    
    Args:
        url: 小红书URL
        output_dir: 输出目录
        
    Returns:
        下载文件路径列表
    """
    content = await parse_xiaohongshu(url)
    return await download_xhs_content(content, output_dir)
