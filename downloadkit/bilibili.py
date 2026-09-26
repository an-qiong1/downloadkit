"""
哔哩哔哩视频解析下载模块
支持无水印高清视频下载
支持自动从浏览器获取Cookie（高清晰度）
"""

import re
import json
import asyncio
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List

import httpx

from .browser_cookie import get_bilibili_cookie_string
from .download_queue import download_queue
from .utils import download_file, sanitize_filename, read_cookie_from_file, get_config_value

logger = logging.getLogger(__name__)


@dataclass
class BilibiliVideo:
    """B站视频信息"""
    bvid: str
    aid: int
    cid: int
    title: str
    desc: str
    author: str
    cover: str
    duration: int
    video_url: str
    audio_url: str
    quality: int
    file_ext: str = "mp4"


# 清晰度对照表
QUALITY_MAP = {
    16: "流畅 360P",
    32: "清晰 480P",
    64: "高清 720P",
    80: "高清 1080P",
    112: "高清 1080P+",
}

# 基础请求头
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}

# 缓存的Cookie
_cached_cookie: Optional[str] = None


def _load_cookie_from_ui_config() -> Optional[str]:
    """从用户在 UI 配置的 cookie.bilibili_path 文件中读取 Cookie。

    优先级：
    1. UI 配置的 cookie.bilibili_path（设置页填的文件路径）
    2. 默认路径 ~/.downloadkit/cookies/bilibili.txt 与 bilibili.json

    Returns:
        Cookie 字符串，没找到返回 None。
    """
    # 1. UI 配置的路径
    user_path = (get_config_value("cookie", "bilibili_path", "") or "").strip()
    if user_path:
        cookie = read_cookie_from_file(user_path)
        if cookie:
            logger.info(f"[Cookie] 从 UI 配置路径加载 B站 Cookie: {user_path}")
            return cookie

    # 2. 默认目录
    default_dir = Path.home() / '.downloadkit' / 'cookies'
    for filename in ('bilibili.txt', 'bilibili.json'):
        f = default_dir / filename
        if f.exists():
            cookie = read_cookie_from_file(str(f))
            if cookie:
                logger.info(f"[Cookie] 从默认文件加载 B站 Cookie: {f}")
                return cookie

    return None


def get_headers_with_cookie() -> dict:
    """
    获取带Cookie的请求头

    Cookie 加载优先级：
    1. UI 配置的 cookie.bilibili_path
    2. ~/.downloadkit/cookies/bilibili.{txt,json}
    3. Edge 浏览器中 .bilibili.com 域的 Cookie

    Returns:
        包含Cookie的请求头字典
    """
    global _cached_cookie

    headers = HEADERS.copy()

    # 尝试获取Cookie
    if _cached_cookie is None:
        # 1. 先从 UI 配置/默认文件加载
        cookie = _load_cookie_from_ui_config()
        if cookie:
            _cached_cookie = cookie
        else:
            # 2. 退回浏览器
            try:
                _cached_cookie = get_bilibili_cookie_string('edge')
                logger.info("已从Edge浏览器获取Cookie")
            except Exception as e:
                logger.warning(f"获取Cookie失败: {e}")
                _cached_cookie = ""

    if _cached_cookie:
        headers["Cookie"] = _cached_cookie

    return headers


def clear_cookie_cache():
    """清除Cookie缓存"""
    global _cached_cookie
    _cached_cookie = None


