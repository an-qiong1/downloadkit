"""创作者订阅持久层测试

去重逻辑是订阅功能的命门：如果 filter_new_works 漏判，
用户的同一个视频会被反复下载。这里逐条覆盖。
"""

import sys
from pathlib import Path

import pytest

# 关键：测试必须落在临时目录，不能污染用户真实的 ~/.downloadkit/subscriptions.db
import tempfile

_real_home = Path.home


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """把数据路径重定向到临时目录"""
    home = tmp_path / "home"
    (home / ".downloadkit").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    import downloadkit.subscription as sub

    # 重置路径 + 线程局部连接
    sub._DB_DIR = home / ".downloadkit"
    sub._DB_PATH = sub._DB_DIR / "subscriptions.db"
    if hasattr(sub._local, "conn") and sub._local.conn is not None:
        sub._local.conn.close()
    sub._local.conn = None
    yield sub
    if hasattr(sub._local, "conn") and sub._local.conn is not None:
        sub._local.conn.close()
    sub._local.conn = None


SEC = "MS4wLjABAAAA_test_sec_uid"


# ---------------- 订阅 CRUD ----------------

def test_add_and_get_creator(temp_db):
    rec = temp_db.add_creator(SEC, "笔吧评测室", "https://img/a.jpg", "https://x")
    assert rec["sec_uid"] == SEC
    assert rec["nickname"] == "笔吧评测室"
    assert rec["enabled"] == 1

    got = temp_db.get_creator(SEC)
    assert got["nickname"] == "笔吧评测室"
    assert got["avatar"] == "https://img/a.jpg"


def test_add_creator_twice_updates_not_duplicates(temp_db):
    temp_db.add_creator(SEC, "旧昵称")
    temp_db.add_creator(SEC, "新昵称")

    assert len(temp_db.list_creators()) == 1
    assert temp_db.get_creator(SEC)["nickname"] == "新昵称"


def test_add_creator_rejects_empty(temp_db):
    with pytest.raises(ValueError):
        temp_db.add_creator("")
    with pytest.raises(ValueError):
        temp_db.add_creator("   ")


def test_remove_creator(temp_db):
    temp_db.add_creator(SEC, "x")
    assert temp_db.remove_creator(SEC) is True
    assert temp_db.get_creator(SEC) is None
    assert temp_db.remove_creator(SEC) is False


def test_list_creators_enabled_filter(temp_db):
    temp_db.add_creator(SEC + "_a", "A")
    temp_db.add_creator(SEC + "_b", "B")
    assert len(temp_db.list_creators()) == 2

    temp_db.set_creator_enabled(SEC + "_b", False)
    assert len(temp_db.list_creators()) == 2
    assert len(temp_db.list_creators(enabled_only=True)) == 1


def test_pause_keeps_record(temp_db):
    """暂停不等于取消，记录要留着"""
    temp_db.add_creator(SEC, "A")
    assert temp_db.set_creator_enabled(SEC, False) is True
    assert temp_db.get_creator(SEC)["enabled"] == 0


# ---------------- 去重（核心） ----------------

def test_filter_new_works_first_time_all_new(temp_db):
    ids = ["1", "2", "3"]
    assert temp_db.filter_new_works(SEC, ids) == ["1", "2", "3"]


def test_filter_new_works_second_time_all_known(temp_db):
    ids = ["1", "2", "3"]
    temp_db.mark_works_seen(SEC, [{"aweme_id": i} for i in ids])
    assert temp_db.filter_new_works(SEC, ids) == []


def test_filter_new_works_only_returns_new_ones(temp_db):
    """核心场景：老作品 + 新作品混在一起"""
    temp_db.mark_works_seen(SEC, [{"aweme_id": "1"}, {"aweme_id": "2"}])
    # 抖音主页通常最新的排前面
    assert temp_db.filter_new_works(SEC, ["4", "3", "2", "1"]) == ["4", "3"]


def test_filter_new_works_dedupes_within_batch(temp_db):
    """同一次拉取里重复的 ID 不能出现两次"""
    assert temp_db.filter_new_works(SEC, ["1", "1", "2", "1"]) == ["1", "2"]


def test_filter_new_works_preserves_order(temp_db):
    assert temp_db.filter_new_works(SEC, ["c", "a", "b"]) == ["c", "a", "b"]


def test_filter_new_works_empty_input(temp_db):
    assert temp_db.filter_new_works(SEC, []) == []
    assert temp_db.filter_new_works(SEC, None) == []


def test_filter_new_works_skips_empty_ids(temp_db):
    assert temp_db.filter_new_works(SEC, ["1", "", None]) == ["1"]


