# -*- coding: utf-8 -*-
"""视频平台分发共享层：平台识别 + 统一解析 + 统一下载。

供 CLI（cli.py 的 ``parse`` / ``video`` 命令）与脚本调用方使用，避免
CLI 各自再抄一份平台分发逻辑。

历史：``detect_platform`` 原是 server.py 的本地函数（HTTP 路由用），CLI
起步时发现无法复用，2026-10-14 搬到本模块统一为一份；server.py 改为
import。注意 server 的 HTTP 路由层（api_video_parse / _download_func）
仍保留各自的平台分发——它们耦合了任务队列与下载历史记录，重构收益不抵
回归风险（该区域目前零测试覆盖）；本模块的 ``parse_url`` /
``download_parsed`` 面向 CLI，输出结构与 /api/video/parse 的响应契约
对齐（额外多一个 ``raw`` 键装原始对象，供下载复用，输出 JSON 时剔除）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from .bilibili import parse_bilibili, download_bilibili_video
from .douyin import (
    fetch_content as douyin_fetch_content,
    download_content as douyin_download_content,
    ContentType as DouyinContentType,
)
from .generic_video import (
    parse_generic,
    download_generic_video,
    is_http_url,
    is_direct_media_url,
    build_file_stem,
)
from .utils import get_download_dir, get_download_subdir
from .xiaohongshu import parse_xiaohongshu, download_xhs_content
from .youtube import parse_youtube, download_youtube_video

logger = logging.getLogger(__name__)


def detect_platform(url: str) -> Optional[str]:
    """按域名判断链接属于哪个视频平台。

    Returns:
        'douyin' / 'bilibili' / 'youtube' / 'xiaohongshu' /
        'generic'（任何 http(s) 链接的兜底，走 yt-dlp）/ None（非 http 链接）
    """
    if 'douyin.com' in url or 'tiktok.com' in url:
        return 'douyin'
    elif 'bilibili.com' in url or 'b23.tv' in url:
        return 'bilibili'
    elif 'youtube.com' in url or 'youtu.be' in url:
        return 'youtube'
    elif 'xiaohongshu.com' in url or 'xhslink.com' in url:
        return 'xiaohongshu'
    elif is_http_url(url):
        # 兜底：任何 http(s) 链接交给 generic（L0 直链 / L1 网页）
        return 'generic'
    else:
        return None


async def parse_url(
    url: str,
    *,
    referer: str = "",
    title_hint: str = "",
) -> dict[str, Any]:
    """统一解析：按平台分发，返回 /api/video/parse 同构的 dict。

    额外的 ``raw`` 键装各平台原始对象（download_parsed 要用；输出 JSON
    时请剔除）。

    Args:
        url: 视频链接（非 http 链接抛 ValueError）
        referer: 来源页 Referer（generic 防盗链，嗅探阶段拿到的真实来源页）
        title_hint: 命名提示（书签标题等），参与 generic 的 suggested_name

    Raises:
        ValueError: 不支持的平台
        Exception: 各平台解析器原样抛出（含 TimeoutError/RuntimeError）
    """
    platform = detect_platform(url)
    if not platform:
        raise ValueError("不支持的平台链接")

    if platform == 'douyin':
        content = await douyin_fetch_content(url)
        # 实况照片：从 motion_photo_pairs 提取全部配对数据
        live_video_urls: list[str] = []
        live_images: list[dict] = []
        if content.content_type == DouyinContentType.ANIMATED and content.motion_photo_pairs:
            for pair in content.motion_photo_pairs:
                live_images.append({
                    "url": pair.image.url,
                    "video_url": pair.video.url,
                })
                live_video_urls.append(pair.video.url)
        else:
            live_images = [{"url": img.url} for img in content.images] if content.images else []
        return {
            "platform": "douyin",
            "url": url,
            "title": content.title,
            "author": content.author,
            "cover": content.cover,
            "content_type": content.content_type.value,
            "video_url": content.video_url or (live_video_urls[0] if live_video_urls else None),
            "video_urls": live_video_urls or None,
            "images": live_images,
            "raw": content,
        }

    if platform == 'bilibili':
        video = await parse_bilibili(url)
        return {
            "platform": "bilibili",
            "url": url,
            "title": video.title,
            "author": video.author,
            "cover": video.cover,
            "content_type": "video",
            "duration": video.duration,
            "quality": video.quality,
            "raw": video,
        }

    if platform == 'youtube':
        video = await parse_youtube(url)
        return {
            "platform": "youtube",
            "url": url,
            "title": video.title,
            "author": video.author,
            "cover": video.cover,
            "content_type": "video",
            "duration": video.duration,
            "raw": video,
        }

    if platform == 'xiaohongshu':
        content = await parse_xiaohongshu(url)
        return {
            "platform": "xiaohongshu",
            "url": url,
            "title": content.title,
            "author": content.author,
            "cover": content.cover,
            "content_type": content.content_type.value,
            "video_url": content.video_url,
            "images": [{"url": u} for u in content.images],
            "raw": content,
        }

    # generic：L0 直链 / L1 网页，yt-dlp generic extractor
    video = await parse_generic(url, referer=referer or None)
    ret: dict[str, Any] = {
        "platform": "generic",
        "url": url,
        "title": video.title,
        "author": video.author,
        "cover": video.cover,
        "content_type": "video",
        "duration": video.duration,
        "is_playlist": video.is_playlist,
        "entry_count": video.entry_count,
        "webpage_url": video.webpage_url,
        "formats": video.formats,
        # 预览将保存的文件名（剧名-第01集 / 网页标题 / web_URL末段）
        "suggested_name": build_file_stem(
            hint=title_hint, title=video.title,
            page_title=video.page_title, url=url,
        ),
        "raw": video,
    }
    # 只有 mp4 直链能被 <video> 直接播放；m3u8 需要 hls.js，
    # 给出去只会黑屏，交给下载流程处理
    if is_direct_media_url(url) and video.ext == "mp4":
        ret["video_url"] = url
    return ret


async def download_parsed(
    info: dict[str, Any],
    *,
    out_dir: str | Path | None = None,
    quality: str = "best",
    rename_strategy: str | None = None,
    name_hint: str = "",
    referer: str = "",
    task_id: str | None = None,
    progress_callback=None,
    merge_motion_photo: bool | None = None,
    apple_live_photo: bool = False,
) -> list[Path]:
    """统一下载：按 ``info['platform']`` 分发到对应下载器。

    Args:
        info: parse_url() 的返回（含 raw；raw 为 None 时按 url 重新解析）
        out_dir:
            - None → 用配置里的下载目录（各平台默认：抖音走分类子目录
              videos/images/animated、小红书落根目录、其余落 videos/，
              与 server 行为一致）
            - 指定 → 产物落 out_dir（抖音例外地会再建分类子目录）
        quality: best/1080/720/480/360（youtube / generic 生效）
        rename_strategy: 重名策略 skip/overwrite/rename，None 从配置读
        name_hint: 命名提示（generic 的产物文件名优先用它）
        referer: generic 防盗链来源页（仅在需要重新解析时生效）
        merge_motion_photo / apple_live_photo: 抖音实况照片选项

    Returns:
        产物路径列表（抖音可能多文件，其余平台单文件）
    """
    platform = info.get("platform")
    raw = info.get("raw")
    url = info.get("url") or info.get("webpage_url") or ""

    if platform == 'douyin':
        if raw is None:
            raw = await douyin_fetch_content(url)
        return await douyin_download_content(
            raw,
            out_dir,
            merge_motion_photo=merge_motion_photo,
            apple_live_photo=apple_live_photo,
            task_id=task_id,
            rename_strategy=rename_strategy,
        )

    # 其余平台的落点：指定 out_dir 直接用；否则按各平台默认
    # （xiaohongshu 落根目录，因为它可能同时产图与视频）
    if platform == 'xiaohongshu':
        default_out = get_download_dir()
    else:
        default_out = get_download_subdir('videos')
    out = Path(out_dir) if out_dir is not None else default_out

    if platform == 'bilibili':
        if raw is None:
            raw = await parse_bilibili(url)
        p = await download_bilibili_video(
            raw, out, task_id=task_id, rename_strategy=rename_strategy)
        return [p]

    if platform == 'youtube':
        if raw is None:
            raw = await parse_youtube(url)
        p = await download_youtube_video(
            raw, out, quality, task_id=task_id, rename_strategy=rename_strategy)
        return [p]

    if platform == 'xiaohongshu':
        if raw is None:
            raw = await parse_xiaohongshu(url)
        return await download_xhs_content(
            raw, out, task_id=task_id, rename_strategy=rename_strategy)

    if platform == 'generic':
        if raw is None:
            raw = await parse_generic(url, referer=referer or None)
        p = await download_generic_video(
            raw, out, quality,
            task_id=task_id,
            rename_strategy=rename_strategy,
            progress_callback=progress_callback,
            name_hint=name_hint or "",
        )
        return [p]

    raise ValueError(f"不支持的平台: {platform}")


def public_info(info: dict[str, Any]) -> dict[str, Any]:
    """剥掉 raw（不可 JSON 序列化的原始对象），供 --json 输出/接口返回。"""
    return {k: v for k, v in info.items() if k != "raw"}