def extract_bvid(url: str) -> Optional[str]:
    """从URL中提取BV号"""
    patterns = [
        r'BV[a-zA-Z0-9]{10}',
        r'bilibili\.com/video/(BV[a-zA-Z0-9]{10})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(0) if 'BV' in match.group(0) else match.group(1)
    return None


async def get_video_info(bvid: str) -> Optional[dict]:
    """
    获取视频基本信息
    
    Args:
        bvid: 视频BV号
    
    Returns:
        视频信息字典
    """
    url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
    
    headers = get_headers_with_cookie()
    
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        resp = await client.get(url)
        data = resp.json()
        
        if data.get("code") == 0:
            return data.get("data")
        else:
                logger.error(f"获取视频信息失败: {data.get('message', '未知错误')}")
    
    return None


async def get_video_stream(bvid: str, cid: int, quality: int = 80) -> Optional[dict]:
    """
    获取视频流地址
    
    Args:
        bvid: 视频BV号
        cid: 视频CID
        quality: 清晰度 (16/32/64/80/112)
    
    Returns:
        视频流信息
    """
    url = f"https://api.bilibili.com/x/player/playurl"
    params = {
        "bvid": bvid,
        "cid": cid,
        "qn": quality,
        "fnver": 0,
        "fnval": 4048,  # DASH格式
        "fourk": 1,
    }
    
    headers = get_headers_with_cookie()
    
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        resp = await client.get(url, params=params)
        data = resp.json()
        
        if data.get("code") == 0:
            return data.get("data")
        else:
                logger.error(f"获取视频流失败: {data.get('message', '未知错误')}")
    
    return None


async def parse_bilibili(url: str) -> BilibiliVideo:
    """
    解析B站视频
    
    Args:
        url: B站视频URL
        
    Returns:
        BilibiliVideo对象或None
    """
    # 提取BV号
    bvid = extract_bvid(url)
    if not bvid:
        raise ValueError("无法提取BV号")
    
        logger.info(f"解析视频: {bvid}")
    
    # 获取视频信息
    video_info = await get_video_info(bvid)
    if not video_info:
        raise ValueError("获取视频信息失败")
    
    aid = video_info.get("aid")
    cid = video_info.get("cid") or video_info.get("pages", [{}])[0].get("cid")
    title = video_info.get("title", "")
    desc = video_info.get("desc", "")
    author = video_info.get("owner", {}).get("name", "")
    cover = video_info.get("pic", "")
    duration = video_info.get("duration", 0)
    
    if not cid:
        raise ValueError("获取CID失败")
    
        logger.info(f"标题: {title}")
        logger.info(f"作者: {author}")
        logger.info(f"CID: {cid}")
    
    # 获取视频流地址（尝试最高清晰度）
    stream_data = await get_video_stream(bvid, cid, quality=112)
    if not stream_data:
        # 降级到1080P
        stream_data = await get_video_stream(bvid, cid, quality=80)
    
    if not stream_data:
        raise ValueError("获取视频流地址失败")
    
    # 提取DASH格式的视频和音频地址
    dash = stream_data.get("dash")
    if dash:
        # 获取最佳视频流
        video_streams = dash.get("video", [])
        if video_streams:
            video_url = video_streams[0].get("baseUrl") or video_streams[0].get("base_url")
        else:
            raise ValueError("无可用视频流")
        
        # 获取最佳音频流
        audio_streams = dash.get("audio", [])
        if audio_streams:
            audio_url = audio_streams[0].get("baseUrl") or audio_streams[0].get("base_url")
        else:
            audio_url = None
    else:
        # 非DASH格式（旧版API）
        durl = stream_data.get("durl", [])
        if durl:
            video_url = durl[0].get("url")
            audio_url = None
        else:
            raise ValueError("无可用视频流")
    
    quality = stream_data.get("quality", 80)
    quality_desc = QUALITY_MAP.get(quality, f"{quality}P")
    logger.info(f"清晰度: {quality_desc}")
    
    return BilibiliVideo(
        bvid=bvid,
        aid=aid,
        cid=cid,
        title=title,
        desc=desc,
        author=author,
        cover=cover,
        duration=duration,
        video_url=video_url,
        audio_url=audio_url,
        quality=quality,
    )


async def download_bilibili_video(
    video: BilibiliVideo,
    output_dir: Path,
    task_id: str = None,
    progress_callback=None,
    rename_strategy: str | None = None
) -> Path:
    """
    下载B站视频
    
    Args:
        video: BilibiliVideo对象
        output_dir: 输出目录
        progress_callback: 进度回调函数
        rename_strategy: 文件重名策略 (skip/overwrite/rename)，None则从配置读取
        
    Returns:
        下载文件路径
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 文件名
    filename = sanitize_filename(f"bilibili_{video.bvid}_{video.title}")
    
    # 下载头（带Cookie和Referer）
    headers = get_headers_with_cookie()
    headers["Origin"] = "https://www.bilibili.com"
    
    async with httpx.AsyncClient(timeout=300, headers=headers) as client:
        if video.audio_url:
            # DASH格式：分别下载视频和音频，然后合并
            video_path = output_dir / f"{filename}_video.m4s"
            audio_path = output_dir / f"{filename}_audio.m4s"
            output_path = output_dir / f"{filename}.mp4"
            
            # 下载视频
            logger.info("下载视频流...")
            await download_file(client, video.video_url, video_path, rename_strategy=rename_strategy)
            
            # 下载音频
            logger.info("下载音频流...")
            await download_file(client, video.audio_url, audio_path, rename_strategy=rename_strategy)
            
            # 合并音视频
            logger.info("合并音视频...")
            await _merge_video_audio(video_path, audio_path, output_path)
            
            # 清理临时文件
            video_path.unlink(missing_ok=True)
            audio_path.unlink(missing_ok=True)
            
        else:
            # 单文件格式
            output_path = output_dir / f"{filename}.mp4"
            logger.info("下载视频...")
            await download_file(client, video.video_url, output_path, rename_strategy=rename_strategy)
            logger.info(f"下载完成: {output_path.name}")
    return output_path


async def _merge_video_audio(video_path: Path, audio_path: Path, output_path: Path):
    """使用ffmpeg合并音视频"""
    import subprocess
    
    cmd = [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-i", str(audio_path),
        "-c", "copy",
        str(output_path)
    ]
    
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )
    
    stdout, stderr = await proc.communicate()
    
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg合并失败: {stderr.decode()[:200]}")


async def fetch_and_download(url: str, output_dir: Path) -> Path:
    """
    一站式解析下载
    
    Args:
        url: B站视频URL
        output_dir: 输出目录
        
    Returns:
        下载文件路径
    """
    video = await parse_bilibili(url)
    return await download_bilibili_video(video, output_dir)

