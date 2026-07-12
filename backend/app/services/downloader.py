import asyncio
from pathlib import Path
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.download_task import DownloadTask
from app.models.media_item import MediaItem
from app.services.parser_factory import get_parser


class DownloadManager:
    def __init__(self, db: Session):
        self.db = db
        settings.download_dir_path.mkdir(parents=True, exist_ok=True)
        settings.temp_dir_path.mkdir(parents=True, exist_ok=True)

    def _get_platform_dir(self, platform: str, media_type: str) -> Path:
        target = settings.download_dir_path / media_type / platform
        target.mkdir(parents=True, exist_ok=True)
        return target

    @staticmethod
    def _has_ffmpeg() -> bool:
        import shutil
        return shutil.which("ffmpeg") is not None

    async def execute_download(self, task: DownloadTask, progress_callback=None):
        parser = get_parser(task.platform)
        if not parser:
            task.status = "failed"
            task.error_message = f"不支持的平台: {task.platform}"
            self.db.commit()
            return

        try:
            task.status = "downloading"
            task.progress = 0.0
            self.db.commit()

            platform_dir = self._get_platform_dir(task.platform, task.media_type)
            safe_title = "".join(c for c in task.title if c.isalnum() or c in " _-").strip()
            output_filename = f"{safe_title}_{task.platform}.%(ext)s"
            output_path = str(platform_dir / output_filename)

            cmd = await parser.get_download_command(task.url, task.format_id, output_path)

            if not self._has_ffmpeg():
                skip_flags = {"--extract-audio", "--embed-thumbnail", "--add-metadata"}
                val_flags = {"--audio-format", "--merge-output-format", "--postprocessor-args"}
                cleaned = []
                i = 0
                while i < len(cmd):
                    if cmd[i] in skip_flags:
                        i += 1
                        continue
                    if cmd[i] in val_flags:
                        i += 2
                        continue
                    # 无 ffmpeg 时合并格式会失败，降级为单流
                    if cmd[i] == "-f" and i + 1 < len(cmd) and "+" in cmd[i + 1]:
                        cleaned.append(cmd[i])
                        cleaned.append("best")
                        i += 2
                        continue
                    cleaned.append(cmd[i])
                    i += 1
                cmd = cleaned

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )

            async def _read_stderr():
                while True:
                    try:
                        line = await asyncio.wait_for(proc.stderr.readline(), timeout=30)
                    except asyncio.TimeoutError:
                        proc.kill()
                        raise RuntimeError("yt-dlp 30 秒无输出，已终止")
                    if not line:
                        break
                    line = line.decode("utf-8", errors="ignore").strip()
                    if "[download]" in line and "%" in line:
                        try:
                            pct = float(line.split("[download]")[1].strip().split("%")[0])
                            task.progress = pct
                            if progress_callback:
                                await progress_callback(task.id, pct, "downloading")
                            self.db.commit()
                        except (ValueError, IndexError):
                            pass

            await asyncio.wait_for(_read_stderr(), timeout=600)
            await asyncio.wait_for(proc.wait(), timeout=10)

            if proc.returncode != 0:
                raise RuntimeError(f"yt-dlp 退出码: {proc.returncode}")

            downloaded_files = list(platform_dir.glob(f"{safe_title}*"))
            actual_file = None
            for f in downloaded_files:
                if f.stat().st_size > 1024:
                    actual_file = f
                    break
            if not actual_file:
                files = sorted(platform_dir.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True)
                actual_file = files[0] if files else None

            if actual_file:
                task.file_path = str(actual_file)
                task.file_size = actual_file.stat().st_size
                task.status = "completed"
                task.progress = 100.0
                self._add_to_library(task, actual_file)
            else:
                task.status = "failed"
                task.error_message = "未找到下载文件"

            self.db.commit()

        except Exception as e:
            task.status = "failed"
            task.error_message = str(e)
            self.db.commit()

    def _add_to_library(self, task: DownloadTask, file_path: Path):
        existing = self.db.query(MediaItem).filter(MediaItem.task_id == task.id).first()
        if existing:
            return
        item = MediaItem(
            task_id=task.id,
            title=task.title,
            artist="",
            album="",
            platform=task.platform,
            media_type=task.media_type,
            file_path=str(file_path),
            file_size=file_path.stat().st_size,
        )
        self.db.add(item)
        self.db.commit()
