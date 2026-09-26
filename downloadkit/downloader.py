"""Download engine -- tries itzo.cn, then gequbao, then migu, then yt-dlp."""

import os, sys, asyncio
import logging
from pathlib import Path
import httpx
from .platforms import PLATFORM_MAP
from .platforms.base import SongInfo
from .platforms.itzo import search_and_get_url as itzo_search
from .platforms.gequbao import search_and_get_url as gequbao_search
from .platforms.migu import search_and_get_url as migu_search
from .utils import sanitize_filename, get_download_dir, get_download_subdir
from .download_queue import download_queue
from .exceptions import PauseException, CancelException
from .utils import check_download_status
from .enricher import enrich_metadata
from .tagger import write_tags

logger = logging.getLogger(__name__)


async def download_song(song: SongInfo, progress=None, task_id: str = None) -> Path | None:
    filename = sanitize_filename(f"{song.title} - {song.artist}")
    download_dir = get_download_subdir('music')
    filepath = download_dir / f"{filename}.mp3"

    # 检查取消/暂停状态
    if task_id:
        if download_queue.is_cancelled(task_id):
            raise CancelException("下载已取消")
        while download_queue.is_paused(task_id):
            await asyncio.sleep(0.5)
            if download_queue.is_cancelled(task_id):
                raise CancelException("下载已取消")

    result: Path | None = None

    # Step 1: Try platform direct URL
    if not result:
        url = await _get_download_url(song)
        if url and await _stream_download(url, filepath, task_id):
            result = filepath

    # Step 2: Try itzo.cn
    if not result:
        logger.info(f"[itzo] Searching: {song.title} - {song.artist.split(chr(47))[0]}")
        try:
            u = await itzo_search(song.title, song.artist)
            if u and await _stream_download(u, filepath, task_id):
                result = filepath
        except Exception as e:
            logger.error(f"[itzo] Error: {e}")

    # Step 3: Try gequbao
    if not result:
        logger.info("[gequbao] Searching...")
        try:
            u = await gequbao_search(song.title, song.artist)
            if u and await _stream_download(u, filepath, task_id):
                result = filepath
        except Exception as e:
            logger.error(f"[gequbao] Error: {e}")

    # Step 4: Try migu
    if not result:
        logger.info("[migu] Searching...")
        try:
            u = await migu_search(song.title, song.artist)
            if u and await _stream_download(u, filepath, task_id):
                result = filepath
        except Exception as e:
            logger.error(f"[migu] Error: {e}")

    # Step 5: yt-dlp
    if not result:
        logger.info("[yt-dlp] Searching...")
        try:
            result = await _download_via_ytdlp(song, filepath)
        except Exception as e:
            logger.error(f"[yt-dlp] Failed: {e}")

    # ── 后处理：元数据补全 + ID3 打标签 ──────────────────────────
    if result and result.exists():
        try:
            enriched = await enrich_metadata(song)
            write_tags(result, enriched)
        except Exception as e:
            logger.warning(f"[post] 打标签失败（不影响下载）: {e}")

    return result


async def _stream_download(url: str, filepath: Path, task_id: str = None) -> bool:
    try:
        headers = {}
        if "music.163.com" in url or "163.com" in url:
            headers["Referer"] = "https://music.163.com/"
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        
        # 断点续传：检查已下载的字节数
        downloaded_bytes = 0
        if filepath.exists():
            downloaded_bytes = filepath.stat().st_size
            if downloaded_bytes > 0:
                headers["Range"] = f"bytes={downloaded_bytes}-"
                logger.info(f"[Resume] 从 {downloaded_bytes} 字节继续下载")
        
        async with httpx.AsyncClient(timeout=120, follow_redirects=True, headers=headers) as client:
            async with client.stream("GET", url) as resp:
                # 处理 Range 响应
                if downloaded_bytes > 0 and resp.status_code == 416:
                    # 已经下载完成
                    logger.info("[Resume] 文件已下载完成")
                    return True
                
                if resp.status_code == 206:
                    # 服务器支持 Range 请求，追加写入
                    mode = "ab"
                else:
                    # 服务器不支持 Range，重新下载
                    if downloaded_bytes > 0:
                        logger.warning("[Resume] 服务器不支持 Range 请求，重新下载")
                    downloaded_bytes = 0
                    mode = "wb"
                
                resp.raise_for_status()
                # Verify it's actually audio, not HTML error page
                ct = resp.headers.get("content-type", "")
                if "text/html" in ct:
                    logger.warning("[DL error] Got HTML instead of audio (wrong Referer?)")
                    return False
                
                with open(filepath, mode) as f:
                    async for chunk in resp.aiter_bytes(chunk_size=65536):
                        # 检查取消/暂停状态
                        check_download_status(task_id)
                        f.write(chunk)
                        
                        # 更新下载进度
                        if task_id:
                            downloaded_bytes += len(chunk)
                            download_queue.update_progress(
                                task_id, 
                                progress=0.0,  # 未知总大小
                                downloaded_size=downloaded_bytes
                            )
        
        return True
    except Exception as e:
        logger.error(f"[DL error] {type(e).__name__}: {e}")
        return False


async def _get_download_url(song: SongInfo) -> str | None:
    if song.url: return song.url
    platform = PLATFORM_MAP.get(song.platform)
    if not platform: return None
    url = await platform.get_song_url(song)
    if url: song.url = url
    return url


async def _download_via_ytdlp(song: SongInfo, filepath: Path) -> Path:
    scripts_dir = Path(sys.executable).parent
    ytdlp = str(scripts_dir / "yt-dlp.exe")
    if not os.path.exists(ytdlp): ytdlp = "yt-dlp"
    query = f"{song.title} {song.artist}"
    output_template = str(filepath.with_suffix("")) + ".%(ext)s"
    for search_prefix in ["ytsearch1", "bilisearch1"]:
        cmd = [ytdlp, "-f", "bestaudio", "--extract-audio", "--audio-format", "mp3",
               "--audio-quality", "0", "-o", output_template, "--no-playlist",
               "--max-downloads", "1", "--socket-timeout", "15",
               f"{search_prefix}:{query}"]
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        stdout, stderr = await proc.communicate()
        if proc.returncode == 0:
            actual = filepath
            if not actual.exists():
                candidates = list(actual.parent.glob(sanitize_filename(f"{song.title} - {song.artist}.*")))
                if candidates: actual = candidates[0]
            return actual
            logger.warning(f"[yt-dlp] {search_prefix}: {stderr.decode()[:200]}")
    raise RuntimeError("All yt-dlp sources exhausted")


async def download_batch(songs, progress=None):
    ok, fail = 0, 0
    for song in songs:
        if await download_song(song, progress): ok += 1
        else: fail += 1
    return ok, fail
