"""FastAPI web server for downloadkit."""

import sys, os, asyncio, time, logging
from pathlib import Path

# Fix Windows encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from pydantic import BaseModel
from typing import Optional
import uvicorn
import subprocess
import httpx

# Ensure downloadkit is importable
sys.path.insert(0, str(Path(__file__).parent))

from downloadkit.searcher import search_all
from downloadkit.playlist import parse_playlist
from downloadkit.downloader import download_song
from downloadkit.utils import get_download_dir, get_download_subdir, sanitize_filename, load_config, save_config, validate_download_dir, read_cookie_from_file
from downloadkit.file_manager import (
    safe_download_path,
    safe_delete_path,
    list_directory_safe,
    get_media_type,
    PathTraversalError,
    FileOutsideBaseError
)
from downloadkit.douyin import (
    fetch_content, parse_url, download_content,
    DouyinContent, ContentType
)
from downloadkit.bilibili import parse_bilibili, download_bilibili_video, BilibiliVideo
from downloadkit.youtube import parse_youtube, download_youtube_video, YouTubeVideo, is_youtube_url
from downloadkit.xiaohongshu import parse_xiaohongshu, download_xhs_content, XhsContent, is_xiaohongshu_url
from downloadkit.download_queue import download_queue, TaskStatus, DownloadTask
from downloadkit.history import download_history
from downloadkit.exceptions import CancelException, PauseException

logger = logging.getLogger(__name__)

