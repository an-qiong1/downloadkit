import re
import os
import tomllib
try:
    import tomli_w
except ImportError:
    tomli_w = None
from pathlib import Path


def sanitize_filename(filename: str) -> str:
    sanitized = re.sub(r'[\\/:*?"<>|]', "_", filename)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    return sanitized or "unknown"


def get_download_dir() -> Path:
    config = load_config()
    # 支持新旧两种配置格式
    path = (config.get("general", {}) or {}).get("download_dir") or config.get("download_dir") or os.environ.get("MUSIC_DL_DIR") or "./downloads"
    return Path(path).expanduser().resolve()


def get_download_subdir(category: str) -> Path:
    """获取分类子目录，不存在则创建。支持配置文件自定义各类别目录。"""
    config = load_config()
    # 类别到配置字段的映射
    _category_config_map = {
        'music': 'download_dir_music',
        'videos': 'download_dir_video',
        'animated': 'download_dir_animated',
        'images': 'download_dir_images',
    }
    config_field = _category_config_map.get(category)
    custom_dir = ""
    if config_field:
        custom_dir = (config.get("general", {}) or {}).get(config_field, "") or ""
    if custom_dir:
        subdir = Path(custom_dir).expanduser().resolve()
    else:
        base_dir = get_download_dir()
        subdir = base_dir / category
    subdir.mkdir(parents=True, exist_ok=True)
    return subdir


def get_category_by_extension(filename: str) -> str:
    """根据文件扩展名判断分类"""
    ext = Path(filename).suffix.lower()
    
    music_exts = {'.mp3', '.m4a', '.flac', '.wav', '.ogg'}
    video_exts = {'.mp4', '.webm', '.avi', '.mkv'}
    image_exts = {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}
    animated_exts = {'.gif'}
    
    if ext in music_exts:
        return 'music'
    elif ext in video_exts:
        return 'videos'
    elif ext in image_exts:
        return 'images'
    elif ext in animated_exts:
        return 'animated'
    else:
        return 'others'


DEFAULT_CONFIG: dict = {
    "general": {
        "download_dir": "./downloads",
        "download_dir_music": "",
        "download_dir_video": "",
        "download_dir_animated": "",
        "download_dir_images": "",
        "max_concurrent": 3,
        "log_level": "INFO",
        "language": "zh-CN",
        "history_max_records": 1000,
        "rename_strategy": "skip",
        "motion_photo_default": True,
    },
    "proxy": {
        "enabled": True,
        "global": "",
        "youtube": "",
        "douyin": "",
        "bilibili": "",
        "xiaohongshu": "",
    },
    "cookie": {
        "douyin_path": "",
        "bilibili_path": "",
    },
}


def _config_path() -> Path:
    return Path.home() / ".downloadkit" / "config.toml"


def _ensure_config_dir():
    """确保配置目录存在"""
    _config_path().parent.mkdir(parents=True, exist_ok=True)


def _normalize_config(raw: dict) -> dict:
    """将旧格式（扁平键）转换为新格式（嵌套结构），缺失字段补默认值"""
    result = {}

    # 已知的顶层 section 名称
    section_names = set(DEFAULT_CONFIG.keys())

    for section, defaults in DEFAULT_CONFIG.items():
        if section in raw and isinstance(raw[section], dict):
            # 新格式：已有完整结构，补缺失字段
            merged = dict(defaults)
            merged.update(raw[section])
            result[section] = merged
        else:
            # 先填默认值
            result[section] = dict(defaults)

    # 处理旧格式扁平键：扫描 raw 中不属于 section 的键，尝试归入对应 section
    flat_key_to_section = {
        "download_dir": "general",
        "max_concurrent": "general",
        "log_level": "general",
        "language": "general",
    }
    for key, section in flat_key_to_section.items():
        if key in raw:
            result.setdefault(section, {})[key] = raw[key]

    return result


def load_config() -> dict:
    path = _config_path()
    if not path.exists():
        return _normalize_config({})
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    return _normalize_config(raw)


