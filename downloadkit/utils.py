import re
import os
import shutil
import sys
import tomllib
try:
    import tomli_w
except ImportError:
    tomli_w = None
from pathlib import Path

from .logger import get_logger

_log = get_logger("utils")

# Windows：GUI 进程（PyInstaller console=False）启动控制台子程序（yt-dlp / ffmpeg /
# powershell）时，若不显式隐藏，系统会为子进程新开一个可见的命令行窗口 —— 批量
# 下载时表现为"连续弹出黑框"。所有 create_subprocess_exec / Popen 都该带上它。
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


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


# 会从系统下载目录搬进总文件夹的分类目录名
_LEGACY_CATEGORIES = {
    "music": "download_dir_music",
    "videos": "download_dir_video",
    "animated": "download_dir_animated",
    "images": "download_dir_images",
}


def _move_tree_contents(src, dst) -> dict:
    """把 src 下的所有条目搬到 dst（同名不覆盖，源目录搬空才删）

    Returns:
        {"moved": [名字...], "errors": ["名字: 原因"...], "removed": bool}
    """
    moved, errors = [], []
    dst.mkdir(parents=True, exist_ok=True)

    for item in sorted(src.iterdir(), key=lambda p: p.name):
        target = dst / item.name
        if target.exists():
            # 绝不覆盖：目标已存在就把源改名后搬，宁可多个 (1) 也不能吞文件
            n = 1
            while target.exists():
                target = dst / f"{item.stem} ({n}){item.suffix}"
                n += 1
        try:
            shutil.move(str(item), str(target))
            moved.append(item.name)
        except Exception as e:  # 文件被占用 / 权限不足 —— 留在原地，别中断
            errors.append(f"{item.name}: {e}")

    removed = False
    try:
        if not any(src.iterdir()):
            src.rmdir()
            removed = True
    except Exception as e:
        errors.append(f"删除旧目录 {src}: {e}")

    return {"moved": moved, "errors": errors, "removed": removed}