app = FastAPI(title="DownloadKit", description="Multi-platform resource downloader")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:8765", "http://localhost:8765"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# No-cache middleware to prevent browser caching of static files
class NoCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        path = request.url.path
        if path.startswith(("/js/", "/css/", "/vendor/")) or path in ("/", "/index.html"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

app.add_middleware(NoCacheMiddleware)

# Track download status
_downloads: dict[str, dict] = {}
_files_lock = asyncio.Lock()

class DownloadRequest(BaseModel):
    title: str
    artist: str
    platform: str
    song_id: str

class PlaylistRequest(BaseModel):
    url: str

class OpenDirRequest(BaseModel):
    path: str = ""  # 文件相对路径，为空则打开下载根目录

class BatchDeleteRequest(BaseModel):
    files: list[str]  # 文件相对路径列表

class VideoParseRequest(BaseModel):
    url: str

class VideoDownloadRequest(BaseModel):
    url: str
    platform: str
    quality: str = "best"  # best, 1080, 720, 480
    merge_motion_photo: bool = True  # 是否合并实况照片为Motion Photo格式（抖音）
    apple_live_photo: bool = False  # 是否同时生成Apple Live Photo格式（适用于iPhone）
    rename_strategy: str | None = None  # 文件重名策略 (skip/overwrite/rename)，None则从配置读取

class BatchParseRequest(BaseModel):
    urls: list[str]  # 视频链接列表

class BatchDownloadRequest(BaseModel):
    urls: list[str]  # 视频链接列表
    quality: str = "best"  # best, 1080, 720, 480
    rename_strategy: str | None = None  # 文件重名策略 (skip/overwrite/rename)，None则从配置读取
    merge_motion_photo: bool | None = None  # 是否合并实况照片（None时从配置读取）

class SettingsUpdateRequest(BaseModel):
    general: dict | None = None
    proxy: dict | None = None
    cookie: dict | None = None

class SongInfoRequest(BaseModel):
    url: str  # 单曲链接

class ListDirectoriesRequest(BaseModel):
    path: str = ""


class PickDirectoryRequest(BaseModel):
    initial: str = ""  # 初始选中路径（用户当前输入框里的值）

@app.get("/api/search")
async def api_search(keyword: str = Query(...), count: int = 30):
    songs = await search_all(keyword, limit=count)
    return {
        "songs": [
            {
                "title": s.title,
                "artist": s.artist,
                "album": s.album,
                "platform": s.platform,
                "song_id": s.song_id,
            }
            for s in songs
        ]
    }

@app.post("/api/song-info")
async def api_song_info(req: SongInfoRequest):
    """解析单曲链接，返回歌曲信息"""
    import re
    from downloadkit.platforms import PLATFORM_MAP
    
    url = req.url
    
    # 从URL中提取歌曲ID和平台
    song_id = None
    platform = None
    
    # 网易云单曲链接
    if 'music.163.com' in url:
        platform = 'netease'
        # 匹配 /song?id=xxx 或 /#/song?id=xxx 或 /song/xxx
        m = re.search(r'[?&]id=(\d+)', url)
        if m:
            song_id = m.group(1)
        else:
            m = re.search(r'/song/(\d+)', url)
            if m:
                song_id = m.group(1)
    
    # QQ音乐单曲链接
    elif 'y.qq.com' in url or 'c6.y.qq.com' in url:
        platform = 'qqmusic'
        # 匹配 songDetail/xxx 格式
        m = re.search(r'songDetail/(\w+)', url)
        if m:
            song_id = m.group(1)
        else:
            m = re.search(r'[?&]songmid=(\w+)', url)
            if m:
                song_id = m.group(1)
    
    if not song_id or not platform:
        raise HTTPException(400, "无法识别的单曲链接格式")
    
    # 获取平台实例
    plat = PLATFORM_MAP.get(platform)
    if not plat:
        raise HTTPException(400, f"不支持的平台: {platform}")
    
    try:
        # 构建SongInfo对象
        from downloadkit.platforms.base import SongInfo
        
        # 尝试通过搜索获取完整歌曲信息
        # 首先尝试用歌曲ID构造基础信息
        song = SongInfo(
            title=f"歌曲_{song_id}",  # 默认标题，后续可优化
            artist="未知",
            platform=platform,
            song_id=song_id,
        )
        
        # 尝试通过搜索获取更准确的歌曲信息
        # 如果是网易云，可以用歌曲详情API
        if platform == 'netease':
            try:
                # 尝试获取歌曲详情
                async with httpx.AsyncClient(timeout=15) as client:
                    resp = await client.get(
                        "https://music.163.com/api/song/detail",
                        params={"id": song_id, "ids": f"[{song_id}]"},
                        headers={
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                            "Referer": "https://music.163.com/",
                        }
                    )
                    data = resp.json()
                    if data.get("code") == 200:
                        songs_data = data.get("songs", [])
                        if songs_data:
                            s = songs_data[0]
                            ar = s.get("ar", [{}])
                            al = s.get("al", {})
                            song = SongInfo(
                                title=s.get("name", f"歌曲_{song_id}"),
                                artist="/".join(a.get("name", "") for a in ar if a.get("name")),
                                album=al.get("name", "") if isinstance(al, dict) else "",
                                platform=platform,
                                song_id=song_id,
                                cover=al.get("picUrl", "") if isinstance(al, dict) else "",
                            )
            except Exception:
                pass  # 使用默认信息
        
        return {
            "song": {
                "title": song.title,
                "artist": song.artist,
                "album": song.album,
                "platform": song.platform,
                "song_id": song.song_id,
            }
        }
    except Exception as e:
        raise HTTPException(500, f"解析失败: {str(e)}")

@app.post("/api/download")
async def api_download(req: DownloadRequest):
    from downloadkit.platforms.base import SongInfo
    song = SongInfo(
        title=req.title,
        artist=req.artist,
        platform=req.platform,
        song_id=req.song_id,
    )
    task_id = f"{int(time.time())}_{req.song_id}"
    _downloads[task_id] = {
        "status": "downloading",
        "filename": sanitize_filename(f"{song.title} - {song.artist}.mp3"),
        "url": req.song_id,
        "platform": req.platform
    }

    # 定义下载函数，接收 DownloadTask 参数
    async def _download_func(task: DownloadTask):
        try:
            result = await download_song(song, task_id=task_id)
            
            if result:
                # 更新任务状态
                task.status = TaskStatus.COMPLETED
                task.progress = 1.0
                task.filename = result.name
                
                # 同步到 _downloads 字典
                _downloads[task_id] = {"status": "done", "filename": result.name}
            else:
                task.status = TaskStatus.FAILED
                task.error = "Download failed"
                _downloads[task_id] = {"status": "failed", "error": "Download failed"}
        except CancelException:
            _downloads[task_id] = {"status": "cancelled"}
            raise
        except PauseException:
            _downloads[task_id] = {"status": "paused"}
            raise
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            _downloads[task_id] = {"status": "failed", "error": str(e)}
            raise

    # 通过队列管理任务
    task_title = f"{song.title} - {song.artist}"
    await download_queue.add_task(
        task_id=task_id,
        url=req.song_id,
        platform=req.platform,
        title=task_title,
        download_func=_download_func
    )
    
    return {"task_id": task_id}

@app.get("/api/download/{task_id}")
async def api_download_status(task_id: str):
    info = _downloads.get(task_id)
    if not info:
        raise HTTPException(404, "Task not found")
    return info

@app.get("/api/files")
async def api_files():
    download_dir = get_download_dir()
    files = []
    
    # 分类目录映射
    categories = {
        'music': '音乐',
        'videos': '视频', 
        'images': '图片',
        'animated': '动图'
    }
    
    # 支持的文件扩展名
    media_exts = {'.mp3', '.m4a', '.flac', '.wav', '.ogg', '.webm', '.mp4', '.jpg', '.jpeg', '.png', '.gif', '.webp'}
    
    if download_dir.exists():
        # 扫描分类子目录
        for subdir, label in categories.items():
            subdir_path = download_dir / subdir
            if subdir_path.exists():
                for f in sorted(subdir_path.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                    if f.is_file():
                        files.append({
                            "name": f.name,
                            "path": f"{subdir}/{f.name}",
                            "size": f.stat().st_size,
                            "time": f.stat().st_mtime,
                            "category": subdir,
                            "category_label": label
                        })
        
        # 扫描根目录（未分类文件）
        for f in sorted(download_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.is_file() and f.suffix.lower() in media_exts:
                files.append({
                    "name": f.name,
                    "path": f.name,
                    "size": f.stat().st_size,
                    "time": f.stat().st_mtime,
                    "category": "others",
                    "category_label": "其他"
                })
    
    return {"files": files}

@app.get("/api/download-file/{file_path:path}")
async def api_download_file(file_path: str):
    download_dir = get_download_dir()
    try:
        filepath = safe_download_path(file_path, download_dir, check_exists=True)
    except (PathTraversalError, FileOutsideBaseError) as e:
        raise e
    
    media = get_media_type(filepath)
    return FileResponse(filepath, media_type=media, filename=filepath.name)

@app.delete("/api/files/{file_path:path}")
async def api_delete_file(file_path: str):
    download_dir = get_download_dir()
    try:
        filepath = safe_delete_path(file_path, download_dir)
    except (PathTraversalError, FileOutsideBaseError) as e:
        raise e
    
    filepath.unlink()
    return {"status": "deleted"}

@app.post("/api/files/batch-delete")
async def api_batch_delete(req: BatchDeleteRequest):
    """批量删除文件"""
    download_dir = get_download_dir()
    deleted = []
    errors = []
    
    for file_path in req.files:
        try:
            filepath = safe_delete_path(file_path, download_dir)
            filepath.unlink()
            deleted.append(file_path)
        except PathTraversalError as e:
            errors.append({"path": file_path, "error": "路径遍历攻击被拒绝"})
        except FileOutsideBaseError as e:
            errors.append({"path": file_path, "error": "路径超出允许范围"})
        except HTTPException as e:
            errors.append({"path": file_path, "error": "文件不存在"})
        except Exception as e:
            errors.append({"path": file_path, "error": str(e)})
    
    return {"deleted": deleted, "errors": errors}

def _is_container():
    """检测是否运行在 Docker/LXC 容器中（无 GUI 环境）"""
    if os.path.exists('/.dockerenv'):
        return True
    try:
        with open('/proc/1/cgroup', 'rt') as f:
            return 'docker' in f.read()
    except Exception:
        pass
    # 环境变量显式标记
    if os.environ.get('RUNNING_IN_CONTAINER', '').lower() in ('1', 'true', 'yes'):
        return True
    return False


@app.post("/api/open-dir")
async def api_open_dir(req: OpenDirRequest):
    """打开文件所在目录（容器内返回路径信息由前端弹窗展示）"""
    import platform
    
    download_dir = get_download_dir()
    
    if req.path:
        # 安全验证文件路径
        try:
            filepath = safe_download_path(req.path, download_dir, check_exists=True)
        except (PathTraversalError, FileOutsideBaseError) as e:
            raise e
        dir_path = filepath.parent
    else:
        # 打开下载根目录
        dir_path = download_dir.resolve()
    
    # 确保目录存在
    if not dir_path.exists():
        raise HTTPException(404, "目录不存在")
    
    # ── 容器 / headless 模式：返回路径信息，由前端弹窗展示 ──
    if _is_container():
        rel_path = str(dir_path.relative_to(download_dir)) if dir_path != download_dir else ''
        info = {
            "status": "headless",
            "path": str(dir_path),
            "container_path": str(dir_path),
            "nas_path": os.environ.get('NAS_FILES_PATH', ''),
            "smb_path": os.environ.get('NAS_SMB_PATH', ''),
            "base_url": os.environ.get('NAS_BASE_URL', ''),
            "rel_path": rel_path,
        }
        if info["nas_path"] and rel_path:
            info["nas_path"] = os.path.join(info["nas_path"], rel_path).replace('\\', '/')
        if info["smb_path"] and rel_path:
            info["smb_path"] = os.path.join(info["smb_path"], rel_path).replace('/', '\\')
        return info
    
    # ── 桌面环境：直接调用系统文件管理器 ──
    try:
        if platform.system() == 'Windows':
            subprocess.Popen(['explorer', str(dir_path)])
        elif platform.system() == 'Darwin':
            subprocess.Popen(['open', str(dir_path)])
        else:
            subprocess.Popen(['xdg-open', str(dir_path)])
        return {"status": "opened", "path": str(dir_path)}
    except Exception as e:
        raise HTTPException(500, f"打开目录失败: {str(e)}")

@app.post("/api/utils/list-directories")
async def api_list_directories(req: ListDirectoriesRequest):
    """浏览目录：返回子目录列表"""
    dirs = []
    target = req.path.strip()

    if not target:
        # 返回常用系统目录
        home = Path.home()
        common_dirs = [
            ("Desktop", home / "Desktop"),
            ("Downloads", home / "Downloads"),
            ("Documents", home / "Documents"),
        ]
        for name, p in common_dirs:
            if p.is_dir():
                dirs.append({"name": name, "path": str(p)})

        # 用户主目录
        dirs.append({"name": "~", "path": str(home)})

        # Windows: 扫描所有盘符根目录
        if sys.platform == "win32":
            for letter in range(67, 91):  # C=67 .. Z=90
                drive = Path(f"{chr(letter)}:\\")
                if drive.exists():
                    dirs.append({"name": f"{chr(letter)}:\\", "path": str(drive)})
        else:
            # Unix: 根目录
            dirs.append({"name": "/", "path": "/"})

        # 当前工作目录
        cwd = Path.cwd()
        if any(d["path"] != str(cwd) for d in dirs):
            dirs.append({"name": "cwd", "path": str(cwd)})

        return {"directories": dirs}

    # 验证路径存在且是目录
    p = Path(target).expanduser()
    if not p.is_absolute():
        if getattr(sys, "frozen", False):
            base = Path(sys.executable).parent
        else:
            base = Path.cwd()
        p = (base / p).resolve()
    else:
        p = p.resolve()

    if not p.exists():
        # 路径不存在 → 退回到常用目录，不报错
        home = Path.home()
        dirs = []
        for name in ("Desktop", "Downloads", "Documents"):
            dp = home / name
            if dp.is_dir():
                dirs.append({"name": name, "path": str(dp)})
        dirs.append({"name": "~", "path": str(home)})
        if sys.platform == "win32":
            for letter in range(67, 91):
                drive = Path(f"{chr(letter)}:\\")
                if drive.exists():
                    dirs.append({"name": f"{chr(letter)}:\\", "path": str(drive)})
        else:
            dirs.append({"name": "/", "path": "/"})
        return {"directories": dirs, "fallback": True, "original": target}

    if not p.is_dir():
        raise HTTPException(400, f"不是目录: {target}")

    # 列出子目录
    try:
        entries = sorted(p.iterdir(), key=lambda x: x.name.lower())
    except PermissionError:
        return {"directories": []}

    count = 0
    for entry in entries:
        if count >= 100:
            break
        if entry.name.startswith("."):
            continue
        if not entry.is_dir():
            continue
        # PermissionError guard on is_dir itself
        try:
            if entry.is_dir():
                dirs.append({"name": entry.name, "path": str(entry)})
                count += 1
        except PermissionError:
            continue

    return {"directories": dirs}


@app.post("/api/utils/pick-directory")
async def api_pick_directory(req: PickDirectoryRequest):
    """弹 Windows 原生文件夹选择对话框（FolderBrowserDialog），返回用户选中的路径

    实现方式：subprocess 调 powershell.exe -STA 启动 System.Windows.Forms.FolderBrowserDialog
    - 用户点 [确定]：stdout 输出选中的路径 → 返回 {ok: True, path: "..."}
    - 用户点 [取消]：stdout 为空 → 返回 {ok: False, cancelled: True}
    - 60 秒无响应：自动 kill 进程 → 返回超时错误
    """
    import subprocess
    from pathlib import Path

    # 处理 initial：相对路径展开 + 验证存在（不存在则回退到当前下载根目录）
    initial = (req.initial or "").strip()
    _fallback_dir = get_download_dir()
    if not _fallback_dir.is_dir():
        _fallback_dir = Path.home() / "Downloads"
    if initial:
        p = Path(initial).expanduser()
        if not p.is_absolute():
            if getattr(sys, "frozen", False):
                base = Path(sys.executable).parent
            else:
                base = Path.cwd()
            p = (base / p).resolve()
        if p.is_dir():
            initial = str(p)
        else:
            initial = str(_fallback_dir)
    else:
        initial = str(_fallback_dir)

    # PowerShell 单引号转义（避免注入：' → ''）
    initial_escaped = initial.replace("'", "''")

    # PowerShell 脚本：弹 FolderBrowserDialog，选中后输出路径到 stdout
    ps_script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$dlg = New-Object System.Windows.Forms.FolderBrowserDialog;"
        "$dlg.Description = '请选择下载目录';"
        f"$dlg.SelectedPath = '{initial_escaped}';"
        "$dlg.ShowNewFolderButton = $true;"
        "if ($dlg.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {"
        "  Write-Output $dlg.SelectedPath"
        "}"
    )

    try:
        proc = subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-STA", "-Command", ps_script],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return {"ok": False, "error": "找不到 powershell.exe，请确认系统已安装"}
    except Exception as e:
        return {"ok": False, "error": f"启动 PowerShell 失败：{e}"}

    try:
        stdout, stderr = proc.communicate(timeout=60)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()  # 清空管道
        return {"ok": False, "error": "选择超时（60 秒）"}

    if proc.returncode != 0:
        return {"ok": False, "error": f"PowerShell 异常退出（{proc.returncode}）：{stderr.strip()}"}

    selected = stdout.strip()
    if not selected:
        # 用户点取消
        return {"ok": False, "cancelled": True}

    return {"ok": True, "path": selected}


@app.post("/api/playlist")
async def api_playlist(req: PlaylistRequest):
    try:
        pl = await parse_playlist(req.url)
        return {
            "name": pl.name,
            "platform": pl.platform,
            "song_count": pl.song_count,
            "songs": [
                {
                    "title": s.title,
                    "artist": s.artist,
                    "album": s.album,
                    "platform": s.platform,
                    "song_id": s.song_id,
                }
                for s in pl.songs
            ],
        }
    except ValueError as e:
        raise HTTPException(400, str(e))

# --- 歌单收藏 endpoints ---
from downloadkit.collection import (
    list_collections as _list_collections,
    get_collection as _get_collection,
    create_collection as _create_collection,
    update_collection as _update_collection,
    delete_collection as _delete_collection,
    refresh_collection as _refresh_collection,
)

class CreateCollectionRequest(BaseModel):
    url: str
    name: str = ""

class UpdateCollectionRequest(BaseModel):
    name: str | None = None


@app.get("/api/collections")
async def api_collections_list():
    """获取所有收藏歌单列表"""
    return _list_collections()


@app.post("/api/collections")
async def api_collections_create(req: CreateCollectionRequest):
    """添加收藏歌单"""
    try:
        return _create_collection(url=req.url, name=req.name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/collections/{collection_id}")
async def api_collections_get(collection_id: int):
    """获取收藏歌单详情（含缓存曲目）"""
    result = _get_collection(collection_id)
    if not result:
        raise HTTPException(404, "收藏歌单不存在")
    return result


@app.put("/api/collections/{collection_id}")
async def api_collections_update(collection_id: int, req: UpdateCollectionRequest):
    """更新收藏歌单信息"""
    kwargs = {}
    if req.name is not None:
        kwargs["name"] = req.name
    result = _update_collection(collection_id, **kwargs)
    if not result:
        raise HTTPException(404, "收藏歌单不存在")
    return result


@app.delete("/api/collections/{collection_id}")
async def api_collections_delete(collection_id: int):
    """删除收藏歌单"""
    ok = _delete_collection(collection_id)
    if not ok:
        raise HTTPException(404, "收藏歌单不存在")
    return {"status": "deleted"}


@app.post("/api/collections/{collection_id}/refresh")
async def api_collections_refresh(collection_id: int):
    """刷新收藏歌单"""
    try:
        result = _refresh_collection(collection_id)
        if not result:
            raise HTTPException(404, "收藏歌单不存在")
        song_count = len(result.get("tracks", []))
        return {
            "collection": result,
            "status": "ok",
            "message": f"刷新成功，共 {song_count} 首歌曲",
        }
    except ValueError as e:
        raise HTTPException(400, str(e))


# --- Douyin endpoints ---
# --- 统一视频解析接口 ---
def detect_platform(url: str) -> str:
    """检测链接平台"""
    if 'douyin.com' in url or 'tiktok.com' in url:
        return 'douyin'
    elif 'bilibili.com' in url or 'b23.tv' in url:
        return 'bilibili'
    elif 'youtube.com' in url or 'youtu.be' in url:
        return 'youtube'
    elif 'xiaohongshu.com' in url or 'xhslink.com' in url:
        return 'xiaohongshu'
    else:
        return None


@app.post("/api/video/parse")
async def api_video_parse(req: VideoParseRequest):
    """统一视频解析接口"""
    url = req.url
    platform = detect_platform(url)
    
    if not platform:
        raise HTTPException(400, "不支持的平台链接")
    
    try:
        if platform == 'douyin':
            content = await fetch_content(url)
            # 实况照片：从 motion_photo_pairs 提取全部配对数据
            live_video_urls = []
            live_images = []
            if content.content_type == ContentType.ANIMATED and content.motion_photo_pairs:
                for pair in content.motion_photo_pairs:
                    live_images.append({
                        "url": pair.image.url,
                        "video_url": pair.video.url
                    })
                    live_video_urls.append(pair.video.url)
            else:
                live_images = [{"url": img.url} for img in content.images] if content.images else []
            
            ret = {
                "platform": "douyin",
                "title": content.title,
                "author": content.author,
                "cover": content.cover,
                "content_type": content.content_type.value,
                "video_url": content.video_url or (live_video_urls[0] if live_video_urls else None),
                "video_urls": live_video_urls or None,
                "images": live_images,
            }
            logger.info(f"[Parse] type={content.content_type.value}, video_url={str(ret['video_url'])[:100] if ret['video_url'] else 'None'}")
            return ret
        
        elif platform == 'bilibili':
            video = await parse_bilibili(url)
            return {
                "platform": "bilibili",
                "title": video.title,
                "author": video.author,
                "cover": video.cover,
                "content_type": "video",
                "duration": video.duration,
                "quality": video.quality,
            }
        
        elif platform == 'youtube':
            video = await parse_youtube(url)
            return {
                "platform": "youtube",
                "title": video.title,
                "author": video.author,
                "cover": video.cover,
                "content_type": "video",
                "duration": video.duration,
            }
        
        elif platform == 'xiaohongshu':
            content = await parse_xiaohongshu(url)
            return {
                "platform": "xiaohongshu",
                "title": content.title,
                "author": content.author,
                "cover": content.cover,
                "content_type": content.content_type.value,
                "video_url": content.video_url,
                "images": [{"url": url} for url in content.images],
            }
    
    except Exception as e:
        raise HTTPException(400, f"解析失败: {str(e)}")


@app.post("/api/video/download")
async def api_video_download(req: VideoDownloadRequest):
    """统一视频下载接口"""
    url = req.url
    platform = req.platform or detect_platform(url)
    
    if not platform:
        raise HTTPException(400, "不支持的平台链接")
    
    task_id = f"video_{platform}_{int(time.time())}_{id(req)}"
    _downloads[task_id] = {"status": "downloading", "filename": "", "files": []}
    
    # 定义下载函数，接收 DownloadTask 参数
    async def _download_func(task: DownloadTask):
        try:
            # 确定文件重名策略
            rename_strategy = req.rename_strategy
            if rename_strategy is None:
                cfg = load_config()
                rename_strategy = cfg.get('general', {}).get('rename_strategy', 'skip')

            if platform == 'douyin':
                content = await fetch_content(url)
                filepaths = await download_content(
                    content, get_download_dir(),
                    merge_motion_photo=req.merge_motion_photo,
                    apple_live_photo=req.apple_live_photo,
                    task_id=task_id,
                    rename_strategy=rename_strategy
                )
                filenames = [fp.name for fp in filepaths]
            
            elif platform == 'bilibili':
                video = await parse_bilibili(url)
                filepath = await download_bilibili_video(video, get_download_subdir('videos'), task_id=task_id, rename_strategy=rename_strategy)
                filenames = [filepath.name]
            
            elif platform == 'youtube':
                video = await parse_youtube(url)
                filepath = await download_youtube_video(video, get_download_subdir('videos'), req.quality, task_id=task_id, rename_strategy=rename_strategy)
                filenames = [filepath.name]
            
            elif platform == 'xiaohongshu':
                content = await parse_xiaohongshu(url)
                filepaths = await download_xhs_content(content, get_download_dir(), task_id=task_id, rename_strategy=rename_strategy)
                filenames = [fp.name for fp in filepaths]
            
            else:
                raise ValueError("不支持的平台")
            
            # 更新任务状态
            task.status = TaskStatus.COMPLETED
            task.progress = 1.0
            task.filename = filenames[0] if filenames else ""
            
            # 同步到 _downloads 字典
            _downloads[task_id] = {
                "status": "done",
                "filename": filenames[0] if filenames else "",
                "files": filenames
            }
            
            # 记录下载历史
            try:
                # 获取文件大小
                total_size = 0
                for fn in filenames:
                    # 根据平台确定文件路径
                    if platform == 'douyin':
                        # 动图文件在animated目录，视频在videos目录
                        for subdir in ['animated', 'videos', 'images']:
                            fpath = get_download_subdir(subdir) / fn
                            if fpath.exists():
                                total_size += fpath.stat().st_size
                                break
                    else:
                        fpath = get_download_subdir('videos') / fn
                        if fpath.exists():
                            total_size += fpath.stat().st_size
                
                # 提取标题
                title = filenames[0] if filenames else "未知"
                # 清理文件名中的扩展名和ID前缀
                import re
                title = re.sub(r'^douyin_\d+_', '', title)
                title = re.sub(r'\.(mp4|jpg|png)$', '', title)
                title = title.replace('_motion_', ' 实况照片 ')
                
                download_history.add_record(
                    url=url,
                    platform=platform,
                    title=title,
                    author="",
                    cover="",
                    file_path=filenames[0] if filenames else "",
                    file_size=total_size
                )
            except Exception as e:
                logger.warning(f"[History] 记录下载历史失败: {e}")
        
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            _downloads[task_id] = {"status": "failed", "error": str(e)}
            raise
    
    # 通过队列管理任务
    task_title = f"{platform} - {url[:50]}..."
    await download_queue.add_task(
        task_id=task_id,
        url=url,
        platform=platform,
        title=task_title,
        download_func=_download_func
    )
    
    return {"task_id": task_id}


@app.get("/api/debug/last-parse")
async def debug_last_parse():
    """返回最近一次解析结果（调试用）"""
    from downloadkit.douyin import _last_parse_result
    if not _last_parse_result:
        return {"error": "无解析记录"}
    return _last_parse_result


@app.get("/api/media/proxy")
async def media_proxy(request: Request, url: str = Query(...), video_url: str = Query(None)):
    """代理获取媒体资源（透传Range头 + 全量缓冲）
    
    浏览器播放视频用 Range 分片请求（206 Partial Content），
    服务端需原样透传 Range/状态码/Content-Range/Content-Length。
    这里使用 client.get() 全量缓冲（Douyin 视频 5-20MB 内存足够）。

    抖音：
    - 前端传入 video_url → 直连快速路径，不重新解析
    - 只传分享链接 → 重新解析获取最新地址（刷新路径）
    - 解析结果接受 VIDEO 和 ANIMATED（实况视频）两种类型
    """
    if not url.startswith(('http://', 'https://')):
        raise HTTPException(400, "不支持的URL协议")
    
    # 快速路径：前端传了已解析的视频URL，直接使用
    if video_url:
        url = video_url
        logger.info(f"[Proxy] 快速路径：使用前端传入的视频地址: {url[:120]}...")
    # 刷新路径：只有分享链接，重新解析获取最新视频地址
    elif "douyin" in url.lower():
        try:
            from downloadkit.douyin import fetch_content, ContentType
            logger.info(f"[Proxy] 刷新路径：重新解析抖音分享链接...")
            content = await fetch_content(url)
            if content and content.video_url and content.content_type in (ContentType.VIDEO, ContentType.ANIMATED):
                url = content.video_url
                logger.info(f"[Proxy] 解析到最新视频地址: {url[:120]}...")
            else:
                logger.warning(f"[Proxy] 解析结果没有可用视频: type={content.content_type if content else 'None'}, video_url={bool(content and content.video_url)}")
        except Exception as e:
            logger.exception(f"[Proxy] 重新解析失败")
            # fall through，仍尝试用原始 URL 请求
    
    # 透传浏览器 Range 头，且对抖音 CDN 加上鉴权 Referer
    proxy_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    }
    url_lower = url.lower()
    if any(d in url_lower for d in ("douyin", "snssdk", "toutiao", "pstatp", "ixigua")):
        proxy_headers["Referer"] = "https://www.douyin.com/"
    range_header = request.headers.get("range")
    if range_header:
        proxy_headers["Range"] = range_header
    
    logger.info(f"[Proxy] 请求最终URL: {url[:120]}... Range: {range_header or '无'}")
    
    try:
        async with httpx.AsyncClient(timeout=120, follow_redirects=True, headers=proxy_headers) as client:
            resp = await client.get(url)
            logger.info(f"[Proxy] 响应: {resp.status_code}, Type: {resp.headers.get('content-type','?')}, Len: {resp.headers.get('content-length','?')}, Body: {len(resp.content)} bytes")
            
            media_type = resp.headers.get("content-type", "video/mp4")
            
            # 构建响应头
            resp_headers = {"accept-ranges": "bytes"}
            for h in ("content-range", "content-length"):
                v = resp.headers.get(h)
                if v:
                    resp_headers[h] = v
            if "content-length" not in resp_headers:
                resp_headers["content-length"] = str(len(resp.content))
            
            return Response(
                content=resp.content,
                status_code=resp.status_code,
                media_type=media_type,
                headers=resp_headers,
            )
    except httpx.TimeoutException:
        raise HTTPException(504, "代理请求超时")
    except httpx.HTTPStatusError as e:
        raise HTTPException(502, f"源站返回错误: {e.response.status_code}")
    except Exception as e:
        logger.exception(f"[Proxy] 代理请求失败: {url[:80]}...")
        raise HTTPException(502, f"代理请求失败: {str(e)}")


@app.get("/api/video/{task_id}")
async def api_video_status(task_id: str):
    """查询视频下载状态"""
    info = _downloads.get(task_id)
    if not info:
        raise HTTPException(404, "Task not found")
    return info


# --- 批量解析下载接口 ---
@app.post("/api/video/batch-parse")
async def api_batch_parse(req: BatchParseRequest):
    """
    批量解析视频链接
    
    请求:
    {
        "urls": [
            "https://www.bilibili.com/video/BV1xx...",
            "https://www.youtube.com/watch?v=xxx"
        ]
    }
    """
    results = []
    
    for url in req.urls:
        url = url.strip()
        if not url:
            continue
        
        try:
            platform = detect_platform(url)
            if not platform:
                results.append({
                    "url": url,
                    "status": "failed",
                    "error": "不支持的平台"
                })
                continue
            
            # 解析视频
            if platform == 'douyin':
                content = await fetch_content(url)
                results.append({
                    "url": url,
                    "platform": platform,
                    "title": content.title,
                    "author": content.author,
                    "cover": content.cover,
                    "content_type": content.content_type.value,
                    "status": "success"
                })
            
            elif platform == 'bilibili':
                video = await parse_bilibili(url)
                results.append({
                    "url": url,
                    "platform": platform,
                    "title": video.title,
                    "author": video.author,
                    "cover": video.cover,
                    "content_type": "video",
                    "duration": video.duration,
                    "quality": video.quality,
                    "status": "success"
                })
            
            elif platform == 'youtube':
                video = await parse_youtube(url)
                results.append({
                    "url": url,
                    "platform": platform,
                    "title": video.title,
                    "author": video.author,
                    "cover": video.cover,
                    "content_type": "video",
                    "duration": video.duration,
                    "status": "success"
                })
            
            elif platform == 'xiaohongshu':
                content = await parse_xiaohongshu(url)
                results.append({
                    "url": url,
                    "platform": platform,
                    "title": content.title,
                    "author": content.author,
                    "cover": content.cover,
                    "content_type": content.content_type.value,
                    "status": "success"
                })
            
            else:
                results.append({
                    "url": url,
                    "status": "failed",
                    "error": "未实现的平台"
                })
        
        except Exception as e:
            results.append({
                "url": url,
                "status": "failed",
                "error": str(e)
            })
    
    return {"results": results}


@app.post("/api/video/batch-download")
async def api_batch_download(req: BatchDownloadRequest):
    """
    批量下载视频
    
    请求:
    {
        "urls": ["https://...", "https://..."],
        "quality": "best"
    }
    """
    task_id = f"batch_{int(time.time())}"
    _downloads[task_id] = {
        "status": "downloading",
        "type": "batch",
        "total": len(req.urls),
        "completed": 0,
        "failed": 0,
        "files": []
    }
    
    # 定义下载函数，接收 DownloadTask 参数
    async def _download_func(task: DownloadTask):
        try:
            # 确定文件重名策略
            rename_strategy = req.rename_strategy
            if rename_strategy is None:
                cfg = load_config()
                rename_strategy = cfg.get('general', {}).get('rename_strategy', 'skip')

            for url in req.urls:
                url = url.strip()
                if not url:
                    continue
                
                try:
                    platform = detect_platform(url)
                    
                    if platform == 'douyin':
                        content = await fetch_content(url)
                        filepaths = await download_content(content, get_download_dir(), merge_motion_photo=req.merge_motion_photo, task_id=task_id, rename_strategy=rename_strategy)
                        _downloads[task_id]["files"].extend([fp.name for fp in filepaths])
                    
                    elif platform == 'bilibili':
                        video = await parse_bilibili(url)
                        filepath = await download_bilibili_video(video, get_download_subdir('videos'), task_id=task_id, rename_strategy=rename_strategy)
                        _downloads[task_id]["files"].append(filepath.name)
                    
                    elif platform == 'youtube':
                        video = await parse_youtube(url)
                        filepath = await download_youtube_video(video, get_download_subdir('videos'), req.quality, task_id=task_id, rename_strategy=rename_strategy)
                        _downloads[task_id]["files"].append(filepath.name)
                    
                    elif platform == 'xiaohongshu':
                        content = await parse_xiaohongshu(url)
                        filepaths = await download_xhs_content(content, get_download_dir(), task_id=task_id, rename_strategy=rename_strategy)
                        _downloads[task_id]["files"].extend([fp.name for fp in filepaths])
                    
                    else:
                        raise ValueError(f"不支持的平台: {platform}")
                    
                    _downloads[task_id]["completed"] += 1
                
                except Exception as e:
                    _downloads[task_id]["failed"] += 1
                    logger.error(f"[Batch] 下载失败 {url}: {e}")
            
            # 更新任务状态
            task.status = TaskStatus.COMPLETED
            task.progress = 1.0
            _downloads[task_id]["status"] = "done"
        
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            _downloads[task_id]["status"] = "failed"
            raise
    
    # 通过队列管理任务
    task_title = f"批量下载 {len(req.urls)} 个视频"
    await download_queue.add_task(
        task_id=task_id,
        url=req.urls[0] if req.urls else "",
        platform="batch",
        title=task_title,
        download_func=_download_func
    )
    
    return {"task_id": task_id}


@app.get("/api/video/batch/{task_id}")
async def api_batch_status(task_id: str):
    """查询批量下载状态"""
    info = _downloads.get(task_id)
    if not info:
        raise HTTPException(404, "Task not found")
    return info


# --- 下载队列API ---
@app.get("/api/queue/status")
async def api_queue_status():
    """获取下载队列状态"""
    # 获取download_queue的状态
    queue_status = download_queue.get_queue_status()
    
    # 将_downloads中的任务也加入到队列状态中
    for task_id, info in _downloads.items():
        # 检查是否已经在queue_status中
        existing = [t for t in queue_status["tasks"] if t["task_id"] == task_id]
        if not existing:
            # 状态映射（包含暂停和取消状态）
            status_map = {
                "downloading": "downloading",
                "done": "completed",
                "failed": "failed",
                "paused": "paused",
                "cancelled": "cancelled"
            }
            status = status_map.get(info.get("status", ""), "pending")
            
            task_info = {
                "task_id": task_id,
                "title": info.get("filename", "").replace(".mp3", "").replace(".mp4", ""),
                "platform": "douyin" if "video_douyin" in task_id else "music",
                "status": status,
                "progress": 1.0 if status == "completed" else 0.0,
                "filename": info.get("filename", ""),
                "file_size": 0,
                "downloaded_size": 0,
                "error": info.get("error", "")
            }
            queue_status["tasks"].append(task_info)
            
            # 更新统计
            if status == "downloading":
                queue_status["downloading"] += 1
            elif status == "completed":
                queue_status["completed"] += 1
            elif status == "failed":
                queue_status["failed"] += 1
            elif status == "paused":
                queue_status["paused"] = queue_status.get("paused", 0) + 1
    
    return queue_status


@app.post("/api/queue/{task_id}/pause")
async def api_pause_download(task_id: str):
    """暂停下载"""
    download_queue.pause_task(task_id)
    # 同时更新 _downloads 状态
    if task_id in _downloads:
        _downloads[task_id]["status"] = "paused"
    return {"status": "paused"}


@app.post("/api/queue/{task_id}/resume")
async def api_resume_download(task_id: str):
    """恢复下载"""
    download_queue.resume_task(task_id)
    # 同时更新 _downloads 状态
    if task_id in _downloads:
        _downloads[task_id]["status"] = "downloading"
    return {"status": "resumed"}


@app.post("/api/queue/{task_id}/cancel")
async def api_cancel_download(task_id: str):
    """取消下载"""
    download_queue.cancel_task(task_id)
    # 同时更新 _downloads 状态
    if task_id in _downloads:
        _downloads[task_id]["status"] = "cancelled"
    return {"status": "cancelled"}


@app.post("/api/queue/{task_id}/retry")
async def api_retry_download(task_id: str):
    """重试失败的下载"""
    # 先尝试通过队列重试
    result = await download_queue.retry_task(task_id)
    if result:
        # 重置 _downloads 状态
        if task_id in _downloads:
            _downloads[task_id]["status"] = "downloading"
            _downloads[task_id].pop("error", None)
        return {"status": "retried"}
    
    # 如果队列中没有，检查 _downloads 中是否有此任务
    if task_id in _downloads:
        task_info = _downloads[task_id]
        if task_info.get("status") == "failed":
            # 重新创建下载任务
            url = task_info.get("url", "")
            platform = task_info.get("platform", "")
            if url and platform:
                # 重新发起下载请求
                new_req = VideoDownloadRequest(url=url, platform=platform)
                result = await api_video_download(new_req)
                return {"status": "retried", "new_task_id": result["task_id"]}
    
    raise HTTPException(400, "无法重试此任务")


@app.post("/api/queue/retry-failed")
async def api_retry_failed():
    """一键重试所有失败任务（P3-2）。

    只重试 download_queue 里还存在的 FAILED 任务（失败后约 5 分钟内，
    超时会被清理循环移出）。_downloads 里的孤儿 failed 卡不在此列：
    视频条目不存原链接无从重发，音乐条目存的 url 是 song_id、走视频
    接口必然立刻再失败 —— 硬发只会批量制造新的失败任务。
    所以把这类如实统计成 orphaned 报给前端，由它向用户说明白。

    Returns:
        {status, retried: 实际重新入队数, orphaned: 过期无法重试的失败卡数}
    """
    retried = 0
    for task_id in list(download_queue.active_tasks.keys()):
        # retry_task 内部只放行 FAILED，其余状态返回 False 自动跳过
        if await download_queue.retry_task(task_id):
            retried += 1
            if task_id in _downloads:
                _downloads[task_id]["status"] = "downloading"
                _downloads[task_id].pop("error", None)

    orphaned = sum(
        1 for task_id, info in _downloads.items()
        if info.get("status") == "failed"
        and task_id not in download_queue.active_tasks
    )
    return {"status": "ok", "retried": retried, "orphaned": orphaned}


# ========== 设置接口 ==========

@app.get("/api/settings/get")
async def api_settings_get():
    """获取当前配置。

    附带 proxy_system：系统代理探测结果（读注册表/环境变量，很快）。
    前端「跟随系统」态要回显「当前系统代理是什么」，不然用户看不到
    生效值，等于三态里有一态是黑盒。
    """
    from downloadkit.proxy import get_system_proxy
    try:
        system_proxy = get_system_proxy() or ""
    except Exception:
        system_proxy = ""
    return {"settings": load_config(), "proxy_system": system_proxy}


class ProxyTestRequest(BaseModel):
    proxy: str = ""   # 要测的代理地址；空 = 测直连
    url: str = ""     # 目标地址；空 = 用内置默认


@app.post("/api/proxy/test")
async def api_proxy_test(req: ProxyTestRequest):
    """测一个代理（或直连）的可用性与延迟（P3-1）。

    永远返回 200，可用性放在 body 的 ok 字段里 —— 「代理不通」是
    测试结果不是服务故障，抛 4xx/5xx 会让前端把两种情况混为一谈。

    Returns:
        {ok, latency_ms, message}，message 是给用户看的中文结论
    """
    target = (req.url or "").strip() or "http://www.baidu.com"
    proxy = (req.proxy or "").strip() or None
    timeout = 10.0
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(
            proxy=proxy, timeout=timeout, follow_redirects=True,
        ) as client:
            resp = await client.get(target)
        ms = int((time.monotonic() - t0) * 1000)
        if resp.status_code < 400:
            msg = f"连接成功（HTTP {resp.status_code}），延迟 {ms} ms"
        else:
            msg = f"对端返回 HTTP {resp.status_code}，延迟 {ms} ms"
        return {"ok": resp.status_code < 400, "latency_ms": ms, "message": msg}
    except httpx.TimeoutException:
        ms = int((time.monotonic() - t0) * 1000)
        return {
            "ok": False, "latency_ms": ms,
            "message": f"连接超时（{int(timeout)} 秒无响应），代理地址或端口可能不对",
        }
    except httpx.ConnectError as e:
        # 连不上要分代理/直连说：前者九成是地址端口错或代理软件没开，
        # 后者是网络本身不通 —— 混成一句英文原文用户没法照着排查
        ms = int((time.monotonic() - t0) * 1000)
        if proxy:
            msg = f"连不上代理（{e}）—— 地址/端口可能不对，或代理软件没开"
        else:
            msg = f"网络不通（{e}）"
        return {"ok": False, "latency_ms": ms, "message": msg}
    except Exception as e:
        ms = int((time.monotonic() - t0) * 1000)
        return {"ok": False, "latency_ms": ms, "message": f"连接失败：{e}"}


@app.get("/api/settings/download-dir-info")
async def api_settings_download_dir_info(path: str = Query("")):
    """获取下载目录信息（实际解析后的绝对路径、是否存在、是否可写）

    Query:
        path: 用户输入的路径（空字符串表示当前配置值）
    """
    if not path or not path.strip():
        # 用当前配置值
        cfg = load_config()
        path = (cfg.get("general", {}) or {}).get("download_dir", "./downloads")

    result = validate_download_dir(path)
    result["input"] = path
    return result


class CookieLoadFromBrowserRequest(BaseModel):
    platform: str  # "douyin" / "bilibili" / "xhs" / "youtube"
    browser: str = "edge"  # "edge" / "chrome" / "firefox"


# ------------------------------------------------------------------
# 开机自启动
# ------------------------------------------------------------------
# 与 /api/settings/update 的区别：那个写 config.toml（应用自己的配置），
# 这个写 HKCU\...\Run（系统状态，决定登录时谁被拉起来）。
# 所以它是独立端点，不塞进 general 段里，也不跟着「保存」按钮一起提交 ——
# 用户勾完就该立即生效，攒着不保存会让人以为开关没反应。


@app.get("/api/settings/autostart")
async def api_settings_autostart_get():
    """查询开机自启动状态。

    源码运行时返回 available=False（没有可自启的程序），
    前端据此禁用开关并显示原因，而不是让用户点了没反应。
    """
    from downloadkit import autostart
    return autostart.get_status()


class AutostartSetRequest(BaseModel):
    enabled: bool


@app.post("/api/settings/autostart")
async def api_settings_autostart_set(req: AutostartSetRequest):
    """开启/关闭开机自启动（写/删 HKCU\\Software\\...\\Run\\DownloadKit）"""
    from downloadkit import autostart
    res = autostart.set_enabled(req.enabled)
    if not res.get("ok", True):
        raise HTTPException(400, res.get("message") or "设置开机启动失败")
    return res


# ------------------------------------------------------------------
# 抖音登录（订阅功能的前置条件）
# ------------------------------------------------------------------
# 与上面 /api/cookies/* 的区别：
#   /api/cookies/*        老方案，把 cookie 字符串存进配置文件，脆弱且要手动维护
#   /api/douyin/login/*   新方案，直接用 Playwright 的持久化 profile，
#                         用户扫一次码就长期有效，之后完全不用管 cookie
#
# 限制：登录窗口和下载共用同一个浏览器 profile，Chromium 独占目录，
#       所以有下载任务在跑时不允许登录（后端返回 409 并说明原因）


class DouyinLoginStartRequest(BaseModel):
    timeout: int = 300  # 等待扫码的最长秒数


@app.get("/api/douyin/login/status")
async def api_douyin_login_status():
    """查询抖音登录态（只读 cookie，<100ms，可放心高频调用）"""
    from downloadkit.douyin import douyin_login_status
    try:
        return await douyin_login_status()
    except Exception as e:
        raise HTTPException(500, f"查询登录态失败：{e}")


@app.post("/api/douyin/login/start")
async def api_douyin_login_start(req: DouyinLoginStartRequest):
    """启动抖音扫码登录

    会弹出一个 Chromium 窗口让用户扫码。本接口立即返回，
    前端用 /api/douyin/login/status 轮询进度。
    """
    from downloadkit.douyin import douyin_start_login
    try:
        result = await douyin_start_login(timeout=req.timeout)
    except Exception as e:
        raise HTTPException(500, f"启动登录失败：{e}")

    # ok=False 是业务性拒绝（如下载中），用 409 让前端能区分「失败」和「被拒」
    if not result.get("ok"):
        return JSONResponse(status_code=409, content=result)
    return result


@app.post("/api/douyin/login/cancel")
async def api_douyin_login_cancel():
    """取消正在进行的登录流程"""
    from downloadkit.douyin import douyin_cancel_login
    try:
        return await douyin_cancel_login()
    except Exception as e:
        raise HTTPException(500, f"取消登录失败：{e}")


@app.post("/api/douyin/logout")
async def api_douyin_logout():
    """退出抖音登录"""
    from downloadkit.douyin import douyin_logout
    try:
        result = await douyin_logout()
    except Exception as e:
        raise HTTPException(500, f"退出登录失败：{e}")
    if not result.get("ok"):
        return JSONResponse(status_code=409, content=result)
    return result


# ------------------------------------------------------------------
# 创作者订阅
# ------------------------------------------------------------------
# 这是产品的核心能力：订阅抖音创作者，自动发现并下载新作品。
#
# 依赖链：
#   登录（/api/douyin/login/*）→ 订阅本组接口 → 增量下载（A4，已实现：
#   subscription_service.check_creator 用水位线只捡基线之后的新作品）
#   → 自动轮询（A5，downloadkit/poller.py）
# 抓创作者主页必须登录，未登录时返回 401 + 可读的提示文案，
# 而不是 500（这是正常业务状态，不是故障）。
#
# 去重在 subscription.filter_new_works() 里做，
# 本层不重复实现判重逻辑。


class AddSubscriptionRequest(BaseModel):
    url: str
    fetch_profile: bool = True   # False = 只存 ID，不抓昵称头像（省一次页面加载）


class ToggleSubscriptionRequest(BaseModel):
    enabled: bool


@app.get("/api/subscriptions")
async def api_subscriptions_list():
    """列出全部订阅的创作者 + 总览统计"""
    from downloadkit.subscription_service import list_subscriptions
    try:
        return await list_subscriptions()
    except Exception as e:
        raise HTTPException(500, f"读取订阅列表失败：{e}")


@app.post("/api/subscriptions")
async def api_subscriptions_add(req: AddSubscriptionRequest):
    """订阅一个创作者

    传主页链接、短链或 sec_uid 都行。
    未登录抖音时返回 401，提示去设置页登录。
    """
    from downloadkit.douyin_browser import RateLimited
    from downloadkit.subscription_service import (
        LoginRequired, add_subscription,
    )
    try:
        rec = await add_subscription(req.url, fetch_profile=req.fetch_profile)
    except LoginRequired as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": str(e)})
    except RateLimited as e:
        # 短链撞上验证码中间页：429 让前端原样展示，用户等窗口过
        # 或直接贴主页链接（主页不走短链域，不受这个限流影响）
        return JSONResponse(status_code=429, content={"ok": False, "error": str(e)})
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"添加订阅失败: {e}", exc_info=True)
        raise HTTPException(500, f"添加订阅失败：{e}")
    return {"ok": True, "creator": rec}


@app.delete("/api/subscriptions/{sec_uid}")
async def api_subscriptions_remove(sec_uid: str):
    """取消订阅。已发现的作品记录保留，重新加回不会重复下载。"""
    from downloadkit.subscription_service import remove_subscription
    try:
        ok = await remove_subscription(sec_uid)
    except Exception as e:
        raise HTTPException(500, f"取消订阅失败：{e}")
    if not ok:
        raise HTTPException(404, "没有订阅这个创作者")
    return {"ok": True}


@app.post("/api/subscriptions/{sec_uid}/toggle")
async def api_subscriptions_toggle(sec_uid: str, req: ToggleSubscriptionRequest):
    """暂停 / 恢复某个创作者的轮询"""
    from downloadkit.subscription_service import toggle_subscription
    try:
        return {"ok": True, "creator": await toggle_subscription(sec_uid, req.enabled)}
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"操作失败：{e}")


