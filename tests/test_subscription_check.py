"""增量检查（A4）测试

最关键的两条不变量：
  1. 首次检查只建基线，绝不下载存量作品
  2. 先入队再标记已见 —— 反过来的话入队失败的作品会被永久跳过
"""

import pytest

import downloadkit.subscription as store
import downloadkit.subscription_service as svc


SEC = "MS4wLjABAAAA_test_check_creator"
OTHER = "MS4wLjABAAAA_test_check_creator2"


class FakeBrowser:
    """替身浏览器：只提供 check_login_via_api 和 fetch_creator"""

    def __init__(self, ids, nickname="测试博主", avatar=""):
        self.ids = list(ids)
        self.nickname = nickname
        self.avatar = avatar
        self.fetch_calls = 0

    async def check_login_via_api(self):
        return True, "已登录: 测试 / uid=1"

    async def fetch_creator(self, sec_uid, max_scrolls=5):
        self.fetch_calls += 1
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

    # 替换取浏览器的入口，避免真起 Chromium
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


# ---------------- 首次检查：建基线 ----------------

@pytest.mark.asyncio
async def test_first_check_baselines_without_downloading(env):
    """核心约束：首次检查一个存量作品都不能下载"""
    env["browser"] = FakeBrowser(["1", "2", "3", "4", "5"])
    store.add_creator(SEC, "测试博主")

    r = await svc.check_creator(SEC, download=True)

    assert r["baselined"] is True
    assert r["fetched"] == 5
    assert r["marked_as_seen"] == 5
    assert r["new_count"] == 0
    assert r["queued"] == 0
    assert env["enqueued"] == [], "首次检查不允许下载任何作品"
    # 但 5 个都记成已见了
    for i in ("1", "2", "3", "4", "5"):
        assert store.is_work_seen(SEC, i)


@pytest.mark.asyncio
async def test_baseline_records_last_checked(env):
    env["browser"] = FakeBrowser(["1", "2"])
    store.add_creator(SEC, "x")
    assert store.get_creator(SEC)["last_checked"] is None

    await svc.check_creator(SEC)
    assert store.get_creator(SEC)["last_checked"] is not None


@pytest.mark.asyncio
async def test_baseline_does_not_download_even_if_download_true(env):
    """download=True 也不能回补历史，这是语义不是开关"""
    env["browser"] = FakeBrowser([str(i) for i in range(50)])
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC, download=True, max_new=0)
    assert env["enqueued"] == []


# ---------------- 后续检查：只下新增 ----------------

@pytest.mark.asyncio
async def test_second_check_downloads_only_new(env):
    env["browser"] = FakeBrowser(["1", "2", "3"])
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC)                 # 建基线
    assert env["enqueued"] == []

    # 博主发了两个新作品（ID 倒序，新的在前，和抖音主页一致）
    env["browser"] = FakeBrowser(["5", "4", "3", "2", "1"])
    r = await svc.check_creator(SEC, download=True)

    assert r["baselined"] is False
    assert r["new_count"] == 2
    assert r["queued"] == 2
    assert sorted(env["enqueued"]) == ["4", "5"]
    # 新的立即标已见，避免下次重复
    assert store.is_work_seen(SEC, "4")
    assert store.is_work_seen(SEC, "5")


@pytest.mark.asyncio
async def test_no_new_works_downloads_nothing(env):
    env["browser"] = FakeBrowser(["1", "2"])
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC)

    r = await svc.check_creator(SEC)
    assert r["new_count"] == 0
    assert r["queued"] == 0
    assert r["message"] == "没有新作品"
    assert env["enqueued"] == []


@pytest.mark.asyncio
async def test_download_false_does_not_mark_seen(env):
    """只看不下载时，不能把新作品标成已见，否则就永远下不到了"""
    env["browser"] = FakeBrowser(["1"])
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC)                 # 基线

    env["browser"] = FakeBrowser(["9", "1"])
    r = await svc.check_creator(SEC, download=False)

    assert r["new_count"] == 1
    assert r["queued"] == 0
    assert "本次不下载" in r["message"]
    # 关键：还没标已见
    assert not store.is_work_seen(SEC, "9")


# ---------------- max_new 上限 ----------------

@pytest.mark.asyncio
async def test_max_new_caps_but_leaves_rest_pending(env):
    """超出上限的留到下次，不能被标成已见丢掉"""
    env["browser"] = FakeBrowser(["1"])
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC)

    env["browser"] = FakeBrowser(["5", "4", "3", "2", "1"])
    r = await svc.check_creator(SEC, download=True, max_new=1)

    assert r["new_count"] == 4
    assert r["queued"] == 1
    assert r["pending"] == 3
    assert env["enqueued"] == ["5"]
    # 只有下了的标已见，其余 3 个留着
    assert store.is_work_seen(SEC, "5")
    for i in ("2", "3", "4"):
        assert not store.is_work_seen(SEC, i)

    # 下次检查还能捡回来
    env["browser"] = FakeBrowser(["5", "4", "3", "2", "1"])
    r2 = await svc.check_creator(SEC, download=True, max_new=0)
    assert r2["new_count"] == 3
    assert r2["queued"] == 3
    assert sorted(env["enqueued"]) == ["2", "3", "4", "5"]