def migrate_legacy_download_dirs(config: dict | None = None) -> dict:
    """把散落在系统下载目录下的旧分类文件夹搬进 DownloadKit 总文件夹

    2026-09-27 用户反馈：装完直接在 `C:\\Users\\x\\Downloads` 下生成
    music/、videos/、animated/ 三个软件自建目录，很脏。现在默认根目录改成了
    `~/Downloads/DownloadKit`，但老用户目录里已经躺着文件，所以启动时一次性搬。

    一次性、幂等，三条安全红线：
      1. 只动「新路径 == 最新默认值」的分类目录 —— 用户自定义过路径的一律不碰
      2. 同名冲突绝不覆盖：源条目改名 `<name> (1)` 再搬
      3. 单个条目搬失败（被占用/没权限）就留在原地并记录，不中断启动、
         源目录非空就绝不删除

    Docker（设了 MUSIC_DL_DIR）直接跳过：那边的目录由 compose 挂载决定。

    Returns:
        {"skipped": 原因} 或
        {"moved": 总数, "categories": {分类: {...}}, "errors": [...]}
    """
    if os.environ.get("MUSIC_DL_DIR"):
        return {"skipped": "MUSIC_DL_DIR 已设置（Docker 场景不迁移）"}

    cfg = config if config is not None else load_config()
    gen = cfg.get("general", {}) or {}
    root = Path(str(gen.get("download_dir", "") or "")).expanduser()
    if not root.is_absolute():
        return {"skipped": "download_dir 不是绝对路径"}

    default_root = Path.home() / "Downloads" / "DownloadKit"
    categories = dict(_LEGACY_CATEGORIES)
    if root != default_root:
        # 用户自定义了总目录：只有根目录也是默认值时，才认为分类目录是"老默认值"
        return {"skipped": f"download_dir 已自定义为 {root}，跳过迁移"}

    # others 没有独立配置项，永远是 root/others，一并处理
    categories["others"] = ""

    report = {"moved": 0, "categories": {}, "errors": []}

    for cat, cfg_key in categories.items():
        new_dir = root / cat
        # 分类目录被单独自定义过 → 不碰
        if cfg_key and str(gen.get(cfg_key, "") or "").strip():
            cur = Path(str(gen[cfg_key])).expanduser()
            if cur != new_dir:
                report["categories"][cat] = {"skipped": f"已自定义为 {cur}"}
                continue

        legacy = Path.home() / "Downloads" / cat
        try:
            if not legacy.is_dir() or legacy == new_dir:
                continue
            res = _move_tree_contents(legacy, new_dir)
        except Exception as e:
            report["errors"].append(f"{cat}: {e}")
            continue

        report["categories"][cat] = res
        report["moved"] += len(res["moved"])
        report["errors"].extend(f"{cat}/{x}" for x in res["errors"])
        if res["moved"] or res["removed"]:
            _log.info(
                f"下载目录迁移 [{cat}]: 搬了 {len(res['moved'])} 项到 {new_dir}"
                + ("，旧目录已删除" if res["removed"] else "，旧目录保留")
            )

    return report


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
        # 默认下载根目录：系统下载目录下的 DownloadKit 总文件夹。
        # 分类目录一律收在总文件夹里 —— 不能直接在 ~/Downloads 下散落
        # music/、videos/ 这些软件自建目录（2026-09-27 用户反馈）。
        # 子目录会在 get_download_subdir() 中按需自动创建
        "download_dir": "~/Downloads/DownloadKit",
        "download_dir_music": "~/Downloads/DownloadKit/music",
        "download_dir_video": "~/Downloads/DownloadKit/videos",
        "download_dir_animated": "~/Downloads/DownloadKit/animated",
        "download_dir_images": "~/Downloads/DownloadKit/images",
        "max_concurrent": 3,
        "log_level": "INFO",
        "language": "zh-CN",
        "history_max_records": 1000,
        "rename_strategy": "skip",
        "motion_photo_default": True,
        # 关闭主窗口时最小化到托盘（= 程序常驻后台，轮询/下载不中断）。
        # 默认关闭：装完就静默常驻会让人以为程序没关掉，
        # 由用户在「设置 → 启动与后台」主动打开。
        # 仅打包成 exe 后生效，源码运行时忽略（见 run.py）。
        "close_to_tray": False,
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

    背景：DEFAULT_CONFIG 历史上改过两次默认下载目录：
      ./downloads            （2026-05 初版）
      ~/Downloads            （2026-07 改）
      ~/Downloads/DownloadKit（2026-09-27 改，分类目录收进总文件夹）
    但用户的 config.toml 里已经存了旧值，load_config() 优先读文件值，
    导致新默认值永远不生效。

    迁移规则（只针对"显然是旧默认值"的值，用户手动改过的值不碰）：
    每个 key 一条历史链，命中链上任意一档都直接跳到**最新**默认值
    （一次到位，不用等两次启动才生效）。

    返回 (config, did_migrate)；调用方如需落盘可自行 save_config。
    """
    # 历史链：旧默认值们 → 最新默认值（最后一项）
    _MIGRATIONS = {
        "download_dir": [
            "./downloads", "~/Downloads", "~/Downloads/DownloadKit",
        ],
        "download_dir_music": [
            "./downloads/music", "~/Downloads/music",
            "~/Downloads/DownloadKit/music",
        ],
        "download_dir_video": [
            "./downloads/videos", "~/Downloads/videos",
            "~/Downloads/DownloadKit/videos",
        ],
        "download_dir_animated": [
            "./downloads/animated", "~/Downloads/animated",
            "~/Downloads/DownloadKit/animated",
        ],
        "download_dir_images": [
            "./downloads/images", "~/Downloads/images",
            "~/Downloads/DownloadKit/images",
        ],
    }

    gen = config.get("general", {}) or {}
    did_migrate = False

    for key, chain in _MIGRATIONS.items():
        cur = (gen.get(key, "") or "").strip()
        latest = chain[-1]
        # 空值：填最新默认值
        if not cur:
            gen[key] = latest
            did_migrate = True
            continue
        # 链上的历史默认值：一次跳到最新
        if cur in chain and cur != latest:
            gen[key] = latest
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