# ---------------- 下载范围（P2-1） ----------------

class ScopeSubscriptionRequest(BaseModel):
    scope: str                      # only_new / backfill_n / all
    param: str = ""                 # 仅 backfill_n 用的 N


@app.post("/api/subscriptions/{sec_uid}/scope")
async def api_subscriptions_scope(sec_uid: str, req: ScopeSubscriptionRequest):
    """设置某创作者的下载范围

    改完下次检查生效，不会立刻开任务。取值非法返回 400，
    创作者不存在返回 404 —— 都是业务状态，不抛 500。
    """
    from downloadkit.subscription_service import update_scope
    try:
        rec = await update_scope(sec_uid, req.scope, req.param)
    except ValueError as e:
        # 「没有订阅这个创作者」和「取值非法」都是 ValueError，
        # 按文案区分状态码太脆，这里统一 400 并把原因讲清楚
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"设置下载范围失败：{e}")
    return {"ok": True, "creator": rec}


# ---------------- 自动轮询（A5） ----------------
#
# ⚠ 必须注册在下面的 `/api/subscriptions/{sec_uid}` **之前**。
#   FastAPI 按注册顺序匹配，放后面的话 GET /poller 会被 `{sec_uid}`
#   这个路径参数先吃掉，返回 404「没有订阅这个创作者」（实测踩过）。
#   所有不带路径参数的静态子路由都要排在参数化路由前面。

