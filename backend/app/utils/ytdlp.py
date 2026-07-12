# -*- coding: utf-8 -*-
"""yt-dlp 调用工具 - 统一处理 Windows PATH 问题"""

import sys
import json
import asyncio
import subprocess
from typing import Any


def ytdlp_base_cmd() -> list[str]:
    """
    yt-dlp 基础命令。
    在 Windows 上 yt-dlp 不在 PATH 中，需要用 python -m yt_dlp 调用。
    """
    return [sys.executable, "-m", "yt_dlp"]


async def ytdlp_run(*args: str, timeout: int = 60) -> str:
    """
    异步运行 yt-dlp 命令，返回 stdout。

    Args:
        *args: yt-dlp 的参数
        timeout: 超时秒数（默认 60）

    Returns:
        stdout 字符串

    Raises:
        TimeoutError: 超时
        RuntimeError: yt-dlp 返回非零退出码
    """
    cmd = ytdlp_base_cmd() + list(args)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        raise TimeoutError(f"yt-dlp 超时 (>{timeout}s): {' '.join(cmd[:4])}...")

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="ignore")[:500]
        raise RuntimeError(f"yt-dlp 错误 (code={proc.returncode}): {err}")

    return stdout.decode("utf-8", errors="ignore")


async def ytdlp_dump_json(url: str, flat: bool = False) -> Any:
    """
    获取 URL 的 yt-dlp JSON 元数据 (--dump-json)。

    Args:
        url: 视频/音频 URL
        flat: 如果是播放列表且 flat=True，返回 list[dict]

    Returns:
        单个 dict 或 list[dict]
    """
    args = ["--dump-json", "--no-download"]
    if flat:
        args.append("--flat-playlist")
    args.append(url)

    output = await ytdlp_run(*args)

    lines = [l for l in output.strip().split("\n") if l]
    results = [json.loads(l) for l in lines]

    if len(results) == 1:
        return results[0]
    return results


async def ytdlp_search(keyword: str, limit: int = 10) -> list[dict]:
    """
    使用 yt-dlp 搜索 (ytsearch{N}:{keyword})。

    Args:
        keyword: 搜索关键词
        limit: 返回条数

    Returns:
        list[dict] 搜索结果
    """
    output = await ytdlp_run(
        "--dump-json", "--no-download", "--flat-playlist",
        f"ytsearch{limit}:{keyword}",
        timeout=30,
    )
    results = []
    for line in output.strip().split("\n"):
        line = line.strip()
        if line:
            results.append(json.loads(line))
    return results
