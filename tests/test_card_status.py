"""P2-4 订阅卡片状态：上次检查时间 + 结果或中文失败原因

三条硬约束：

  1. **失败绝不写 last_checked** —— 首查判断 `if not rec["last_checked"]`
     靠它判「还没建基线」。失败也写的话，首查失败 → 下次被当成
     已建过基线 → 走后续检查分支 → 水位线是空的，行为完全跑偏。
     所以成败都更新的是新加的 last_attempt / last_result 两列。
  2. **中断时只有真正被检查到的那个创作者写失败** —— RateLimited /
     LoginRequired 会中断整轮，后面没轮到的创作者没被检查过，
     不能给它们写「失败」（它们上次的成功状态还有效）。
  3. **暂停的不写状态** —— skipped 是「没检查」，不是一次结果。
"""

from pathlib import Path

import pytest

import downloadkit.subscription as store
import downloadkit.subscription_service as svc
from downloadkit.douyin_browser import RateLimited

SEC = "MS4wLjABAAAA_test_card_status"
OTHER = "MS4wLjABAAAA_test_card_status_b"

STATIC = Path(__file__).resolve().parent.parent / "downloadkit" / "static"


def _ids(n, start=1):
    return [str(i) for i in range(start + n - 1, start - 1, -1)]


class FakeBrowser:
    def __init__(self, ids=()):
        self.ids = list(ids)

    async def check_login_via_api(self):
        return True, "已登录: 测试 / uid=1"

    async def fetch_creator(self, sec_uid, max_scrolls=5):
        from downloadkit.douyin_browser import CreatorInfo
        return CreatorInfo(sec_uid=sec_uid, nickname="测试博主", avatar="",
                           video_ids=list(self.ids))


class BoomBrowser(FakeBrowser):
    async def fetch_creator(self, sec_uid, max_scrolls=5):
        raise RuntimeError("页面超时")


class RateLimitBrowser(FakeBrowser):
    async def fetch_creator(self, sec_uid, max_scrolls=5):
        raise RateLimited("触发验证码中间页")


class NoLoginBrowser(FakeBrowser):
    async def check_login_via_api(self):
        raise svc.LoginRequired("登录已失效")


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
        return True, f"sub_{sec_uid[:12]}", ""

    monkeypatch.setattr(svc, "_browser", fake_browser)
    monkeypatch.setattr(svc, "_enqueue_video", fake_enqueue)
    yield holder
    if getattr(store._local, "conn", None) is not None:
        store._local.conn.close()
    store._local.conn = None


# ---------------- 迁移与 mark_creator_result ----------------

def test_migrate_adds_status_columns(env):
    """老库要补上两列，重复执行安全"""
    import sqlite3
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
    store._init_db()

    conn = sqlite3.connect(str(store._DB_PATH))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(creators)")}
    conn.close()
    assert "last_attempt" in cols, "老库没补上 last_attempt"
    assert "last_result" in cols, "老库没补上 last_result"


def test_mark_creator_result_writes_and_tolerates_missing(env):
    store.add_creator(SEC, "x")
    assert store.mark_creator_result(SEC, "没有新作品") is True
    rec = store.get_creator(SEC)
    assert rec["last_result"] == "没有新作品"
    assert rec["last_attempt"], "尝试时间没写"
    assert rec["last_checked"] is None, "mark_creator_result 不许碰 last_checked"

    # 订阅不存在 → 静默 False，不能再炸一次（单查 404 分支会走到）
    assert store.mark_creator_result("no_such_sec", "失败：x") is False


# ---------------- 成功路径 ----------------

@pytest.mark.asyncio
async def test_baselined_writes_status(env):
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")

    r = await svc.check_creator(SEC, download=True)

    assert r["baselined"] is True
    rec = store.get_creator(SEC)
    assert "已建立基线" in rec["last_result"], rec["last_result"]
    assert "10 个存量" in rec["last_result"], "存量数没进状态"
    assert rec["last_checked"], "成功必须更新 last_checked"
    assert rec["last_attempt"]


@pytest.mark.asyncio
async def test_no_new_works_writes_status(env):
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC, download=True)

    env["browser"] = FakeBrowser(_ids(10))
    r = await svc.check_creator(SEC, download=True)

    assert r["new_count"] == 0
    assert store.get_creator(SEC)["last_result"] == "没有新作品"


@pytest.mark.asyncio
async def test_new_works_writes_status(env):
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC, download=True)

    env["browser"] = FakeBrowser(["11"] + _ids(10))
    await svc.check_creator(SEC, download=True, max_new=1)

    assert store.get_creator(SEC)["last_result"] == \
        "发现 1 个新作品，入队 1 个"


@pytest.mark.asyncio
async def test_probe_writes_status(env):
    """探针（download=False）也算检查过，卡片要显示它发现了什么"""
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC, download=True)

    env["browser"] = FakeBrowser(["11"] + _ids(10))
    await svc.check_creator(SEC, download=False)

    assert store.get_creator(SEC)["last_result"] == \
        "发现 1 个新作品（本次不下载）"
    assert env["enqueued"] == [], "探针不许入队"


