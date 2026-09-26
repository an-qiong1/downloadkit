import re
import os
import sys
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
    # 优先级：MUSIC_DL_DIR 环境变量（Docker） > 配置文件 > 内置默认值
    raw = os.environ.get("MUSIC_DL_DIR") or (config.get("general", {}) or {}).get("download_dir") or config.get("download_dir") or "./downloads"
    p = Path(raw).expanduser()
    if not p.is_absolute():
        # 相对路径 → 基于 EXE 所在目录解析（onefile 模式下 __file__ 在临时目录）
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).parent
        else:
            base = Path.cwd()
        p = base / p
    return p.resolve()


def get_download_subdir(category: str) -> Path:
    """获取分类子目录，不存在则创建。支持配置文件自定义各类别目录。

    优先级：
    1. MUSIC_DL_DIR 环境变量设了 → 使用 get_download_dir() / category（无视子目录配置）
    2. 配置文件有自定义子目录 → 使用自定义路径
    3. 以上都没有 → 使用 get_download_dir() / category
    """
    # 环境变量设了 → 子目录跟随根目录
    if os.environ.get("MUSIC_DL_DIR"):
        base_dir = get_download_dir()
        subdir = base_dir / category
        subdir.mkdir(parents=True, exist_ok=True)
        return subdir

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
        # 默认下载根目录：Windows 通用位置（每台 Win10/11 都有）
        # 子目录会在 get_download_subdir() 中按需自动创建
        "download_dir": "~/Downloads",
        "download_dir_music": "~/Downloads/music",
        "download_dir_video": "~/Downloads/videos",
        "download_dir_animated": "~/Downloads/animated",
        "download_dir_images": "~/Downloads/images",
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
    "subscription": {
        # 订阅自动轮询。默认关闭 —— 装完不该自己在后台跑起来，
        # 由用户在「创作者订阅」页手动打开。
        "enabled": False,
        # 轮询间隔（分钟）。默认 60 分钟，走保守路线：
        # 抖音风控敏感，实测已触发过验证码中间页，宁可慢也别撞。
        # 允许 15~1440，服务端会做上下限裁剪。
        "interval_minutes": 60,
        # 单轮最多下载几个新作品，0 = 不限制
        "max_new_per_check": 3,
        # 间隔抖动百分比：实际等待 = interval ± jitter，
        # 避免每次都踩在整点节律上（固定周期更容易被风控识别）
        "jitter_percent": 20,
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


def _migrate_config(config: dict) -> dict:
    """自动迁移旧版默认值 → 新版默认值

    背景：DEFAULT_CONFIG 历史上是 "./downloads"，2026-07 改成了 "~/Downloads"。
    但用户的 config.toml 里已经存了旧值，load_config() 优先读文件值，
    导致新默认值永远不生效。

    迁移规则（只针对"显然是旧默认值"的值，用户手动改过的值不碰）：
    - download_dir        == "./downloads"  或  ""  → "~/Downloads"
    - download_dir_music  == "./downloads/music" 或 "" → "~/Downloads/music"
    - download_dir_video  == "./downloads/videos" 或 "" → "~/Downloads/videos"
    - download_dir_animated == "./downloads/animated" 或 "" → "~/Downloads/animated"
    - download_dir_images == "./downloads/images" 或 "" → "~/Downloads/images"

    返回 (config, did_migrate)；调用方如需落盘可自行 save_config。
    """
    # 旧值 → 新值的映射
    _MIGRATIONS = {
        "download_dir":         {"./downloads":        "~/Downloads"},
        "download_dir_music":   {"./downloads/music":  "~/Downloads/music"},
        "download_dir_video":   {"./downloads/videos": "~/Downloads/videos"},
        "download_dir_animated": {"./downloads/animated": "~/Downloads/animated"},
        "download_dir_images":  {"./downloads/images": "~/Downloads/images"},
    }

    gen = config.get("general", {}) or {}
    did_migrate = False

    for key, mapping in _MIGRATIONS.items():
        cur = gen.get(key, "") or ""
        # 空值：填新默认值
        if not cur.strip():
            gen[key] = next(iter(mapping.values()))
            did_migrate = True
            continue
        # 旧默认值：替换
        if cur.strip() in mapping:
            gen[key] = mapping[cur.strip()]
            did_migrate = True

    if did_migrate:
        config["general"] = gen

    return config, did_migrate


def load_config() -> dict:
    path = _config_path()
    if not path.exists():
        return _normalize_config({})
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    config = _normalize_config(raw)

    # 自动迁移旧默认值 → 静默落盘（不打断调用方）
    config, did_migrate = _migrate_config(config)
    if did_migrate:
        try:
            save_config(config)
        except Exception:
            # 落盘失败也无所谓，下次启动还会再尝试
            pass

    return config


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


def get_config_value(section: str, key: str, default=None):
    """便捷读取配置项（不存在时返回 default）"""
    return load_config().get(section, {}).get(key, default)


def read_cookie_from_file(path: str) -> str:
    """从文件读取 Cookie，自动识别格式（不会抛异常）

    支持的格式：
    - .json:      {"name1": "value1", "name2": "value2"}
    - .txt 等:    "name1=value1; name2=value2"  (单行 cookie 字符串)
    - Netscape:   "# Netscape HTTP Cookie File" 开头的 tab 分隔格式（yt-dlp 风格）

    Args:
        path: 文件路径，支持 ~ 展开。文件不存在或读取失败返回 ''。

    Returns:
        Cookie 字符串，格式为 "name1=value1; name2=value2"。失败返回 ''。
    """
    import json

    if not path:
        return ""
    p = Path(path).expanduser()
    if not p.exists() or not p.is_file():
        return ""
    try:
        content = p.read_text(encoding="utf-8").strip()
    except Exception:
        try:
            content = p.read_text(encoding="gbk").strip()
        except Exception:
            return ""
    if not content:
        return ""

    suffix = p.suffix.lower()

    # JSON
    if suffix == ".json":
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                pairs = [f"{k}={v}" for k, v in data.items() if v]
                return "; ".join(pairs)
        except Exception:
            return ""
        return ""

    # Netscape / yt-dlp 格式（tab 分隔）
    first_line = content.splitlines()[0] if content.splitlines() else ""
    if "\t" in first_line or content.startswith("# Netscape"):
        pairs = []
        for line in content.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("//"):
                continue
            parts = line.split("\t")
            # Netscape 格式: domain flag path secure expiry name value
            if len(parts) >= 7:
                name, value = parts[5], parts[6]
                if name and value:
                    pairs.append(f"{name}={value}")
        if pairs:
            return "; ".join(pairs)

    # 默认：当作纯 cookie 字符串
    return content


def validate_download_dir(path: str) -> dict:
    """校验下载目录路径

    Returns:
        {
            "ok": bool,            # 是否可用
            "absolute": str,       # 解析后的绝对路径
            "exists": bool,        # 是否已存在
            "writable": bool,      # 是否可写
            "message": str,        # 给用户看的中文提示
        }
    """
    if not path or not path.strip():
        return {"ok": False, "absolute": "", "exists": False, "writable": False, "message": "路径不能为空"}
    p = Path(path.strip()).expanduser()
    if not p.is_absolute():
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).parent
        else:
            base = Path.cwd()
        p = (base / p).resolve()
    else:
        p = p.resolve()

    exists = p.exists()
    writable = False
    if exists:
        if not p.is_dir():
            return {"ok": False, "absolute": str(p), "exists": True, "writable": False, "message": f"路径存在但不是目录：{p}"}
        writable = os.access(p, os.W_OK)
    else:
        # 尝试创建
        try:
            p.mkdir(parents=True, exist_ok=True)
            writable = True
            exists = True
        except Exception as e:
            return {"ok": False, "absolute": str(p), "exists": False, "writable": False, "message": f"无法创建目录：{e}"}

    if not writable:
        return {"ok": False, "absolute": str(p), "exists": True, "writable": False, "message": f"目录不可写：{p}"}

    return {"ok": True, "absolute": str(p), "exists": True, "writable": True, "message": "OK"}


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