class PollerConfigRequest(BaseModel):
    """轮询配置，None = 不改"""
    enabled: Optional[bool] = None
    mode: Optional[str] = None            # interval | daily_at（P2-2 双模式）
    daily_at: Optional[str] = None        # "HH:MM"，仅 daily_at 模式用
    interval_minutes: Optional[int] = None
    max_new_per_check: Optional[int] = None
    jitter_percent: Optional[int] = None


@app.get("/api/subscriptions/poller")
async def api_subscriptions_poller():
    """轮询状态（开关、下次执行时间、退避情况、上轮结果）"""
    from downloadkit import poller
    try:
        return poller.status()
    except Exception as e:
        logger.error(f"读取轮询状态失败: {e}", exc_info=True)
        raise HTTPException(500, f"读取失败：{e}")


@app.post("/api/subscriptions/poller")
async def api_subscriptions_poller_config(req: PollerConfigRequest):
    """开关/调整自动轮询。只更新传入的字段"""
    from downloadkit import poller
    try:
        # 先关再开要重置状态，避免「关掉再打开」还卡在旧的退避里
        before = poller.load_settings().get("enabled")
        settings = poller.save_settings(
            enabled=req.enabled,
            mode=req.mode,
            daily_at=req.daily_at,
            interval_minutes=req.interval_minutes,
            max_new_per_check=req.max_new_per_check,
            jitter_percent=req.jitter_percent,
        )
        after = settings.get("enabled")
        if before is False and after is True:
            poller.reset_for_enable()
        return {"status": "ok", "settings": settings, "poller": poller.status()}
    except Exception as e:
        logger.error(f"更新轮询配置失败: {e}", exc_info=True)
        raise HTTPException(500, f"更新失败：{e}")


