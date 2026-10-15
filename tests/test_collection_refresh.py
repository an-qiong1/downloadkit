#!/usr/bin/env python3
"""歌单收藏模块（downloadkit/collection.py）回归

2026-10-15 P5-7 实测挖出的两个真 bug，都写成测试锁住 —— 它们此前一直没人
发现，是因为整个仓库没有任何一处覆盖 collection.py：

  1. `refresh_collection` 的 SELECT 少了 `auto_name`，后面却读
     `row["auto_name"]` → 必然 IndexError。也就是说
     `POST /api/collections/{id}/refresh` **从来就没工作过**，每次刷新都是
     500 Internal Server Error，CLI 把它暴露出来才看见。

  2. `_run_async` 的 `except RuntimeError` 罩住了整个 try 块，于是工作线程
     里 `asyncio.run` 抛出的 RuntimeError 会被当成「没有事件循环」再从主线程
     调一次 —— 那次必然撞上「cannot be called from a running event loop」，
     把解析器真正的报错盖得严严实实。DrissionPage 一类浏览器驱动很爱抛
     RuntimeError，用户看到的就会是一句驴唇不对马嘴的 asyncio 报错。

第 2 条必须在**有事件循环的线程里**才复现（那正是旧代码的错误分支），
所以用一层 asyncio.run 包起来调。
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from downloadkit import collection
from downloadkit.platforms.base import PlaylistInfo, SongInfo


@pytest.fixture()
def db(tmp_path, monkeypatch):
    """把歌单库指到临时目录，别碰用户真实的 ~/.downloadkit/collections.db。"""
    monkeypatch.setattr(collection, "_COLLECTION_DB_DIR", tmp_path)
    monkeypatch.setattr(collection, "_COLLECTION_DB_PATH",
                        tmp_path / "collections.db")
    collection._local.conn = None          # 丢掉缓存连接，让它按新路径重连
    collection._init_db()
    yield tmp_path / "collections.db"
    collection._local.conn = None


def _fake_parser(name="替身歌单", n=3, prefix="曲目"):
    """返回一个 async 解析器，替身掉真正的网络解析。"""

    async def parse(url):
        return PlaylistInfo(name=name, platform="netease", songs=[
            SongInfo(title=f"{prefix}{i}", artist=f"歌手{i}",
                     album="专辑A", platform="netease", song_id=f"sid{i}")
            for i in range(1, n + 1)
        ])

    return parse


# ======================= refresh（bug 1）=======================

def test_refresh_actually_works(db, monkeypatch):
    """这条此前必挂：SELECT 少了 auto_name → IndexError → 500。"""
    monkeypatch.setattr(collection, "parse_playlist", _fake_parser("旧名字", 2))
    created = collection.create_collection("https://example.com/p/1")
    cid = created["id"]
    assert len(collection.get_collection(cid)["tracks"]) == 2

    monkeypatch.setattr(collection, "parse_playlist",
                        _fake_parser("新名字", 5, prefix="新曲目"))
    result = collection.refresh_collection(cid)

    assert result is not None
    assert [t["title"] for t in result["tracks"]] == [
        "新曲目1", "新曲目2", "新曲目3", "新曲目4", "新曲目5"]
    assert result["song_count"] == 5


def test_refresh_updates_song_count_on_disk(db, monkeypatch):
    monkeypatch.setattr(collection, "parse_playlist", _fake_parser(n=2))
    cid = collection.create_collection("https://example.com/p/1")["id"]

    monkeypatch.setattr(collection, "parse_playlist", _fake_parser(n=7))
    collection.refresh_collection(cid)

    row = collection.list_collections()[0]
    assert row["song_count"] == 7


def test_refresh_replaces_old_tracks_entirely(db, monkeypatch):
    """不是追加，是清空再插新的 —— 否则每刷一次歌单就翻一倍。"""
    monkeypatch.setattr(collection, "parse_playlist", _fake_parser(n=3))
    cid = collection.create_collection("https://example.com/p/1")["id"]

    monkeypatch.setattr(collection, "parse_playlist",
                        _fake_parser(n=3, prefix="替换后"))
    result = collection.refresh_collection(cid)

    titles = [t["title"] for t in result["tracks"]]
    assert titles == ["替换后1", "替换后2", "替换后3"]
    assert not any(t.startswith("曲目") for t in titles)


def test_refresh_overwrites_auto_name(db, monkeypatch):
    """auto_name=1（没手动指定名称）→ 用歌单最新的名字覆盖。"""
    monkeypatch.setattr(collection, "parse_playlist", _fake_parser("原始名字"))
    cid = collection.create_collection("https://example.com/p/1")["id"]
    assert collection.get_collection(cid)["name"] == "原始名字"

    monkeypatch.setattr(collection, "parse_playlist", _fake_parser("平台改了名"))
    result = collection.refresh_collection(cid)

    assert result["name"] == "平台改了名"


def test_refresh_keeps_manual_name(db, monkeypatch):
    """手动改过名（auto_name=0）的歌单，刷新不该把名字冲掉。"""
    monkeypatch.setattr(collection, "parse_playlist", _fake_parser("原始名字"))
    cid = collection.create_collection("https://example.com/p/1",
                                       name="我起的名字")["id"]
    assert collection.get_collection(cid)["name"] == "我起的名字"

    monkeypatch.setattr(collection, "parse_playlist", _fake_parser("平台改了名"))
    result = collection.refresh_collection(cid)

    assert result["name"] == "我起的名字"


def test_refresh_missing_id_returns_none(db, monkeypatch):
    monkeypatch.setattr(collection, "parse_playlist", _fake_parser())
    assert collection.refresh_collection(9999) is None


def test_refresh_parse_failure_raises_valueerror(db, monkeypatch):
    """解析失败要变成 ValueError（服务端据此回 400），不能是别的异常。"""
    monkeypatch.setattr(collection, "parse_playlist", _fake_parser())
    cid = collection.create_collection("https://example.com/p/1")["id"]

    async def boom(url):
        raise RuntimeError("模拟的解析失败")

    monkeypatch.setattr(collection, "parse_playlist", boom)

    with pytest.raises(ValueError, match="歌单刷新失败"):
        collection.refresh_collection(cid)


def test_refresh_parse_failure_keeps_old_tracks(db, monkeypatch):
    """刷新失败不能把原来的缓存曲目清空——那等于一次失败把歌单弄残了。"""
    monkeypatch.setattr(collection, "parse_playlist", _fake_parser(n=3))
    cid = collection.create_collection("https://example.com/p/1")["id"]

    async def boom(url):
        raise RuntimeError("模拟的解析失败")

    monkeypatch.setattr(collection, "parse_playlist", boom)
    with pytest.raises(ValueError):
        collection.refresh_collection(cid)

    kept = collection.get_collection(cid)
    assert [t["title"] for t in kept["tracks"]] == ["曲目1", "曲目2", "曲目3"]
    assert kept["song_count"] == 3


# ===================== _run_async（bug 2）====================

def test_run_async_without_running_loop():
    async def ok():
        return 42

    assert collection._run_async(ok()) == 42


def test_run_async_does_not_mask_runtime_error():
    """核心回归：工作线程里抛的 RuntimeError 不能被当成「没有事件循环」。

    必须在有事件循环的线程里调才复现（那正是旧代码的错误分支）——旧代码
    会把它再跑一次 asyncio.run，结果抛出的是
    「asyncio.run() cannot be called from a running event loop」，
    真正的报错一个字都传不出来。
    """

    async def boom():
        raise RuntimeError("真正的错误")

    async def caller():
        return collection._run_async(boom())

    with pytest.raises(RuntimeError, match="真正的错误"):
        asyncio.run(caller())


def test_run_async_preserves_other_exceptions():
    """非 RuntimeError 的异常也要原样传出来，不能被吞成别的。"""

    async def boom():
        raise ValueError("解析失败了")

    async def caller():
        return collection._run_async(boom())

    with pytest.raises(ValueError, match="解析失败了"):
        asyncio.run(caller())
