"""
aria2 磁力链接下载服务
通过 aria2c 命令行工具下载 BT 磁力链接
"""
import os
import re
import asyncio
from pathlib import Path
from typing import Optional, Callable

from app.core.config import settings


class Aria2Downloader:
    """aria2 磁力下载管理器"""

    def __init__(self):
        self._torrent_dir = settings.download_dir_path / "video" / "torrent"
        self._torrent_dir.mkdir(parents=True, exist_ok=True)

    async def find_aria2c(self) -> Optional[str]:
        """查找 aria2c 可执行文件"""
        import shutil
        aria2c = shutil.which("aria2c")
        if aria2c:
            return aria2c

        # 常见安装路径
        common_paths = [
            "C:\\Program Files\\aria2\\aria2c.exe",
            "C:\\Program Files (x86)\\aria2\\aria2c.exe",
            os.path.expanduser("~\\scoop\\apps\\aria2\\current\\aria2c.exe"),
            os.path.expanduser("~\\AppData\\Local\\aria2\\aria2c.exe"),
        ]
        for p in common_paths:
            if os.path.isfile(p):
                return p
        return None

    async def download_magnet(
        self,
        magnet: str,
        output_dir: Optional[Path] = None,
        progress_callback: Optional[Callable] = None,
    ) -> Optional[Path]:
        """
        通过 aria2c 下载磁力链接
        返回下载完成的文件路径
        """
        aria2c = await self.find_aria2c()
        if not aria2c:
            raise RuntimeError(
                "未找到 aria2c，请安装 aria2:\n"
                "  1. Windows: scoop install aria2 或下载 aria2c.exe 放入 PATH\n"
                "  2. macOS: brew install aria2\n"
                "  3. Linux: apt install aria2"
            )

        target_dir = output_dir or self._torrent_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        # 创建 session 文件（用于恢复下载）
        session_file = target_dir / "aria2.session"
        if not session_file.exists():
            session_file.write_text("")

        cmd = [
            aria2c,
            "--dir", str(target_dir),
            "--input-file", str(session_file),
            "--save-session", str(session_file),
            "--continue=true",
            "--max-connection-per-server=16",
            "--split=16",
            "--bt-max-peers=50",
            "--seed-time=0",  # 下载完成后不继续做种
            "--console-log-level=error",
            "--summary-interval=0",
            magnet,
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # 读取输出
        last_progress = 0
        while proc.stdout:
            line = await proc.stdout.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="ignore").strip()

            # 检测下载完成
            if "Download complete" in text:
                if progress_callback:
                    await progress_callback("", 100.0, "completed")

            # 检测文件名
            if "[#" in text and ") " in text:
                # 提取完成文件名
                name_match = re.search(r'\)\s*(.+?)\s*$', text)
                if name_match:
                    pass  # 记录文件名

        await proc.wait()

        if proc.returncode != 0 and proc.returncode != 3:
            # returncode 3 = 部分文件下载完成但某些出错
            if proc.returncode > 3:
                raise RuntimeError(f"aria2c 退出码: {proc.returncode}")

        # 查找最新的文件
        files = sorted(target_dir.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
        for f in files:
            if f.is_file() and f.stat().st_size > 1024 * 1024:  # > 1MB
                return f

        # 如果没找到大文件，返回目录中最大的文件
        largest = max(
            [f for f in target_dir.iterdir() if f.is_file()],
            key=lambda f: f.stat().st_size,
            default=None,
        )
        return largest

    async def is_available(self) -> bool:
        """检查 aria2c 是否可用"""
        aria2c = await self.find_aria2c()
        return aria2c is not None
