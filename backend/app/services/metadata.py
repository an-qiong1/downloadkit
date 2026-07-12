from pathlib import Path
from mutagen.mp3 import MP3
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TIT2, TPE1, TALB, APIC
from mutagen.mp4 import MP4, MP4Cover
import requests
from typing import Optional


class MetadataWriter:
    """音视频元数据写入器"""

    @staticmethod
    def write_music_metadata(
        file_path: str,
        title: str = "",
        artist: str = "",
        album: str = "",
        cover_url: str = "",
    ):
        path = Path(file_path)
        if not path.exists():
            return

        ext = path.suffix.lower()

        try:
            if ext == ".mp3":
                MetadataWriter._write_mp3(file_path, title, artist, album, cover_url)
            elif ext == ".flac":
                MetadataWriter._write_flac(file_path, title, artist, album, cover_url)
            elif ext in (".m4a", ".mp4"):
                MetadataWriter._write_m4a(file_path, title, artist, album, cover_url)
        except Exception as e:
            print(f"写入元数据失败: {e}")

    @staticmethod
    def _write_mp3(file_path: str, title: str, artist: str, album: str, cover_url: str):
        try:
            audio = MP3(file_path, ID3=ID3)
        except Exception:
            audio = MP3(file_path)
            audio.add_tags()

        if title:
            audio.tags.add(TIT2(encoding=3, text=title))
        if artist:
            audio.tags.add(TPE1(encoding=3, text=artist))
        if album:
            audio.tags.add(TALB(encoding=3, text=album))

        if cover_url:
            try:
                resp = requests.get(cover_url, timeout=10)
                if resp.status_code == 200:
                    audio.tags.add(
                        APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=resp.content)
                    )
            except Exception:
                pass
        audio.save()

    @staticmethod
    def _write_flac(file_path: str, title: str, artist: str, album: str, cover_url: str):
        audio = FLAC(file_path)
        if title:
            audio["title"] = title
        if artist:
            audio["artist"] = artist
        if album:
            audio["album"] = album
        if cover_url:
            try:
                resp = requests.get(cover_url, timeout=10)
                if resp.status_code == 200:
                    from mutagen.flac import Picture
                    pic = Picture()
                    pic.data = resp.content
                    pic.type = 3
                    pic.mime = "image/jpeg"
                    pic.desc = "Cover"
                    audio.add_picture(pic)
            except Exception:
                pass
        audio.save()

    @staticmethod
    def _write_m4a(file_path: str, title: str, artist: str, album: str, cover_url: str):
        audio = MP4(file_path)
        if title:
            audio["\xa9nam"] = title
        if artist:
            audio["\xa9ART"] = artist
        if album:
            audio["\xa9alb"] = album
        if cover_url:
            try:
                resp = requests.get(cover_url, timeout=10)
                if resp.status_code == 200:
                    audio["covr"] = [MP4Cover(resp.content, MP4Cover.FORMAT_JPEG)]
            except Exception:
                pass
        audio.save()
