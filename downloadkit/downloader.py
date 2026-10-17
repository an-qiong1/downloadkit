"""Download engine -- tries itzo.cn, gequbao, migu, kuwo, kugou, soda, then yt-dlp."""

import asyncio
import logging
import shutil
from pathlib import Path
import httpx
from .platforms import PLATFORM_MAP
from .platforms.base import SongInfo
from .platforms.itzo import search_and_get_url as itzo_search
from .platforms.gequbao import search_and_get_url as gequbao_search
from .platforms.migu import search_and_get_url as migu_search
from .platforms.kuwo import search_and_get_url as kuwo_search
from .platforms.kugou import search_and_get_url as kugou_search
from .platforms.soda import search_and_get_url as soda_search
from .utils import sanitize_filename, get_download_dir, get_download_subdir, CREATE_NO_WINDOW
from .download_queue import download_queue
from .exceptions import PauseException, CancelException
from .utils import check_download_status
from .enricher import enrich_metadata
from .tagger import write_tags

logger = logging.getLogger(__name__)

# 半截文件当前属于哪个源（filepath -> URL）。
# 断点续传只在同一个源上安全：换了源还带 Range，后一源会从半截处接着写
# （服务器回 206 时），结果是两段不同的音频被拼进同一个文件。来源不明的
# 残留一律重下——宁可多下一次，也不产出拼接出来的坏文件。
_partial_source: dict[str, str] = {}


async def download_song(song: SongInfo, progress=None, task_id: str = None, output_dir: str | None = None) -> Path | None:
    filename = sanitize_filename(f"{song.title} - {song.artist}")
    if output_dir:
        download_dir = Path(output_dir)
        download_dir.mkdir(parents=True, exist_ok=True)
    else:
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

    try:
        result = await _run_download_chain(song, filepath, task_id)
    except (PauseException, CancelException):
        _drop_empty_artifact(filepath)
        raise
    if not result:
        _drop_empty_artifact(filepath)

    # ── 后处理：元数据补全 + ID3 打标签 ──────────────────────────
    if result and result.exists():
        try:
            enriched = await enrich_metadata(song)
            write_tags(result, enriched)
        except Exception as e:
            logger.warning(f"[post] 打标签失败（不影响下载）: {e}")

    return result


def _drop_empty_artifact(filepath: Path) -> None:
    """删掉 0 字节的产物空壳。

    _stream_download 先 open(wb) 再流式写入：若在第一个字节写出前
    失败/被取消，磁盘上就留下一个 0 字节的 .mp3 —— 文件列表里显示成
    一首"能看见、播不了"的假歌（2026-10-17 打包版取消测试实测）。
    空壳对断点续传也没有任何价值（续传看的是已有字节数，0 即从头下），
    一律删掉。非 0 的半截文件**必须保留**：那是同源重试续传的依据。
    """
    try:
        if filepath.exists() and filepath.stat().st_size == 0:
            filepath.unlink()
            logger.info(f"[DL] 清理 0 字节产物空壳: {filepath.name}")
    except OSError as e:
        logger.warning(f"[DL] 清理空壳失败: {type(e).__name__}: {e}")


async def _run_download_chain(song: SongInfo, filepath: Path,
                              task_id: str | None) -> Path | None:
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

    # Step 5: Try kuwo
    if not result:
        logger.info("[kuwo] Searching...")
        try:
            u = await kuwo_search(song.title, song.artist)
            if u and await _stream_download(u, filepath, task_id):
                result = filepath
        except Exception as e:
            logger.error(f"[kuwo] Error: {e}")

    # Step 6: Try kugou
    if not result:
        logger.info("[kugou] Searching...")
        try:
            u = await kugou_search(song.title, song.artist)
            if u and await _stream_download(u, filepath, task_id):
                result = filepath
        except Exception as e:
            logger.error(f"[kugou] Error: {e}")

    # Step 7: Try soda (汽水音乐)
    if not result:
        logger.info("[soda] Searching...")
        try:
            u = await soda_search(song.title, song.artist)
            if u and await _stream_download(u, filepath, task_id):
                result = filepath
        except Exception as e:
            logger.error(f"[soda] Error: {e}")

    # Step 8: yt-dlp
    if not result:
        logger.info("[yt-dlp] Searching...")
        try:
            result = await _download_via_ytdlp(song, filepath)
        except Exception as e:
            logger.error(f"[yt-dlp] Failed: {e}")

    return result


async def _stream_download(url: str, filepath: Path, task_id: str = None) -> bool:
    try:
        headers = {}
        if "music.163.com" in url or "163.com" in url:
            headers["Referer"] = "https://music.163.com/"
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        
        # 断点续传：只有这份半截文件确实是同一个源留下来的才续，
        # 否则（换了源 / 来源不明）丢掉重下，避免两段不同音频被拼进一个文件
        downloaded_bytes = 0
        if filepath.exists():
            if _partial_source.get(str(filepath)) == url:
                downloaded_bytes = filepath.stat().st_size
            if downloaded_bytes > 0:
                headers["Range"] = f"bytes={downloaded_bytes}-"
                logger.info(f"[Resume] 同源续传，从 {downloaded_bytes} 字节继续")
            else:
                logger.info("[Resume] 残留文件不是本源产物，丢弃后重新下载")
                filepath.unlink(missing_ok=True)
        _partial_source[str(filepath)] = url

        async with httpx.AsyncClient(timeout=120, follow_redirects=True, headers=headers) as client:
            async with client.stream("GET", url) as resp:
                # 处理 Range 响应
                if downloaded_bytes > 0 and resp.status_code == 416:
                    # 已经下载完成
                    logger.info("[Resume] 文件已下载完成")
                    _partial_source.pop(str(filepath), None)
                    return await _ensure_mp3(filepath)
                
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
                    # 没写入任何字节，半截文件（若有）仍属于同一源，保留以便续传
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
        
        # 产物扩展名固定 .mp3，必须保证内容真的是 MP3：itzo 的 QQ 源给的是
        # m4a，这里转一道，避免"文件名写 mp3、里面装 AAC"（tagger 也打不进去）
        if not await _ensure_mp3(filepath):
            logger.warning("[DL error] 产物不是可接受的 MP3，丢弃")
            filepath.unlink(missing_ok=True)
            _partial_source.pop(str(filepath), None)
            return False
        _partial_source.pop(str(filepath), None)
        return True
    except (PauseException, CancelException):
        # 取消/暂停必须往上抛，否则会被当成"这一级失败"继续试下一级
        raise
    except Exception as e:
        logger.error(f"[DL error] {type(e).__name__}: {e}")
        return False


