"""P2-1 每创作者下载范围

范围三取值（本期；since_date 因缺发布时间数据源缓做，见 PLAN）：
    only_new    只下订阅后新发的（默认，等于改造前的行为）
    backfill_n  往回补 N 个历史作品 —— N 是**累计上限**，不是每轮上限
    all         水位线之下的历史全补下，按单轮上限分批

三条必须守住的不变量：

  1. **反复检查绝不重复下载**（订阅功能的命门）。补下候选由
     list_backfill_candidates 筛（水位线之下 + task_id 为空），
     入队成功才写 task_id —— 所以第二轮只会捡第一轮没下成的。
  2. **增量优先**：新作品有时效性，max_new 的配额先给增量，
     余量才轮到补下；余量为 0 时补下一个都不能下。
  3. **download=False 什么都不产生**：探针不能触发任何入队。

另外锁死一个配额语义：`_budget(max_new, used)` 里 max_new<=0 → -1（不限），
0 → 没有余量。这两者混起来会让增量吃满配额时把历史一口气全塞进队列。
"""

import sqlite3
from pathlib import Path

import pytest

import downloadkit.subscription as store
import downloadkit.subscription_service as svc


SEC = "MS4wLjABAAAA_test_download_scope"

STATIC = Path(__file__).resolve().parent.parent / "downloadkit" / "static"


def _ids(n, start=1):
    """n 个作品 ID，按**数值**降序（模拟抖音主页的排列）。

    注意不能用 sorted(str, reverse=True)：那是字典序，
    '9' 会排在 '10' 前面，测出来的顺序和真实主页对不上。
    """
    return [str(i) for i in range(start + n - 1, start - 1, -1)]


class FakeBrowser:
    """替身浏览器：只提供 check_login_via_api 和 fetch_creator"""

    def __init__(self, ids, nickname="测试博主", avatar=""):
        self.ids = list(ids)
        self.nickname = nickname
        self.avatar = avatar

    async def check_login_via_api(self):
        return True, "已登录: 测试 / uid=1"

    async def fetch_creator(self, sec_uid, max_scrolls=5):
        from downloadkit.douyin_browser import CreatorInfo
        return CreatorInfo(sec_uid=sec_uid, nickname=self.nickname,
                           avatar=self.avatar, video_ids=list(self.ids))


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / ".downloadkit").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(store.Path, "home", staticmethod(lambda: home))
    store._DB_DIR = home / ".downloadkit"
    store._DB_PATH = store._DB_DIR / "subscriptions.db"
    if getattr(store._local, "conn", None) is not None:
        store._local.conn.close()
    store._local.conn = None

    holder = {"browser": None, "enqueued": []}

    def fake_browser():
        return holder["browser"]

    async def fake_enqueue(aweme_id, sec_uid, nickname):
        holder["enqueued"].append(aweme_id)
        return True, f"sub_{sec_uid[:12]}_{aweme_id}", ""

    monkeypatch.setattr(svc, "_browser", fake_browser)
    monkeypatch.setattr(svc, "_enqueue_video", fake_enqueue)
    yield holder
    if getattr(store._local, "conn", None) is not None:
        store._local.conn.close()
    store._local.conn = None


def _ok_enqueue(env):
    """造一个成功的入队替身（用于先失败后恢复的场景）"""
    async def ok(aweme_id, sec_uid, nickname):
        env["enqueued"].append(aweme_id)
        return True, f"sub_{sec_uid[:12]}_{aweme_id}", ""
    return ok


# ---------------- schema 与取值校验 ----------------

def test_new_subscription_defaults_to_only_new(env):
    """默认范围必须是 only_new —— 老订阅升级后行为一个字都不变"""
    store.add_creator(SEC, "x")
    rec = store.get_creator(SEC)
    assert rec["download_scope"] == "only_new"
    assert rec["scope_param"] == ""


def test_migrate_adds_scope_columns_to_old_db(env):
    """升级前的老库要能被 _init_db 补上新列，重复执行安全"""
    conn = sqlite3.connect(str(store._DB_PATH))
    conn.execute(
        "CREATE TABLE creators ("
        " sec_uid TEXT PRIMARY KEY, nickname TEXT NOT NULL DEFAULT '',"
        " avatar TEXT NOT NULL DEFAULT '', home_url TEXT NOT NULL DEFAULT '',"
        " enabled INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,"
        " last_checked TEXT, last_found TEXT,"
        " works_seen INTEGER NOT NULL DEFAULT 0,"
        " baseline_max_id TEXT NOT NULL DEFAULT '')"
    )
    conn.commit()
    conn.close()

    store._init_db()
    store._init_db()          # 幂等：跑第二遍不该炸

    conn = sqlite3.connect(str(store._DB_PATH))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(creators)")}
    conn.close()
    assert "download_scope" in cols, "老库没补上 download_scope"
    assert "scope_param" in cols, "老库没补上 scope_param"


