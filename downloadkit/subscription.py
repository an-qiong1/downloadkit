"""
创作者订阅 - SQLite 持久层
============================
和 collection.py（音乐歌单收藏）是两回事，别混用：
  collection  收藏「歌单」，一次性抓取曲目
  subscription 订阅「创作者」，持续追踪新作品

设计要点：
  1. 去重靠 seen_works 表。同一作者的新作品靠作品 ID 判重，
     不依赖发布时间（抖音的时间字段会随编辑变动）。
  2. 订阅表和已见作品表分开放。删订阅时作品记录可以保留
     （用户可能只是暂停关注），这样重新加回来不会重复下载。
  3. 下载状态不在这两张表里，由 download_queue 负责。
     这里只记「已发现」，避免同一套状态散落两处。

数据位置: ~/.downloadkit/subscriptions.db
"""

import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

_DB_DIR = Path.home() / ".downloadkit"
_DB_PATH = _DB_DIR / "subscriptions.db"

_local = threading.local()
_db_lock = threading.Lock()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _get_db() -> sqlite3.Connection:
    """取当前线程的数据库连接（SQLite 连接不能跨线程用）"""
    if not hasattr(_local, "conn") or _local.conn is None:
        _DB_DIR.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), detect_types=sqlite3.PARSE_DECLTYPES)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


def _init_db() -> None:
    conn = _get_db()
    conn.executescript("""
        -- 订阅的创作者
        CREATE TABLE IF NOT EXISTS creators (
            sec_uid      TEXT PRIMARY KEY,          -- 抖音创作者唯一 ID
            nickname     TEXT NOT NULL DEFAULT '',
            avatar       TEXT NOT NULL DEFAULT '',
            home_url     TEXT NOT NULL DEFAULT '',
            enabled      INTEGER NOT NULL DEFAULT 1, -- 0=暂停轮询
            created_at   TEXT NOT NULL,
            last_checked TEXT,                      -- 上次检查时间
            last_found   TEXT,                      -- 上次发现的最新作品时间
            works_seen   INTEGER NOT NULL DEFAULT 0, -- 累计发现作品数
            baseline_max_id TEXT NOT NULL DEFAULT '' -- 基线水位线（见 set_creator_baseline）
        );

        -- 已发现的作品（去重表）
        -- 不随订阅删除而清空：用户暂停关注后重新加回，不会重复下载老作品
        CREATE TABLE IF NOT EXISTS seen_works (
            aweme_id    TEXT NOT NULL,
            sec_uid     TEXT NOT NULL,
            title       TEXT NOT NULL DEFAULT '',
            found_at    TEXT NOT NULL,
            task_id     TEXT,                       -- 关联的下载任务
            PRIMARY KEY (aweme_id, sec_uid)
        );

        CREATE INDEX IF NOT EXISTS idx_seen_sec_uid ON seen_works(sec_uid);
        CREATE INDEX IF NOT EXISTS idx_seen_found_at ON seen_works(found_at DESC);
        CREATE INDEX IF NOT EXISTS idx_creators_enabled ON creators(enabled);
    """)
    _migrate(conn)
    conn.commit()