def _looks_like_mp3(path: Path) -> bool:
    """按魔数判断是否 MP3（ID3 标签头或帧同步字）。"""
    try:
        with path.open("rb") as f:
            head = f.read(3)
    except OSError:
        return False
    if len(head) < 3:
        return False
    if head[:3] == b"ID3":
        return True
    return head[0] == 0xFF and (head[1] & 0xE0) == 0xE0


async def _ensure_mp3(path: Path) -> bool:
    """确保落盘的是 MP3；非 MP3（如 m4a）用 ffmpeg 转码。"""
    if not path.exists() or path.stat().st_size == 0:
        return False
    if _looks_like_mp3(path):
        return True
    return await _transcode_to_mp3(path)


async def _transcode_to_mp3(path: Path) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning("[DL] 未找到 ffmpeg，无法把非 MP3 音频转成 MP3")
        return False
    tmp = path.with_name(path.name + ".tmp.mp3")
    # 剥掉原容器元数据，标签交给 tagger 统一写
    cmd = [ffmpeg, "-y", "-i", str(path), "-vn", "-map_metadata", "-1",
           "-codec:a", "libmp3lame", "-q:a", "0", str(tmp)]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW)
        _, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
    except Exception as e:
        logger.warning(f"[DL] 转码失败: {type(e).__name__}: {e}")
        tmp.unlink(missing_ok=True)
        return False
    if proc.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        tail = (stderr or b"").decode(errors="replace").strip()[-200:]
        logger.warning(f"[DL] 转码失败 (rc={proc.returncode}): {tail}")
        tmp.unlink(missing_ok=True)
        return False
    tmp.replace(path)
    return True


async def _get_download_url(song: SongInfo) -> str | None:
    if song.url: return song.url
    platform = PLATFORM_MAP.get(song.platform)
    if not platform: return None
    url = await platform.get_song_url(song)
    if url: song.url = url
    return url


async def _download_via_ytdlp(song: SongInfo, filepath: Path) -> Path:
    from .generic_video import _yt_dlp_cmd

    cmd_base = _yt_dlp_cmd()
    if not cmd_base:
        raise RuntimeError("yt-dlp 不可用：未找到独立 yt-dlp 且当前为打包环境")
    query = f"{song.title} {song.artist}"
    output_template = str(filepath.with_suffix("")) + ".%(ext)s"
    errors: list[str] = []
    # 跑之前先记下已有产物，成功必须是本次新写出来的（否则上次中断留下的
    # 半截文件会被当成成功）
    before = _artifact_state(filepath, song)
    for search_prefix in ["ytsearch1", "bilisearch1"]:
        cmd = [*cmd_base, "-f", "bestaudio", "--extract-audio", "--audio-format", "mp3",
               "--audio-quality", "0", "-o", output_template, "--no-playlist",
               "--max-downloads", "1", "--socket-timeout", "15",
               f"{search_prefix}:{query}"]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW)
        stdout, stderr = await proc.communicate()

        # 成功与否只看产物，不看退出码：--max-downloads 1 命中后 yt-dlp 以
        # 101 (Aborting remaining downloads) 退出，音频其实已完整落盘
        # （2026-10-14 实测：rc=101 + 文件 7.26MiB 完好）。老逻辑要求
        # rc==0，把下成功的歌报成 "All yt-dlp sources exhausted"。
        actual, state = _artifact_state(filepath, song, return_path=True)
        if actual and state != before and actual.stat().st_size > 0:
            return actual

        tail = (stderr or b"").decode(errors="replace").strip()[-300:]
        errors.append(f"{search_prefix} rc={proc.returncode}: {tail}")
        logger.warning(f"[yt-dlp] {search_prefix} 未产出文件 (rc={proc.returncode}): {tail[:200]}")
    raise RuntimeError("All yt-dlp sources exhausted: " + " | ".join(errors))


def _artifact_state(filepath: Path, song: SongInfo, return_path: bool = False):
    """定位产物文件并返回 (路径, 状态指纹)；无产物时路径为 None。

    指纹用 (大小, 修改时间) ，用来区分"本次新写"与"历史残留"。
    """
    actual = filepath if filepath.exists() else None
    if actual is None:
        candidates = list(filepath.parent.glob(sanitize_filename(f"{song.title} - {song.artist}.*")))
        actual = candidates[0] if candidates else None
    state = (actual.stat().st_size, actual.stat().st_mtime_ns) if actual else None
    return (actual, state) if return_path else state


async def download_batch(songs, progress=None):
    ok, fail = 0, 0
    for song in songs:
        if await download_song(song, progress): ok += 1
        else: fail += 1
    return ok, fail