def test_scope_validation(env):
    store.add_creator(SEC, "x")

    store.set_creator_scope(SEC, "backfill_n", "5")
    rec = store.get_creator(SEC)
    assert rec["download_scope"] == "backfill_n"
    assert rec["scope_param"] == "5"

    with pytest.raises(ValueError):
        store.set_creator_scope(SEC, "since_date", "2026-01-01")  # 本期未实现
    with pytest.raises(ValueError):
        store.set_creator_scope(SEC, "all_the_things")
    with pytest.raises(ValueError):
        store.set_creator_scope(SEC, "backfill_n", "abc")
    with pytest.raises(ValueError):
        store.set_creator_scope(SEC, "backfill_n", "0")
    with pytest.raises(ValueError):
        store.set_creator_scope(SEC, "backfill_n", "10000")
    with pytest.raises(ValueError):
        store.set_creator_scope("MS4wLjABAAAA_not_subscribed", "all")


def test_switching_away_from_backfill_clears_param(env):
    """换成不需要参数的范围时清掉残留 N，免得数据库里躺着没人读的值"""
    store.add_creator(SEC, "x")
    store.set_creator_scope(SEC, "backfill_n", "5")
    store.set_creator_scope(SEC, "all")
    assert store.get_creator(SEC)["scope_param"] == ""


# ---------------- only_new：等于改造前的行为 ----------------

@pytest.mark.asyncio
async def test_only_new_never_touches_history(env):
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")

    r1 = await svc.check_creator(SEC, download=True, max_new=0)
    assert r1["queued"] == 0
    assert env["enqueued"] == [], "默认范围首查不该下任何历史作品"

    env["browser"] = FakeBrowser(_ids(10))
    r2 = await svc.check_creator(SEC, download=True, max_new=0)
    assert r2["queued"] == 0
    assert env["enqueued"] == []
    assert r2["message"] == "没有新作品"


# ---------------- backfill_n ----------------

@pytest.mark.asyncio
async def test_backfill_n_downloads_n_on_first_check(env):
    """订阅时就选了范围，建基线当轮就该开始补，不用等下一轮"""
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")
    store.set_creator_scope(SEC, "backfill_n", "3")

    r = await svc.check_creator(SEC, download=True, max_new=0)

    assert r["baselined"] is True
    assert r["queued"] == 3
    assert r["backfilled"] == 3
    assert r["backfill_left"] == 0, "N 已补满，不该还报剩余"
    assert len(env["enqueued"]) == 3
    assert "按范围补下 3 个历史作品" in r["message"]
    # 补的是最新的 3 个（ID 降序取前 3）
    assert set(env["enqueued"]) == {"10", "9", "8"}


@pytest.mark.asyncio
async def test_backfill_n_is_cumulative_cap_not_per_round(env):
    """N 是累计上限：每轮补 2，5 个的额度要分 3 轮走完，第 4 轮必须停"""
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")
    store.set_creator_scope(SEC, "backfill_n", "5")

    counts = []
    for _ in range(4):
        env["browser"] = FakeBrowser(_ids(10))
        r = await svc.check_creator(SEC, download=True, max_new=2)
        counts.append(r.get("backfilled", 0))

    assert counts == [2, 2, 1, 0], f"累计上限没生效：{counts}"
    assert len(env["enqueued"]) == 5
    assert len(set(env["enqueued"])) == 5, "出现重复下载"


@pytest.mark.asyncio
async def test_backfill_n_capped_by_available_candidates(env):
    """博主作品不够 N 个时，有多少补多少，不报错不重复"""
    env["browser"] = FakeBrowser(_ids(3))
    store.add_creator(SEC, "x")
    store.set_creator_scope(SEC, "backfill_n", "10")

    r = await svc.check_creator(SEC, download=True, max_new=0)
    assert r["backfilled"] == 3
    assert r["backfill_left"] == 7, "还差 7 个没补满（博主只有 3 个作品）"

    env["browser"] = FakeBrowser(_ids(3))
    r2 = await svc.check_creator(SEC, download=True, max_new=0)
    assert r2.get("backfilled", 0) == 0, "候选已空，不该再下"
    assert len(env["enqueued"]) == 3


# ---------------- all ----------------