def test_works_are_scoped_per_creator(temp_db):
    """同一作品 ID 不该在不同创作者之间串味"""
    other = SEC + "_other"
    temp_db.mark_works_seen(SEC, [{"aweme_id": "999"}])
    # 另一个作者没标记过，999 仍算新
    assert temp_db.filter_new_works(other, ["999"]) == ["999"]


def test_is_work_seen(temp_db):
    assert temp_db.is_work_seen(SEC, "1") is False
    temp_db.mark_works_seen(SEC, [{"aweme_id": "1"}])
    assert temp_db.is_work_seen(SEC, "1") is True
    assert temp_db.is_work_seen(SEC, "2") is False


# ---------------- 标记 ----------------

def test_mark_works_seen_is_idempotent(temp_db):
    """轮询重试时不能因为重复写入而报错或重复计数"""
    items = [{"aweme_id": "1", "title": "A"}]
    assert temp_db.mark_works_seen(SEC, items) == 1
    assert temp_db.mark_works_seen(SEC, items) == 1   # executemany 照写
    assert len(temp_db.list_seen_works(SEC)) == 1     # 但只有一条
    assert temp_db.stats()["works_seen"] == 1


def test_mark_works_seen_ignores_missing_id(temp_db):
    assert temp_db.mark_works_seen(SEC, [{"title": "no id"}]) == 0
    assert temp_db.mark_works_seen(SEC, []) == 0


def test_mark_works_seen_truncates_long_title(temp_db):
    long = "标" * 500
    temp_db.mark_works_seen(SEC, [{"aweme_id": "1", "title": long}])
    assert len(temp_db.list_seen_works(SEC)[0]["title"]) == 200


def test_list_seen_works_newest_first(temp_db):
    temp_db.mark_works_seen(SEC, [{"aweme_id": str(i)} for i in range(5)])
    rows = temp_db.list_seen_works(SEC)
    assert len(rows) == 5
    # found_at 是秒级精度，顺序主要靠 aweme_id 倒序兜底
    assert rows[0]["aweme_id"] == "4"


def test_list_seen_works_respects_limit(temp_db):
    temp_db.mark_works_seen(SEC, [{"aweme_id": str(i)} for i in range(20)])
    assert len(temp_db.list_seen_works(SEC, limit=5)) == 5


# ---------------- 删订阅后作品记录保留 ----------------

def test_remove_creator_keeps_seen_works(temp_db):
    """暂停关注后重新加回，不能把老作品当成新的重下"""
    temp_db.mark_works_seen(SEC, [{"aweme_id": "1"}, {"aweme_id": "2"}])
    temp_db.add_creator(SEC, "A")
    temp_db.remove_creator(SEC)

    assert temp_db.get_creator(SEC) is None
    # 作品记录还在
    assert len(temp_db.list_seen_works(SEC)) == 2
    temp_db.add_creator(SEC, "A")
    assert temp_db.filter_new_works(SEC, ["1", "2", "3"]) == ["3"]


# ---------------- 检查时间戳 ----------------

def test_mark_creator_checked(temp_db):
    temp_db.add_creator(SEC, "A")
    temp_db.mark_works_seen(SEC, [{"aweme_id": "1"}])
    temp_db.mark_creator_checked(SEC, last_found="2026-09-26 12:00:00")

    rec = temp_db.get_creator(SEC)
    assert rec["last_checked"] is not None
    assert rec["last_found"] == "2026-09-26 12:00:00"
    assert rec["works_seen"] == 1


def test_mark_creator_checked_keeps_old_last_found(temp_db):
    """没抓到新作品时，不能把 last_found 清空"""
    temp_db.add_creator(SEC, "A")
    temp_db.mark_creator_checked(SEC, last_found="2026-01-01 00:00:00")
    temp_db.mark_creator_checked(SEC, last_found="")
    assert temp_db.get_creator(SEC)["last_found"] == "2026-01-01 00:00:00"


# ---------------- 总览 ----------------

def test_stats(temp_db):
    temp_db.add_creator(SEC + "_a", "A")
    temp_db.add_creator(SEC + "_b", "B")
    temp_db.set_creator_enabled(SEC + "_b", False)
    temp_db.mark_works_seen(SEC + "_a", [{"aweme_id": "1"}])

    s = temp_db.stats()
    assert s["creators"] == 2
    assert s["enabled"] == 1
    assert s["works_seen"] == 1
    assert s["db_path"].endswith("subscriptions.db")


def test_data_survives_reconnect(temp_db):
    """模拟程序重启：新连接要能读到旧数据"""
    temp_db.add_creator(SEC, "A")
    temp_db.mark_works_seen(SEC, [{"aweme_id": "1"}])

    temp_db._local.conn.close()
    temp_db._local.conn = None

    assert temp_db.get_creator(SEC)["nickname"] == "A"
    assert temp_db.filter_new_works(SEC, ["1"]) == []