@app.get("/api/subscriptions/{sec_uid}")
async def api_subscriptions_detail(sec_uid: str, limit: int = 50):
    """单个创作者详情 + 已发现的作品列表"""
    from downloadkit.subscription_service import get_creator_detail
    try:
        return await get_creator_detail(sec_uid, limit=limit)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, f"读取详情失败：{e}")


class PreviewCreatorRequest(BaseModel):
    url: str
    max_scrolls: int = 3


class CheckCreatorRequest(BaseModel):
    download: bool = True       # False = 只检测不入队
    max_new: int = 3            # 本次最多入队几个，0 = 不限制
    max_scrolls: int = 3


@app.post("/api/subscriptions/{sec_uid}/check")
async def api_subscriptions_check(sec_uid: str, req: CheckCreatorRequest):
    """检查单个创作者有没有新作品

    ⚠ 首次检查只建立基线：把现有作品全部标记为「已见」但一个都不下载。
      之后只下载基线之后新增的作品。这是订阅功能的默认语义，
      不是临时限制——订阅一个 500 视频的博主不该把 500 个全下下来。
    """
    from downloadkit import subscription as store
    from downloadkit.subscription_service import (
        LoginRequired, RateLimited, check_creator,
    )
    try:
        return await check_creator(
            sec_uid,
            download=req.download,
            max_new=req.max_new,
            max_scrolls=req.max_scrolls,
        )
    except RateLimited as e:
        # 抖音触发风控，让前端提示「稍后再试」而不是当成 500 故障
        store.mark_creator_result(sec_uid, f"失败：{e}")
        return JSONResponse(status_code=429, content={"ok": False, "error": str(e)})
    except LoginRequired as e:
        store.mark_creator_result(sec_uid, f"失败：{e}")
        return JSONResponse(status_code=401, content={"ok": False, "error": str(e)})
    except ValueError as e:
        # 404「没有订阅」也走到 mark，函数对不存在的行静默返回 False
        store.mark_creator_result(sec_uid, f"失败：{e}")
        raise HTTPException(404, str(e))
    except Exception as e:
        logger.error(f"检查订阅失败: {e}", exc_info=True)
        store.mark_creator_result(sec_uid, f"失败：{e}")
        raise HTTPException(500, f"检查失败：{e}")