@pytest.mark.asyncio
async def test_all_backfills_in_batches_by_max_new(env):
    """all 按单轮上限分批，几轮之内补完且一轮不重复"""
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")
    store.set_creator_scope(SEC, "all")

    got = []
    rounds = []
    for _ in range(5):
        env["browser"] = FakeBrowser(_ids(10))
        r = await svc.check_creator(SEC, download=True, max_new=3)
        rounds.append(r.get("backfilled", 0))
        got = env["enqueued"][:]        # 每轮快照，最后一并断言

    assert rounds == [3, 3, 3, 1, 0], f"分批不对：{rounds}"
    assert len(got) == 10
    assert len(set(got)) == 10, "补下过程出现重复下载"


@pytest.mark.asyncio
async def test_all_unlimited_when_max_new_zero(env):
    env["browser"] = FakeBrowser(_ids(6))
    store.add_creator(SEC, "x")
    store.set_creator_scope(SEC, "all")

    r = await svc.check_creator(SEC, download=True, max_new=0)
    assert r["backfilled"] == 6
    assert r["backfill_left"] == 0


# ---------------- 优先级与配额 ----------------

@pytest.mark.asyncio
async def test_fresh_takes_priority_over_backfill(env):
    """max_new=1 且同时有新作品时，配额给新作品，历史一个都不许下

    这条锁的是配额 bug：余量算出来是 0，若把 0 当成「不限」，
    这一轮会把 10 个历史全塞进队列。
    """
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC, download=True)      # 建基线（only_new 不补）

    store.set_creator_scope(SEC, "all")
    env["browser"] = FakeBrowser(["11"] + _ids(10))
    r = await svc.check_creator(SEC, download=True, max_new=1)

    assert r["new_count"] == 1
    assert r["queued"] == 1
    assert env["enqueued"] == ["11"], "配额必须优先给新作品"
    assert r.get("backfill_left") == 10, "历史留给以后，一个都不能少记"


@pytest.mark.asyncio
async def test_backfill_gets_the_leftover_slots(env):
    """增量没用完配额时，余量归补下"""
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC, download=True)      # 基线

    store.set_creator_scope(SEC, "all")
    # 1 个新作品 + 10 个历史，max_new=4 → 新 1 + 补 3
    env["browser"] = FakeBrowser(["11"] + _ids(10))
    r = await svc.check_creator(SEC, download=True, max_new=4)

    assert r["new_count"] == 1
    assert r.get("backfilled") == 3, "余量 3 应该全给补下"
    assert r["queued"] == 4


# ---------------- 命门：反复检查不重复 ----------------

@pytest.mark.asyncio
async def test_repeated_checks_never_duplicate(env):
    """增量 + 补下混着跑三轮，一个作品都不允许入队两次"""
    stock = _ids(10)
    env["browser"] = FakeBrowser(stock)
    store.add_creator(SEC, "x")
    store.set_creator_scope(SEC, "backfill_n", "5")

    # 第 1 轮：建基线 + 补 5 个历史
    await svc.check_creator(SEC, download=True, max_new=0)
    # 第 2 轮：博主发了 2 个新的（补下额度已满，不该再补）
    env["browser"] = FakeBrowser(["12", "11"] + stock)
    await svc.check_creator(SEC, download=True, max_new=0)
    # 第 3 轮：什么都没变
    env["browser"] = FakeBrowser(["12", "11"] + stock)
    r3 = await svc.check_creator(SEC, download=True, max_new=0)

    enqueued = env["enqueued"]
    assert len(enqueued) == len(set(enqueued)), f"重复入队：{enqueued}"
    # 应该下的：N=5 的历史（最新 5 个）+ 2 个新作品
    assert set(enqueued) == {"10", "9", "8", "7", "6", "12", "11"}
    assert r3["queued"] == 0, "第 3 轮无事可做"
    assert r3["message"] == "没有新作品"


@pytest.mark.asyncio
async def test_reenqueue_after_scope_raised(env):
    """改大 N 后能继续补，且不会重下已经下过的"""
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")
    store.set_creator_scope(SEC, "backfill_n", "3")
    await svc.check_creator(SEC, download=True, max_new=0)

    store.set_creator_scope(SEC, "backfill_n", "6")
    env["browser"] = FakeBrowser(_ids(10))
    r = await svc.check_creator(SEC, download=True, max_new=0)

    assert r.get("backfilled") == 3, "额度从 3 提到 6，应补 3 个"
    enqueued = env["enqueued"]
    assert len(enqueued) == len(set(enqueued)), f"重复入队：{enqueued}"
    assert set(enqueued) == {"10", "9", "8", "7", "6", "5"}


