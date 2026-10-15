"""歌单收藏管理器 - SQLite 持久化存储

提供收藏歌单的增删改查、刷新缓存等核心操作。
桌面版 (server.py) 和 NAS Docker 版 (backend/) 共用此模块。

数据库位置: ~/.downloadkit/collections.db
表结构:
  collections        - 收藏歌单主表
  collection_tracks  - 缓存歌曲列表（刷新时全量替换）
"""

import sqlite3
import threading
import asyncio
import concurrent.futures
from pathlib import Path
from datetime import datetime
from typing import Optional

from .playlist import parse_playlist


def _run_async(coro):
    """安全地从同步代码中运行协程，兼容有无正在运行的事件循环两种场景。

    注意 except 的作用域只能罩住 get_running_loop()：如果连 pool.submit
    一起罩住，工作线程里 asyncio.run 抛出的 RuntimeError 会被当成「没有
    事件循环」再从主线程调一次 —— 那次必然撞上「cannot be called from a
    running event loop」，把解析器真正的报错盖得严严实实（DrissionPage
    一类浏览器驱动很爱抛 RuntimeError，实测踩到过）。
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # 没有事件循环 → 直接创建
        return asyncio.run(coro)
    # 已有事件循环 → 在独立线程中运行
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()

# ── 数据库路径 ──────────────────────────────────────────

_COLLECTION_DB_DIR = Path.home() / ".downloadkit"
_COLLECTION_DB_PATH = _COLLECTION_DB_DIR / "collections.db"

# 线程锁（sqlite3 连接不能跨线程共享）
_local = threading.local()
_db_lock = threading.Lock()


def _get_db() -> sqlite3.Connection:
    """获取当前线程的数据库连接（懒创建）"""
    if not hasattr(_local, "conn") or _local.conn is None:
        _COLLECTION_DB_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_COLLECTION_DB_PATH), detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


def _init_db():
    """确保数据库表存在（幂等）"""
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS collections (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            url         TEXT NOT NULL UNIQUE,
            platform    TEXT NOT NULL,
            song_count  INTEGER DEFAULT 0,
            auto_name   INTEGER DEFAULT 1,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            refreshed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS collection_tracks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            collection_id   INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
            title           TEXT NOT NULL,
            artist          TEXT DEFAULT '',
            album           TEXT DEFAULT '',
            song_id         TEXT NOT NULL,
            platform        TEXT NOT NULL,
            sort_order      INTEGER DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_tracks_collection
            ON collection_tracks(collection_id);
    """)
    conn.commit()


# 模块加载时自动初始化
_init_db()


def _row_to_dict(row: sqlite3.Row) -> dict:
    """将 sqlite3.Row 转为普通 dict"""
    return dict(row) if row else {}


# ── 公开 API ──────────────────────────────────────────