class CheckAllRequest(BaseModel):
    download: bool = True
    max_new: int = 3
    # P2-3 手动检查策略：scope 空 = 跟随各创作者自己设置的下载范围；
    # 给值则本轮临时覆盖（不落库）。backfill_n 必须配合法的 scope_param。
    scope: Optional[str] = None
    scope_param: str = ""


@app.post("/api/subscriptions/check-all")
async def api_subscriptions_check_all(req: CheckAllRequest):
    """检查所有启用的订阅（串行，避免撞抖音限流）

    走 poller.run_round(manual=True) 而不是直接调 check_all：
    自动轮询和手动点击共用同一把锁，两轮绝不会同时抓主页。
    手动触发不计入退避，用户说了算。
    """
    from downloadkit import poller
    from downloadkit.subscription import validate_scope
    try:
        # scope 校验放在这里而不是 run_round 里：非法值要 400 中文报错
        # 挡在开跑之前，不能等抓完主页才发现策略写错了
        scope, scope_param = "", ""
        if req.scope is not None:
            scope, scope_param = validate_scope(req.scope, req.scope_param)
        return await poller.run_round(
            manual=True,
            download=req.download,
            max_new=req.max_new,
            scope=scope,
            scope_param=scope_param,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"批量检查失败: {e}", exc_info=True)
        raise HTTPException(500, f"批量检查失败：{e}")