@pytest.mark.asyncio
async def test_enqueue_failure_keeps_candidate_for_next_round(env, monkeypatch):
    """补下入队失败的必须留在未下状态，下一轮重试"""
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")
    store.set_creator_scope(SEC, "backfill_n", "3")

    async def failing(aweme_id, sec_uid, nickname):
        return False, "", "队列满了"

    monkeypatch.setattr(svc, "_enqueue_video", failing)
    r = await svc.check_creator(SEC, download=True, max_new=0)

    assert r["backfilled"] == 0
    assert r["backfill_left"] == 3, "一个都没成，3 个额度都得留着"
    assert env["enqueued"] == []

    # 恢复后重试，候选还在
    monkeypatch.setattr(svc, "_enqueue_video", _ok_enqueue(env))
    env["browser"] = FakeBrowser(_ids(10))
    r2 = await svc.check_creator(SEC, download=True, max_new=0)
    assert r2["backfilled"] == 3


# ---------------- 探针与服务入口 ----------------

@pytest.mark.asyncio
async def test_download_false_never_backfills(env):
    """download=False 是探针，任何情况下都不该产生任务"""
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")
    store.set_creator_scope(SEC, "backfill_n", "3")

    r1 = await svc.check_creator(SEC, download=False, max_new=0)
    assert r1["queued"] == 0
    assert env["enqueued"] == [], "首查探针就开补了"

    env["browser"] = FakeBrowser(_ids(10))
    r2 = await svc.check_creator(SEC, download=False, max_new=0)
    assert r2["queued"] == 0
    assert env["enqueued"] == []


@pytest.mark.asyncio
async def test_update_scope_service_roundtrip(env):
    store.add_creator(SEC, "x")

    rec = await svc.update_scope(SEC, "backfill_n", "7")
    assert rec["download_scope"] == "backfill_n"
    assert rec["scope_param"] == "7"

    with pytest.raises(ValueError):
        await svc.update_scope(SEC, "nope")
    with pytest.raises(ValueError):
        await svc.update_scope("MS4wLjABAAAA_nobody", "all")


@pytest.mark.asyncio
async def test_scope_change_takes_effect_on_next_check(env):
    """only_new 查过之后改成范围，下一次检查开始补"""
    env["browser"] = FakeBrowser(_ids(8))
    store.add_creator(SEC, "x")
    r1 = await svc.check_creator(SEC, download=True, max_new=0)
    assert r1["queued"] == 0

    await svc.update_scope(SEC, "backfill_n", "4")
    env["browser"] = FakeBrowser(_ids(8))
    r2 = await svc.check_creator(SEC, download=True, max_new=0)
    assert r2.get("backfilled") == 4
    assert len(set(env["enqueued"])) == 4


# ---------------- 配额助手 ----------------

def test_budget_semantics():
    """-1 = 不限，0 = 没有余量 —— 混起来会一口气塞爆队列"""
    assert svc._budget(0) == -1, "max_new=0 是不限"
    assert svc._budget(-1) == -1
    assert svc._budget(4) == 4, "没消耗过，满额给补下"
    assert svc._budget(4, 1) == 3
    assert svc._budget(4, 4) == 0, "增量吃满，补下没份"
    assert svc._budget(4, 9) == 0, "消耗超过配额也不能变负数"


# ---------------- 界面与路由 ----------------

def test_scope_route_registered():
    """/{sec}/scope 必须注册成自己的路由，不能被其它参数化路由吃掉"""
    from server import app

    sec = "MS4wLjABAAAA9jVXMI9P5Gye45GdF88OIr1Frk2Gf1q7PS416m3PxGo"
    hit = None
    for r in app.routes:
        if not (getattr(r, "methods", None) and "POST" in r.methods):
            continue
        regex = getattr(r, "path_regex", None)
        if regex and regex.match(f"/api/subscriptions/{sec}/scope"):
            hit = r
            break
    assert hit is not None, "POST /api/subscriptions/{sec}/scope 没注册"
    assert hit.path == "/api/subscriptions/{sec_uid}/scope"


def test_scope_choices_rendered_in_card():
    """卡片里必须渲染出三种范围，且走 /scope 端点 + change 事件"""
    js = (STATIC / "js" / "subscriptions.js").read_text(encoding="utf-8")
    for label in ("仅新作品", "往回补 N 个", "全部补下"):
        assert label in js, f"订阅卡片缺范围选项「{label}」"
    assert "/scope'" in js or '/scope"' in js, "前端没调用 /scope 端点"
    assert "sub-scope" in js
    # 数字框要等失焦/回车才触发 change，绑定方式不能写错
    assert "addEventListener('change'" in js, "范围控件没绑 change 事件"


def test_scope_css_exists():
    css = (STATIC / "css" / "main.css").read_text(encoding="utf-8")
    assert ".sub-scope" in css, "main.css 缺 .sub-scope"
    assert ".sub-scope-n" in css, "main.css 缺 .sub-scope-n"