def _migrate(conn: sqlite3.Connection) -> None:
    """给老库补列。

    CREATE TABLE IF NOT EXISTS 对已存在的表不生效，所以新增字段
    必须单独 ALTER。加过就跳过，重复执行安全。
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(creators)")}
    if "baseline_max_id" not in cols:
        conn.execute(
            "ALTER TABLE creators ADD COLUMN baseline_max_id "
            "TEXT NOT NULL DEFAULT ''"
        )


# ==================================================================
# 创作者订阅
# ==================================================================

def add_creator(sec_uid: str, nickname: str = "", avatar: str = "",
                home_url: str = "") -> dict:
    """订阅一个创作者。已存在则更新资料，不报错。

    Args:
        sec_uid: 抖音创作者唯一 ID
        nickname: 昵称
        avatar: 头像 URL
        home_url: 主页地址

    Returns:
        订阅记录 dict
    """
    sec_uid = (sec_uid or "").strip()
    if not sec_uid:
        raise ValueError("sec_uid 不能为空")

    with _db_lock:
        _init_db()
        conn = _get_db()
        conn.execute(
            """
            INSERT INTO creators (sec_uid, nickname, avatar, home_url, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(sec_uid) DO UPDATE SET
                nickname = excluded.nickname,
                avatar   = excluded.avatar,
                home_url = excluded.home_url
            """,
            (sec_uid, nickname or "", avatar or "", home_url or "", _now()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM creators WHERE sec_uid = ?", (sec_uid,)
        ).fetchone()
    return dict(row)


def remove_creator(sec_uid: str) -> bool:
    """取消订阅。seen_works 里的记录保留。

    Returns:
        是否真的删掉了一条
    """
    with _db_lock:
        _init_db()
        conn = _get_db()
        cur = conn.execute("DELETE FROM creators WHERE sec_uid = ?", (sec_uid,))
        conn.commit()
        return cur.rowcount > 0


def list_creators(enabled_only: bool = False) -> list[dict]:
    """列出所有订阅的创作者"""
    with _db_lock:
        _init_db()
        conn = _get_db()
        sql = "SELECT * FROM creators"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY created_at DESC"
        rows = conn.execute(sql).fetchall()
    return [dict(r) for r in rows]


def get_creator(sec_uid: str) -> Optional[dict]:
    with _db_lock:
        _init_db()
        conn = _get_db()
        row = conn.execute(
            "SELECT * FROM creators WHERE sec_uid = ?", (sec_uid,)
        ).fetchone()
    return dict(row) if row else None


def set_creator_enabled(sec_uid: str, enabled: bool) -> bool:
    """暂停/恢复某个创作者的轮询"""
    with _db_lock:
        _init_db()
        conn = _get_db()
        cur = conn.execute(
            "UPDATE creators SET enabled = ? WHERE sec_uid = ?",
            (1 if enabled else 0, sec_uid),
        )
        conn.commit()
        return cur.rowcount > 0


def mark_creator_checked(sec_uid: str, works_seen: int = 0,
                         last_found: str = "") -> None:
    """记录「刚检查过这个创作者」

    Args:
        sec_uid: 创作者 ID
        works_seen: 累计已发现作品数
        last_found: 最新作品的发布时间
    """
    with _db_lock:
        _init_db()
        conn = _get_db()
        conn.execute(
            """
            UPDATE creators
               SET last_checked = ?,
                   last_found   = COALESCE(NULLIF(?, ''), last_found),
                   works_seen   = ? + (
                       SELECT COUNT(*) FROM seen_works WHERE sec_uid = ?
                   )
             WHERE sec_uid = ?
            """,
            (_now(), last_found or "", works_seen, sec_uid, sec_uid),
        )
        conn.commit()


def set_creator_baseline(sec_uid: str, max_aweme_id: str) -> bool:
    """记录基线水位线：订阅那一刻主页最新作品的 aweme_id。

    为什么需要它（不能只靠「作品是否已见过」判新）：

      抖音主页是个滑动窗口，每次滚动落点不同，窗口尾部的组成
      会变。实测同一个人、同样滚动 3 次，两次抓回来 62 条里
      只有 54 条重合 —— 尾部混进了 8 条**早就发过的老作品**。
      纯集合差集会把这 8 条当成「新作品」，反复点检查就会把
      老视频一条条下下来。

      解决办法：首次基线时记下当时最新的作品 ID 作为水位线。
      之后只有 ID 大于水位线的才算「订阅之后新发的」；
      ID 小于等于水位线的，无论是否见过，一律不下载。

    aweme_id 是雪花算法生成，随发布时间单调递增（实测抓取
    顺序严格等于 ID 降序），所以「ID > 水位线」等价于
    「比订阅时更新」。

    这个值只写一次，之后不再更新 —— 更新了就会把「还没下载完
    的真新作品」一起压到水位线以下，导致漏下。

    Args:
        sec_uid: 创作者 ID
        max_aweme_id: 基线时抓到的最大 aweme_id

    Returns:
        是否写入成功
    """
    sec_uid = (sec_uid or "").strip()
    if not sec_uid or not max_aweme_id:
        return False

    with _db_lock:
        _init_db()
        conn = _get_db()
        # 只在水位线还空着时写入：已有的不覆盖，rowcount 也如实反映
        # 「这次到底写没写进去」
        cur = conn.execute(
            """
            UPDATE creators
               SET baseline_max_id = ?
             WHERE sec_uid = ? AND baseline_max_id = ''
            """,
            (str(max_aweme_id), sec_uid),
        )
        conn.commit()
        return cur.rowcount > 0


def split_new_vs_drift(sec_uid: str, aweme_ids: list[str]) -> tuple[list, list]:
    """把抓到的作品分成「真新」和「滑窗漂移进来的老作品」。

    真新 = 从没见过 且 ID > 基线水位线   → 进下载队列
    漂移 = 从没见过 且 ID <= 基线水位线  → 标记已见但绝不下载

    Args:
        sec_uid: 创作者 ID
        aweme_ids: 本次抓到的作品 ID（保持信息流顺序）

    Returns:
        (真新列表, 漂移列表)
    """
    if not aweme_ids:
        return [], []

    unique = list(dict.fromkeys(a for a in aweme_ids if a))

    with _db_lock:
        _init_db()
        conn = _get_db()
        row = conn.execute(
            "SELECT baseline_max_id FROM creators WHERE sec_uid = ?",
            (sec_uid,),
        ).fetchone()
        watermark = (row["baseline_max_id"] if row else "") or ""

        placeholders = ",".join("?" * len(unique))
        known = {
            r["aweme_id"]
            for r in conn.execute(
                f"SELECT aweme_id FROM seen_works "
                f"WHERE sec_uid = ? AND aweme_id IN ({placeholders})",
                [sec_uid] + unique,
            )
        }

    unknown = [a for a in unique if a not in known]
    if not watermark:
        # 还没建立基线：退回纯集合差集，不做水位线判断。
        # 正常流程 check_creator 会先建基线，走到这里属于异常，
        # 此时宁可全部当新作品（跟旧行为一致），也不要误吞。
        return unknown, []

    def _big(a: str) -> bool:
        try:
            return int(a) > int(watermark)
        except (TypeError, ValueError):
            return False

    fresh = [a for a in unknown if _big(a)]
    drift = [a for a in unknown if not _big(a)]
    return fresh, drift


# ==================================================================
# 作品去重
# ==================================================================

def filter_new_works(sec_uid: str, aweme_ids: list[str]) -> list[str]:
    """从一批作品 ID 里筛出「以前没见过的」。

    这是订阅功能的核心去重入口。每次轮询拉到的作品列表
    都要过这一遍，只有新出现的才进下载队列。

    Args:
        sec_uid: 创作者 ID
        aweme_ids: 本次抓到的作品 ID 列表

    Returns:
        从未见过过的作品 ID（保持原顺序，自动去重）
    """
    if not aweme_ids:
        return []

    # 先去掉本次内部的重复
    unique = list(dict.fromkeys(a for a in aweme_ids if a))

    with _db_lock:
        _init_db()
        conn = _get_db()
        placeholders = ",".join("?" * len(unique))
        rows = conn.execute(
            f"SELECT aweme_id FROM seen_works "
            f"WHERE sec_uid = ? AND aweme_id IN ({placeholders})",
            [sec_uid] + unique,
        ).fetchall()
        known = {r["aweme_id"] for r in rows}

    return [a for a in unique if a not in known]


def mark_works_seen(sec_uid: str, items: list[dict]) -> int:
    """把作品标记为「已发现」。

    必须在作品成功入队后立刻调用，否则下一轮轮询会重复入队。

    Args:
        sec_uid: 创作者 ID
        items: [{"aweme_id": ..., "title": ..., "task_id": ...}, ...]

    Returns:
        新写入的记录数
    """
    if not items:
        return 0

    with _db_lock:
        _init_db()
        conn = _get_db()
        rows = [
            (
                it.get("aweme_id", ""),
                sec_uid,
                (it.get("title") or "")[:200],
                _now(),
                it.get("task_id"),
            )
            for it in items
            if it.get("aweme_id")
        ]
        if not rows:
            return 0
        # INSERT OR IGNORE：并发轮询时同一条被插两次不报错
        conn.executemany(
            """
            INSERT OR IGNORE INTO seen_works
                (aweme_id, sec_uid, title, found_at, task_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
        return len(rows)


def list_seen_works(sec_uid: str, limit: int = 50) -> list[dict]:
    """列出某创作者已发现的作品（按发现时间倒序）"""
    with _db_lock:
        _init_db()
        conn = _get_db()
        rows = conn.execute(
            "SELECT * FROM seen_works WHERE sec_uid = ? "
            "ORDER BY found_at DESC, aweme_id DESC LIMIT ?",
            (sec_uid, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def is_work_seen(sec_uid: str, aweme_id: str) -> bool:
    with _db_lock:
        _init_db()
        conn = _get_db()
        row = conn.execute(
            "SELECT 1 FROM seen_works WHERE sec_uid = ? AND aweme_id = ?",
            (sec_uid, aweme_id),
        ).fetchone()
    return row is not None


def stats() -> dict:
    """总览，给界面顶部显示"""
    with _db_lock:
        _init_db()
        conn = _get_db()
        creators = conn.execute("SELECT COUNT(*) c FROM creators").fetchone()["c"]
        enabled = conn.execute(
            "SELECT COUNT(*) c FROM creators WHERE enabled = 1"
        ).fetchone()["c"]
        works = conn.execute("SELECT COUNT(*) c FROM seen_works").fetchone()["c"]
    return {
        "creators": creators,
        "enabled": enabled,
        "works_seen": works,
        "db_path": str(_DB_PATH),
    }