def save_config(config: dict) -> None:
    """保存配置到 config.toml

    Args:
        config: 完整配置字典（general / proxy / cookie 结构）
    """
    _ensure_config_dir()
    path = _config_path()

    # 合并现有配置，只覆盖传入的字段
    current = load_config()
    for section, values in config.items():
        if isinstance(values, dict):
            current.setdefault(section, {})
            current[section].update(values)
        else:
            current[section] = values

    if tomli_w:
        with open(path, "wb") as f:
            tomli_w.dump(current, f)
    else:
        # 降级：手动写入 TOML（简单场景够用）
        lines = []
        for section, values in current.items():
            if isinstance(values, dict):
                lines.append(f"\n[{section}]")
                for k, v in values.items():
                    if isinstance(v, bool):
                        lines.append(f'{k} = {"true" if v else "false"}')
                    elif isinstance(v, int):
                        lines.append(f"{k} = {v}")
                    else:
                        # 转义 TOML 字符串中的特殊字符（反斜杠、双引号）
                        escaped = str(v).replace('\\', '\\\\').replace('"', '\\"')
                        lines.append(f'{k} = "{escaped}"')
            else:
                escaped = str(values).replace('\\', '\\\\').replace('"', '\\"')
                lines.append(f'{section} = "{escaped}"')
        path.write_text("\n".join(lines).strip(), encoding="utf-8")


def check_download_status(task_id: str) -> None:
    """检查下载任务的暂停/取消状态，抛出异常"""
    from .exceptions import PauseException, CancelException
    from .download_queue import download_queue
    
    if task_id:
        if download_queue.is_paused(task_id):
            raise PauseException("下载已暂停")
        if download_queue.is_cancelled(task_id):
            raise CancelException("下载已取消")


async def download_file(
    client,
    url: str,
    filepath: Path,
    task_id: str = None,
    progress_callback=None,
    headers: dict = None,
    rename_strategy: str | None = None,
) -> None:
    from .exceptions import PauseException, CancelException
    from .download_queue import download_queue

    if rename_strategy is None:
        cfg = load_config()
        rename_strategy = cfg.get('general', {}).get('rename_strategy', 'skip')

    temp_path = filepath.with_suffix(filepath.suffix + '.tmp')
    downloaded_size = temp_path.stat().st_size if temp_path.exists() else 0

    req_headers = dict(headers) if headers else {}
    if downloaded_size > 0:
        req_headers['Range'] = f'bytes={downloaded_size}-'

    async with client.stream("GET", url, headers=req_headers) as resp:
        resp.raise_for_status()

        content_length = int(resp.headers.get('content-length', 0))

        if resp.status_code == 206:
            total_size = downloaded_size + content_length
            mode = 'ab'
        else:
            total_size = content_length
            downloaded_size = 0
            mode = 'wb'

        with open(temp_path, mode) as f:
            async for chunk in resp.aiter_bytes(chunk_size=8192):
                if task_id:
                    if download_queue.is_paused(task_id):
                        raise PauseException("下载已暂停")
                    if download_queue.is_cancelled(task_id):
                        temp_path.unlink(missing_ok=True)
                        raise CancelException("下载已取消")

                f.write(chunk)
                downloaded_size += len(chunk)

                if progress_callback and total_size > 0:
                    progress_callback(downloaded_size / total_size)
                if task_id and total_size > 0:
                    download_queue.update_progress(task_id, downloaded_size / total_size,
                                                  downloaded_size, total_size)

    # 处理文件已存在的情况
    if filepath.exists():
        if rename_strategy == "overwrite":
            filepath.unlink(missing_ok=True)
            temp_path.rename(filepath)
        elif rename_strategy == "rename":
            stem = filepath.stem
            ext = filepath.suffix
            counter = 1
            new_path = filepath.parent / f"{stem} ({counter}){ext}"
            while new_path.exists():
                counter += 1
                new_path = filepath.parent / f"{stem} ({counter}){ext}"
            temp_path.rename(new_path)
        else:  # "skip" — 默认行为
            temp_path.unlink(missing_ok=True)
        return
    temp_path.rename(filepath)
