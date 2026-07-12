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
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from pydantic import BaseModel
import uvicorn
import subprocess
import httpx

# Ensure downloadkit is importable
sys.path.insert(0, str(Path(__file__).parent))

from downloadkit.searcher import search_all
from downloadkit.playlist import parse_playlist
from downloadkit.downloader import download_song
from downloadkit.utils import get_download_dir, get_download_subdir, sanitize_filename, load_config, save_config
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
    p = Path(target)
    if not p.exists():
        raise HTTPException(404, f"路径不存在: {target}")
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


# ========== 设置接口 ==========

@app.get("/api/settings/get")
async def api_settings_get():
    """获取当前配置"""
    return {"settings": load_config()}


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

    # 注册清理回调，清理 _downloads 字典
    def cleanup_downloads():
        cleaned_ids = download_queue.cleanup_completed()
        for task_id in cleaned_ids:
            _downloads.pop(task_id, None)
    
    download_queue.add_cleanup_callback(cleanup_downloads)
    asyncio.create_task(download_queue.start())
    logger.info("Download queue worker started")

def main():
    uvicorn.run(app, host="127.0.0.1", port=8765)

if __name__ == "__main__":
    main()