@app.post("/api/subscriptions/preview")
async def api_subscriptions_preview(req: PreviewCreatorRequest):
    """订阅前预览：抓一次主页看有多少作品，但不入库"""
    from downloadkit.douyin_browser import RateLimited
    from downloadkit.subscription_service import LoginRequired, preview_creator
    try:
        return await preview_creator(req.url, max_scrolls=req.max_scrolls)
    except LoginRequired as e:
        return JSONResponse(status_code=401, content={"ok": False, "error": str(e)})
    except RateLimited as e:
        return JSONResponse(status_code=429, content={"ok": False, "error": str(e)})
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.error(f"预览创作者失败: {e}", exc_info=True)
        raise HTTPException(500, f"预览失败：{e}")


# 平台登录页 URL（用于"弹浏览器登录"流程）
_LOGIN_URLS = {
    "douyin": "https://www.douyin.com/",
    "bilibili": "https://passport.bilibili.com/login",
}


@app.get("/api/cookies/open-login")
async def api_cookies_open_login(platform: str = Query(...)):
    """在用户默认浏览器中打开指定平台的登录页

    流程：前端请求 → 后端调 webbrowser.open() 打开 URL → 返回 URL 让前端展示
    用户在浏览器里登录完成后，回到 app 点"已完成登录"，再调 /api/cookies/load-from-browser 读取。
    """
    if platform not in _LOGIN_URLS:
        raise HTTPException(400, f"不支持的平台: {platform}")
    url = _LOGIN_URLS[platform]
    try:
        import webbrowser
        opened = webbrowser.open(url, new=2)  # new=2: 新标签页
        return {"ok": True, "url": url, "opened": opened, "platform": platform}
    except Exception as e:
        # 打不开时仍把 URL 返给前端，让前端展示给用户自己复制
        return {"ok": False, "url": url, "platform": platform, "error": f"自动打开浏览器失败：{e}"}


