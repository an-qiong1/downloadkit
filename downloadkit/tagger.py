"""ID3 标签写入器 -- 下载完成后将元数据写入 MP3 文件。"""

import logging
from pathlib import Path
from typing import Optional
import httpx

from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TRCK, TCON, APIC, USLT
from mutagen import MutagenError

from .platforms.base import SongInfo

logger = logging.getLogger(__name__)

_COVER_TIMEOUT = 15  # seconds
_MAX_COVER_BYTES = 5 * 1024 * 1024  # 5MB safety limit


def write_tags(filepath: Path, song: SongInfo) -> bool:
    """将 SongInfo 中的元数据写入 MP3 文件的 ID3 标签。

    写入的帧:
      - TIT2  标题
      - TPE1  艺术家
      - TALB  专辑
      - TDRC  年份
      - TRCK  音轨号
      - APIC  封面图片（内嵌）
      - USLT  歌词原文 + 翻译（内嵌）

    Args:
        filepath: MP3 文件路径
        song:    已补全元数据的 SongInfo

    Returns:
        True 表示标签写入成功（部分失败也算成功），
        False 表示完全写不了（文件不存在/不是 MP3）。
    """
    if not filepath or not filepath.exists():
        logger.warning(f"[tagger] 文件不存在，跳过打标签: {filepath}")
        return False

    if filepath.suffix.lower() not in (".mp3",):
        logger.info(f"[tagger] 非 MP3 文件，跳过打标签: {filepath.suffix}")
        return False

    try:
        # 加载或创建 ID3 标签
        try:
            audio = MP3(filepath, ID3=ID3)
        except Exception:
            audio = MP3(filepath)
            audio.add_tags()

        _write_text_frames(audio, song)
        _write_cover(audio, song.cover)
        _write_lyrics(audio, song)

        audio.save()
        logger.info(f"[tagger] 标签写入完成: {filepath.name}")
        return True

    except MutagenError as e:
        logger.warning(f"[tagger] Mutagen 写入失败: {e}")
        return False
    except Exception as e:
        logger.warning(f"[tagger] 打标签异常: {e}")
        return False


def _write_text_frames(audio: MP3, song: SongInfo):
    """写入文本类 ID3 帧。"""
    tags = audio.tags

    if song.title:
        tags.add(TIT2(encoding=3, text=song.title))
    if song.artist:
        tags.add(TPE1(encoding=3, text=song.artist))
    if song.album:
        tags.add(TALB(encoding=3, text=song.album))
    if song.year:
        tags.add(TDRC(encoding=3, text=str(song.year)))
    if song.track_number:
        tags.add(TRCK(encoding=3, text=str(song.track_number)))
    if song.genre:
        tags.add(TCON(encoding=3, text=song.genre))


def _write_cover(audio: MP3, cover_url: str):
    """从 URL 下载封面图并写入 APIC 帧。"""
    if not cover_url:
        return

    try:
        resp = httpx.get(cover_url, timeout=_COVER_TIMEOUT, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code != 200:
            logger.debug(f"[tagger] 封面下载失败: HTTP {resp.status_code}")
            return

        data = resp.content
        if not data or len(data) > _MAX_COVER_BYTES:
            logger.debug(f"[tagger] 封面数据无效或过大: {len(data) if data else 0} bytes")
            return

        # 根据 URL 后缀或 content-type 判断 mime
        mime = _guess_image_mime(cover_url, resp.headers.get("content-type", ""))
        audio.tags.add(
            APIC(encoding=3, mime=mime, type=3, desc="Cover", data=data)
        )
        logger.debug(f"[tagger] 封面已写入 ({len(data)} bytes, {mime})")
    except Exception as e:
        logger.debug(f"[tagger] 封面写入失败: {e}")


def _write_lyrics(audio: MP3, song: SongInfo):
    """写入歌词 USLT 帧（原文 + 翻译）。"""
    has_original = bool(song.lyrics)
    has_trans = bool(song.lyrics_trans)

    if not has_original and not has_trans:
        return

    if has_original:
        audio.tags.add(
            USLT(encoding=3, lang="chi", desc="", text=song.lyrics)
        )

    if has_trans and song.lyrics_trans != song.lyrics:
        audio.tags.add(
            USLT(encoding=3, lang="eng", desc="translation", text=song.lyrics_trans)
        )

    logger.debug(f"[tagger] 歌词已写入 (原文={has_original}, 翻译={has_trans})")


def _guess_image_mime(url: str, content_type: str) -> str:
    """根据 URL 或 Content-Type 猜测图片 MIME。"""
    ct = content_type.lower()
    if "png" in ct:
        return "image/png"
    if "webp" in ct:
        return "image/webp"
    if "gif" in ct:
        return "image/gif"

    url_lower = url.lower()
    if url_lower.endswith(".png"):
        return "image/png"
    if url_lower.endswith(".webp"):
        return "image/webp"
    if url_lower.endswith(".gif"):
        return "image/gif"

    return "image/jpeg"  # default