@pytest.mark.asyncio
async def test_skipped_creator_status_untouched(env):
    """暂停 = 没检查，不许把上次的状态覆盖掉"""
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC, download=True)          # 写一条成功状态

    store.set_creator_enabled(SEC, False)
    r = await svc.check_creator(SEC, download=True)

    assert r.get("skipped") is True
    rec = store.get_creator(SEC)
    assert "已建立基线" in rec["last_result"], "暂停把状态冲掉了"


# ---------------- 失败路径（命门） ----------------

@pytest.mark.asyncio
async def test_first_check_failure_keeps_baseline_semantics(env):
    """命门：首查失败后 last_checked 必须仍是空 ——
    否则下次被当成「已建过基线」，水位线判断整个跑偏"""
    env["browser"] = BoomBrowser()
    store.add_creator(SEC, "x")

    r = await svc.check_all()

    rec = store.get_creator(SEC)
    assert rec["last_checked"] is None, "失败写了 last_checked，基线判断被污染！"
    assert rec["last_result"].startswith("失败"), rec["last_result"]
    assert rec["last_attempt"], "失败也要记尝试时间"
    assert r["errors"] == 1

    # 第二次成功：必须还走建基线分支
    env["browser"] = FakeBrowser(_ids(10))
    r2 = await svc.check_all()
    assert r2["results"][0].get("baselined") is True, "首查失败后基线判断丢了"


@pytest.mark.asyncio
async def test_rate_limited_writes_only_checked_creator(env):
    """风控中断整轮：只写被检查到的那个，后面的不许写"""
    env["browser"] = RateLimitBrowser()
    store.add_creator(SEC, "A")
    store.add_creator(OTHER, "B")
    # B 先成功建立一条基线状态，A 被风控时 B 不该再被动到
    env["browser"] = FakeBrowser(_ids(10))
    await svc.check_creator(OTHER, download=True)
    before = store.get_creator(OTHER)

    env["browser"] = RateLimitBrowser()
    r = await svc.check_all()

    assert r["rate_limited"] is True
    a = store.get_creator(SEC)
    assert a["last_result"].startswith("失败"), a["last_result"]
    assert a["last_checked"] is None, "风控失败写了 last_checked"

    b = store.get_creator(OTHER)
    assert b["last_attempt"] == before["last_attempt"], "没轮到的被写了状态"
    assert b["last_result"] == before["last_result"]


@pytest.mark.asyncio
async def test_login_required_writes_failure(env):
    env["browser"] = NoLoginBrowser()
    store.add_creator(SEC, "x")

    r = await svc.check_all()

    assert r["needs_login"] is True
    rec = store.get_creator(SEC)
    assert rec["last_result"].startswith("失败"), rec["last_result"]
    assert rec["last_checked"] is None


@pytest.mark.asyncio
async def test_failure_then_recovery_updates_status(env):
    """失败后成功重试，状态要换成新的成功结果"""
    env["browser"] = BoomBrowser()
    store.add_creator(SEC, "x")
    await svc.check_all()
    assert store.get_creator(SEC)["last_result"].startswith("失败")

    env["browser"] = FakeBrowser(_ids(10))
    await svc.check_all()
    rec = store.get_creator(SEC)
    assert "已建立基线" in rec["last_result"], "恢复后状态还是旧的失败"
    assert rec["last_checked"], "恢复后 last_checked 仍没写"


@pytest.mark.asyncio
async def test_manual_single_check_failure_writes_status(env):
    """单查接口的失败也要落状态（走 server 端点的 except 分支）"""
    from fastapi import HTTPException

    from server import CheckCreatorRequest, api_subscriptions_check

    env["browser"] = BoomBrowser()
    store.add_creator(SEC, "x")

    with pytest.raises(HTTPException):
        await api_subscriptions_check(SEC, CheckCreatorRequest())

    rec = store.get_creator(SEC)
    assert rec["last_result"].startswith("失败"), rec["last_result"]
    assert rec["last_checked"] is None


# ---------------- 界面 ----------------

def test_card_shows_attempt_and_status():
    js = (STATIC / "js" / "subscriptions.js").read_text(encoding="utf-8")
    assert "statusSpan" in js, "卡片没渲染状态"
    assert "last_attempt || c.last_checked" in js, \
        "时间没用 last_attempt（老订阅要回落 last_checked）"
    assert "'失败'" in js or '"失败"' in js, "失败前缀没判色"


def test_card_status_html_static_check():
    js = (STATIC / "js" / "subscriptions.js").read_text(encoding="utf-8")
    # 状态文本要转义（失败原因来自异常消息，可能是任意字符串）
    assert "escHtml(t)" in js or "escHtml(c.last_result)" in js, \
        "状态没转义，异常消息里的尖括号会打穿标签"