@app.post("/api/cookies/load-from-browser")
async def api_cookies_load_from_browser(req: CookieLoadFromBrowserRequest):
    """从指定浏览器读取指定平台的 Cookie 列表

    用于 Cookie 设置页的"从浏览器读取"按钮，列出可用的 Cookie 项供用户选择保存。
    """
    if req.platform not in ("douyin", "bilibili", "xhs", "youtube"):
        raise HTTPException(400, f"不支持的平台: {req.platform}")

    # 延迟导入，避免 browser_cookie 在某些环境下加载失败
    try:
        from downloadkit.browser_cookie import (
            get_douyin_cookie_string,
            get_bilibili_cookie_string,
        )
    except Exception as e:
        raise HTTPException(500, f"无法加载 browser_cookie 模块: {e}")

    cookie_string = ""
    source_browser = ""
    if req.platform == "douyin":
        try:
            cookie_string = get_douyin_cookie_string(req.browser) or ""
            source_browser = req.browser
        except Exception as e:
            return {"ok": False, "platform": req.platform, "browser": req.browser,
                    "cookies": [], "count": 0, "cookie_string": "",
                    "error": f"从 {req.browser} 浏览器读取失败：{e}"}
    elif req.platform == "bilibili":
        try:
            cookie_string = get_bilibili_cookie_string(req.browser) or ""
            source_browser = req.browser
        except Exception as e:
            return {"ok": False, "platform": req.platform, "browser": req.browser,
                    "cookies": [], "count": 0, "cookie_string": "",
                    "error": f"从 {req.browser} 浏览器读取失败：{e}"}
    else:
        return {"ok": False, "platform": req.platform, "browser": req.browser,
                "cookies": [], "count": 0, "cookie_string": "",
                "error": f"{req.platform} 平台暂不支持浏览器自动读取，请使用文件方式"}

    # 解析为 dict（name -> value）让前端能展示
    cookies = {}
    if cookie_string:
        for part in cookie_string.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()

    return {
        "ok": bool(cookies),
        "platform": req.platform,
        "browser": source_browser,
        "cookies": [{"name": k, "value": v} for k, v in cookies.items()],
        "count": len(cookies),
        "cookie_string": cookie_string,  # 同时返回原始字符串，方便直接保存
    }


class CookieSaveRequest(BaseModel):
    platform: str  # "douyin" / "bilibili"
    cookie_string: str  # Cookie 字符串
    save_to_config: bool = True  # 是否同时保存到 UI 配置路径
    custom_path: str = ""  # 自定义保存路径，为空时用默认路径


@app.post("/api/cookies/save")
async def api_cookies_save(req: CookieSaveRequest):
    """保存 Cookie 到文件（同时更新 UI 配置路径）"""
    from pathlib import Path

    if not req.cookie_string or not req.cookie_string.strip():
        raise HTTPException(400, "Cookie 字符串不能为空")

    if req.platform not in ("douyin", "bilibili"):
        raise HTTPException(400, f"不支持的平台: {req.platform}")

    # 决定保存路径
    if req.custom_path and req.custom_path.strip():
        save_path = Path(req.custom_path.strip()).expanduser()
    else:
        save_path = Path.home() / ".downloadkit" / "cookies" / f"{req.platform}.txt"

    try:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(req.cookie_string.strip(), encoding="utf-8")
    except Exception as e:
        raise HTTPException(500, f"写入 Cookie 文件失败: {e}")

    # 同时保存到 config.toml 让 UI 路径生效
    if req.save_to_config:
        cfg = load_config()
        cfg.setdefault("cookie", {})[f"{req.platform}_path"] = str(save_path)
        save_config(cfg)

    return {"ok": True, "path": str(save_path), "message": f"已保存 {len(req.cookie_string)} 字符到 {save_path}"}


@app.post("/api/settings/update")
async def api_settings_update(req: SettingsUpdateRequest):
    """更新配置，只更新传入的字段"""
    config = {}
    if req.general is not None:
        config["general"] = req.general
    if req.proxy is not None:
        config["proxy"] = req.proxy
    if req.cookie is not None:
        config["cookie"] = req.cookie
    if not config:
        return {"status": "ok"}
    save_config(config)
    # 如果更新了 general 部分，同步 history_max_records
    if req.general is not None:
        history_max = req.general.get("history_max_records")
        if history_max is not None:
            download_history.update_max_records(int(history_max))
    return {"status": "ok", "settings": load_config()}


# Mount static files after API routes
static_dir = Path(__file__).parent / "downloadkit" / "static"
app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

@app.on_event("startup")
async def startup_event():
    """启动时注册队列worker"""
    # 从配置同步历史记录最大条数
    cfg = load_config()
    history_max = cfg.get("general", {}).get("history_max_records", 1000)
    download_history.update_max_records(history_max)

    # 下载目录归位：老版本把 music/、videos/ 直接生成在系统下载目录下，
    # 现在默认根目录是 ~/Downloads/DownloadKit，启动时把旧分类目录搬进来。
    # 一次性、幂等、只动默认路径（自定义过的一律不碰）；失败只记日志，不阻塞启动。
    try:
        from downloadkit.utils import migrate_legacy_download_dirs
        mig = migrate_legacy_download_dirs(cfg)
        if mig.get("moved"):
            logger.info(f"下载目录迁移：共搬 {mig['moved']} 项进 DownloadKit 总文件夹")
        if mig.get("errors"):
            logger.warning(f"下载目录迁移有 {len(mig['errors'])} 项留在原地: {mig['errors']}")
    except Exception as e:
        logger.warning(f"下载目录迁移失败（不影响启动）: {e}")

    # 注册清理回调，清理 _downloads 字典
    def cleanup_downloads():
        cleaned_ids = download_queue.cleanup_completed()
        for task_id in cleaned_ids:
            _downloads.pop(task_id, None)
    
    download_queue.add_cleanup_callback(cleanup_downloads)
    asyncio.create_task(download_queue.start())
    logger.info("Download queue worker started")

    # 预热抖音浏览器：启动 Chromium 约需 1~2 秒，
    # 放到启动阶段做，首次下载就不用等。
    # 失败不影响其他功能（首次下载时会懒启动）。
    async def _warmup_douyin():
        try:
            from downloadkit.douyin import get_browser
            await get_browser()
        except Exception as e:
            logger.warning(f"Douyin 浏览器预热失败（不影响其他功能）: {e}")

    asyncio.create_task(_warmup_douyin())

    # 订阅自动轮询（A5）。默认配置 enabled=False，任务起着但不跑，
    # 用户在「创作者订阅」页打开开关后自动开始；开关状态周期性重读，
    # 所以无需为开关再单独启停任务。
    try:
        from downloadkit import poller
        poller.start()
    except Exception as e:
        logger.warning(f"订阅轮询调度器启动失败（不影响其他功能）: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """关闭时释放浏览器资源"""
    # 先停轮询，避免关服务时它还在抓主页（会和浏览器关闭互相打断）
    try:
        from downloadkit import poller
        await poller.stop()
    except Exception as e:
        logger.warning(f"停止订阅轮询失败: {e}")

    try:
        from downloadkit.douyin import close_browser
        await close_browser()
    except Exception as e:
        logger.warning(f"关闭抖音浏览器失败: {e}")


def main():
    uvicorn.run(app, host="127.0.0.1", port=8765)

if __name__ == "__main__":
    main()
