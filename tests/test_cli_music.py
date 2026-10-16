#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 音乐下载基础命令（search / download / playlist）回归

P5-8：老命令此前无 CLI 测试。
- search：patch cli.search_all（顶层 import）
- download / playlist：patch cli.parse_playlist + pl_mod.parse_playlist
  （parse_playlist 在 cli 顶层 import，本地 from .playlist import 得到同一对象，
   但 patch 后需双端同步才能生效）
- download_song：async 替身
"""
import asyncio
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

import downloadkit.cli as cli
from downloadkit.platforms.base import SongInfo, PlaylistInfo


def _run(args, input=None):
    return CliRunner().invoke(cli.main, args, input=input, catch_exceptions=False)


def _song(n=1, title="晴天", artist="周杰伦"):
    return SongInfo(title=title, artist=artist, album="专辑", platform="netease",
                    song_id=f"sid{n}")


def _playlist(n=3, name="我的歌单"):
    return PlaylistInfo(name=name, platform="netease", song_count=n,
                        songs=[_song(i + 1) for i in range(n)])


def _async_value(val):
    async def _inner():
        return val
    return _inner()


def _fake_parse(n=1):
    """返回一个返回协程的 parse_playlist 替身。"""
    async def fake(url):
        return _playlist(n)
    return fake


# ============================ search ============================

def test_search_calls_search_all(monkeypatch):
    songs = [_song(1), _song(2)]
    monkeypatch.setattr(cli, "search_all", lambda kw, limit: _async_value(songs))
    r = _run(["search", "test", "-n", "5"], input="q\n")
    assert r.exit_code == 0
    assert "周杰伦" in r.output


def test_search_empty_result(monkeypatch):
    monkeypatch.setattr(cli, "search_all", lambda kw, limit: _async_value([]))
    r = _run(["search", "不存在"], input="q\n")
    assert r.exit_code == 0
    assert "未找到歌曲" in r.output


def test_search_select_via_input(monkeypatch):
    """选 1 → 调 download_song。"""
    songs = [_song(1), _song(2)]
    monkeypatch.setattr(cli, "search_all", lambda kw, limit: _async_value(songs))
    called = []
    async def fake_dl(song, **kw):
        called.append(song.title)
        return Path("/fake/song.mp3")
    monkeypatch.setattr(cli, "download_song", fake_dl)
    r = _run(["search", "test", "-s", "1"])
    assert r.exit_code == 0
    assert called == ["晴天"]


def test_search_select_a_all(monkeypatch):
    """a=全部 → 下载所有。"""
    songs = [_song(1), _song(2)]
    monkeypatch.setattr(cli, "search_all", lambda kw, limit: _async_value(songs))
    called = []
    async def fake_dl(song, **kw):
        called.append(song.title)
        return Path("/fake/song.mp3")
    monkeypatch.setattr(cli, "download_song", fake_dl)
    r = _run(["search", "test", "-s", "a"])
    assert r.exit_code == 0
    assert len(called) == 2


def test_search_no_selection_quits(monkeypatch):
    """prompt q → 退出，不下载。"""
    songs = [_song(1)]
    monkeypatch.setattr(cli, "search_all", lambda kw, limit: _async_value(songs))
    called = []
    async def fake_dl(song, **kw):
        called.append(1)
        return None
    monkeypatch.setattr(cli, "download_song", fake_dl)
    r = _run(["search", "test"], input="q\n")
    assert r.exit_code == 0
    assert called == []


# ============================ download ============================

def test_download_requires_url(monkeypatch):
    r = _run(["download", "not_a_url"])
    assert r.exit_code == 0
    assert "请提供歌曲链接" in r.output


def test_download_calls_download_song(monkeypatch):
    fake = _fake_parse(1)
    cli.parse_playlist = fake
    import downloadkit.playlist as pl_mod
    pl_mod.parse_playlist = fake
    called = []
    async def fake_dl(song, **kw):
        called.append({"title": song.title, "output": kw.get("output_dir")})
        return Path("/tmp/test.mp3")
    monkeypatch.setattr(cli, "download_song", fake_dl)
    r = _run(["download", "https://music.163.com/#/song?id=123", "-o", "/tmp/out"])
    assert r.exit_code == 0
    assert len(called) == 1
    assert called[0]["output"] == "/tmp/out"
    assert "已保存到" in r.output


def test_download_output_defaults_to_none(monkeypatch):
    fake = _fake_parse(1)
    cli.parse_playlist = fake
    import downloadkit.playlist as pl_mod
    pl_mod.parse_playlist = fake
    called = []
    async def fake_dl(song, **kw):
        called.append(kw.get("output_dir"))
        return Path("/tmp/test.mp3")
    monkeypatch.setattr(cli, "download_song", fake_dl)
    r = _run(["download", "https://music.163.com/#/song?id=1"])
    assert r.exit_code == 0
    assert called[0] is None


# ============================ playlist ============================

def test_playlist_calls_parse_and_download(monkeypatch):
    fake = _fake_parse(1)
    cli.parse_playlist = fake
    import downloadkit.playlist as pl_mod
    pl_mod.parse_playlist = fake
    called = []
    async def fake_dl(song, **kw):
        called.append(song.title)
        return Path("/tmp/song.mp3")
    monkeypatch.setattr(cli, "download_song", fake_dl)
    r = _run(["playlist", "https://music.163.com/#/playlist?id=1", "-o", "/tmp/pl"],
             input="y\n")
    assert r.exit_code == 0
    assert len(called) == 1


def test_playlist_empty(monkeypatch):
    async def empty_fake(url):
        return PlaylistInfo(name="", platform="", song_count=0, songs=[])
    cli.parse_playlist = empty_fake
    import downloadkit.playlist as pl_mod
    pl_mod.parse_playlist = empty_fake
    r = _run(["playlist", "https://music.163.com/#/playlist?id=1"])
    assert r.exit_code == 0
    assert "歌单为空" in r.output


def test_playlist_cancel(monkeypatch):
    fake = _fake_parse(1)
    cli.parse_playlist = fake
    import downloadkit.playlist as pl_mod
    pl_mod.parse_playlist = fake
    called = []
    async def fake_dl(song, **kw):
        called.append(1)
        return None
    monkeypatch.setattr(cli, "download_song", fake_dl)
    r = _run(["playlist", "https://music.163.com/#/playlist?id=1"], input="n\n")
    assert r.exit_code == 0
    assert called == []
    assert "下载全部歌曲" in r.output


# ============================= 组 =============================

def test_help_has_chinese_commands():
    r = _run(["--help"])
    assert r.exit_code == 0
    for name in ("search", "playlist", "download", "douyin", "parse", "video",
                 "queue", "subscribe", "files", "sniff", "bookmarks", "settings",
                 "collections", "history"):
        assert name in r.output, f"命令 {name} 不在帮助中"