def list_collections() -> list[dict]:
    """获取所有收藏歌单列表（不含缓存曲目）"""
    conn = _get_db()
    rows = conn.execute(
        "SELECT id, name, url, platform, song_count, auto_name, created_at, refreshed_at "
        "FROM collections ORDER BY refreshed_at DESC, created_at DESC"
    ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_collection(collection_id: int) -> Optional[dict]:
    """获取单个收藏歌单详情（含缓存曲目列表）

    Returns:
        {
            "id": ...,
            "name": ...,
            "url": ...,
            "platform": ...,
            "song_count": ...,
            "auto_name": ...,
            "created_at": ...,
            "refreshed_at": ...,
            "tracks": [
                {"id": ..., "title": ..., "artist": ..., "album": ..., "song_id": ..., "platform": ..., "sort_order": ...},
                ...
            ]
        }
        不存在时返回 None
    """
    conn = _get_db()
    row = conn.execute(
        "SELECT id, name, url, platform, song_count, auto_name, created_at, refreshed_at "
        "FROM collections WHERE id = ?", (collection_id,)
    ).fetchone()
    if not row:
        return None

    collection = _row_to_dict(row)
    track_rows = conn.execute(
        "SELECT id, title, artist, album, song_id, platform, sort_order "
        "FROM collection_tracks WHERE collection_id = ? "
        "ORDER BY sort_order", (collection_id,)
    ).fetchall()
    collection["tracks"] = [_row_to_dict(t) for t in track_rows]
    return collection


def create_collection(url: str, name: str = "", platform: str = "") -> dict:
    """添加收藏歌单

    先调用 parse_playlist 解析歌单，自动获取名称和平台信息，
    然后写入数据库并缓存歌曲列表。

    Args:
        url: 歌单链接
        name: 自定义名称（为空则用解析结果自动命名）
        platform: 平台（为空则自动检测）

    Returns:
        创建后的完整歌单 dict（含 tracks）

    Raises:
        ValueError: URL 不合法或解析失败
    """
    try:
        pl_info = _run_async(parse_playlist(url))
    except Exception as e:
        raise ValueError(f"歌单解析失败: {e}")

    # 确定名称和平台
    final_name = name.strip() or pl_info.name or "未命名歌单"
    final_platform = platform or pl_info.platform or "unknown"

    conn = _get_db()
    with _db_lock:
        # 检查是否已收藏（按 URL 去重）
        existing = conn.execute(
            "SELECT id FROM collections WHERE url = ?", (url,)
        ).fetchone()
        if existing:
            raise ValueError(f"该歌单已收藏（ID: {existing['id']}），请勿重复添加")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor = conn.execute(
            "INSERT INTO collections (name, url, platform, song_count, auto_name, refreshed_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (final_name, url, final_platform, len(pl_info.songs), 1 if not name.strip() else 0, now),
        )
        collection_id = cursor.lastrowid

        # 缓存歌曲列表
        for idx, song in enumerate(pl_info.songs):
            conn.execute(
                "INSERT INTO collection_tracks (collection_id, title, artist, album, song_id, platform, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (collection_id, song.title, song.artist, song.album or "", song.song_id, song.platform, idx),
            )
        conn.commit()

    return get_collection(collection_id)


def update_collection(collection_id: int, **kwargs) -> Optional[dict]:
    """更新收藏歌单信息（如重命名）

    支持的 kwargs:
        name: 新名称

    Returns:
        更新后的歌单 dict，不存在返回 None
    """
    conn = _get_db()
    with _db_lock:
        existing = conn.execute(
            "SELECT id FROM collections WHERE id = ?", (collection_id,)
        ).fetchone()
        if not existing:
            return None

        updates = []
        values = []
        for key in ("name",):
            if key in kwargs:
                updates.append(f"{key} = ?")
                values.append(kwargs[key])

        if not updates:
            return get_collection(collection_id)

        values.append(collection_id)
        conn.execute(
            f"UPDATE collections SET {', '.join(updates)} WHERE id = ?",
            values,
        )
        conn.commit()

    return get_collection(collection_id)


def delete_collection(collection_id: int) -> bool:
    """删除收藏歌单（级联删除缓存曲目）

    Returns:
        True 删除成功，False 不存在
    """
    conn = _get_db()
    with _db_lock:
        existing = conn.execute(
            "SELECT id FROM collections WHERE id = ?", (collection_id,)
        ).fetchone()
        if not existing:
            return False
        conn.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        conn.commit()
    return True


def refresh_collection(collection_id: int) -> Optional[dict]:
    """刷新收藏歌单：重新解析链接，替换缓存曲目列表

    流程:
        1. 从数据库取出收藏记录
        2. 调用 parse_playlist() 重新解析
        3. 在事务中清空旧曲目 → 插入新曲目
        4. 更新 song_count + refreshed_at

    Returns:
        刷新后的完整歌单 dict，不存在返回 None
    """
    conn = _get_db()
    with _db_lock:
        # auto_name 必须一起 SELECT 出来：下面要用它决定「刷新时要不要用
        # 歌单最新名字覆盖」，漏了它 row["auto_name"] 会 IndexError，
        # 而这个端点此前从来没工作过——每次刷新都是 500
        row = conn.execute(
            "SELECT id, name, url, platform, auto_name FROM collections "
            "WHERE id = ?", (collection_id,)
        ).fetchone()
        if not row:
            return None

        url = row["url"]
        auto_name = bool(row["auto_name"])

    try:
        pl_info = _run_async(parse_playlist(url))
    except Exception as e:
        raise ValueError(f"歌单刷新失败: {e}")

    with _db_lock:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 如果 auto_name 开启，用最新的歌单名更新
        if auto_name and pl_info.name:
            conn.execute(
                "UPDATE collections SET name = ?, song_count = ?, refreshed_at = ? WHERE id = ?",
                (pl_info.name, len(pl_info.songs), now, collection_id),
            )
        else:
            conn.execute(
                "UPDATE collections SET song_count = ?, refreshed_at = ? WHERE id = ?",
                (len(pl_info.songs), now, collection_id),
            )

        # 清空旧缓存曲目，插入新的
        conn.execute("DELETE FROM collection_tracks WHERE collection_id = ?", (collection_id,))
        for idx, song in enumerate(pl_info.songs):
            conn.execute(
                "INSERT INTO collection_tracks (collection_id, title, artist, album, song_id, platform, sort_order) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (collection_id, song.title, song.artist, song.album or "", song.song_id, song.platform, idx),
            )
        conn.commit()

    return get_collection(collection_id)