@pytest.mark.asyncio
async def test_max_new_zero_means_unlimited(env):
    env["browser"] = FakeBrowser(["1"])
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC)
    env["browser"] = FakeBrowser(["5", "4", "3", "2", "1"])
    r = await svc.check_creator(SEC, download=True, max_new=0)
    assert r["queued"] == 4
    assert "pending" not in r


# ---------------- 入队失败不能丢作品 ----------------

@pytest.mark.asyncio
async def test_enqueue_failure_leaves_work_unseen(env, monkeypatch):
    """入队失败的作品必须留在未下载状态，下次还能重试"""
    env["browser"] = FakeBrowser(["1"])
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC)

    async def failing_enqueue(aweme_id, sec_uid, nickname):
        return False, "", "队列满了"

    monkeypatch.setattr(svc, "_enqueue_video", failing_enqueue)

    env["browser"] = FakeBrowser(["9", "1"])
    r = await svc.check_creator(SEC, download=True)

    assert r["new_count"] == 1
    assert r["queued"] == 0
    assert not store.is_work_seen(SEC, "9"), "入队失败却标了已见，作品会永久丢失"


# ---------------- 暂停/未登录 ----------------

@pytest.mark.asyncio
async def test_paused_creator_is_skipped(env):
    env["browser"] = FakeBrowser(["1", "2"])
    store.add_creator(SEC, "x")
    store.set_creator_enabled(SEC, False)

    r = await svc.check_creator(SEC)
    assert r["skipped"] is True
    assert r["reason"] == "已暂停轮询"
    assert env["browser"].fetch_calls == 0, "暂停的创作者不该去抓主页"


@pytest.mark.asyncio
async def test_not_logged_in_raises(env):
    class Anon(FakeBrowser):
        async def check_login_via_api(self):
            return False, "未登录 (status_code=8)"

    env["browser"] = Anon(["1"])
    store.add_creator(SEC, "x")
    with pytest.raises(svc.LoginRequired):
        await svc.check_creator(SEC)


@pytest.mark.asyncio
async def test_unsubscribed_creator_raises(env):
    env["browser"] = FakeBrowser(["1"])
    with pytest.raises(ValueError):
        await svc.check_creator(SEC)


# ---------------- 补昵称 ----------------

@pytest.mark.asyncio
async def test_check_fills_in_nickname(env):
    env["browser"] = FakeBrowser(["1"], nickname="笔吧评测室")
    store.add_creator(SEC, "")          # 订阅时没抓资料
    await svc.check_creator(SEC)
    assert store.get_creator(SEC)["nickname"] == "笔吧评测室"


# ---------------- 批量 ----------------

@pytest.mark.asyncio
async def test_check_all_skips_paused(env):
    env["browser"] = FakeBrowser(["1"])
    store.add_creator(SEC, "A")
    store.add_creator(OTHER, "B")
    store.set_creator_enabled(OTHER, False)

    r = await svc.check_all()
    assert r["total"] == 1
    assert len(r["results"]) == 1
    assert r["results"][0]["sec_uid"] == SEC


@pytest.mark.asyncio
async def test_check_all_stops_on_login_required(env, monkeypatch):
    """没登录时立刻停下，不要对每个创作者都重试一遍"""
    class Anon(FakeBrowser):
        async def check_login_via_api(self):
            return False, "未登录"

    env["browser"] = Anon(["1"])
    store.add_creator(SEC, "A")
    store.add_creator(OTHER, "B")

    r = await svc.check_all()
    assert len(r["results"]) == 1
    assert "error" in r["results"][0]


@pytest.mark.asyncio
async def test_check_all_reports_per_creator_errors(env, monkeypatch):
    """一个创作者失败不影响其它创作者"""
    calls = {"n": 0}

    async def boom(sec_uid, download=True, max_new=3, max_scrolls=3, **kw):
        # **kw 接住 check_all 透传的 scope / scope_param（P2-3 策略）
        calls["n"] += 1
        if sec_uid == SEC:
            raise RuntimeError("页面超时")
        return {"sec_uid": sec_uid, "new_count": 0, "queued": 0}

    monkeypatch.setattr(svc, "check_creator", boom)
    store.add_creator(SEC, "A")
    store.add_creator(OTHER, "B")

    r = await svc.check_all()
    assert calls["n"] == 2
    assert len(r["results"]) == 2
    errs = [x for x in r["results"] if "error" in x]
    assert len(errs) == 1
