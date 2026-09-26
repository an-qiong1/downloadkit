"""基线水位线测试

背景（2026-09-26 实测）：抖音主页是滑动窗口，同样滚动 3 次，
两次抓回来 62 条里只有 54 条重合 —— 尾部会混进早就发过的老作品。
纯集合差集会把它们当「新作品」，反复点检查就会一条条把老视频下下来。

水位线规则：只有 aweme_id > 基线水位线 的才叫新作品。
"""

import pytest

import downloadkit.subscription as store
import downloadkit.subscription_service as svc

SEC = "MS4wLjABAAAA_test_watermark"


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


class FakeBrowser:
    def __init__(self, ids, nickname="测试博主"):
        self.ids = list(ids)
        self.nickname = nickname

    async def check_login_via_api(self):
        return True, "已登录: 测试 / uid=1"

    async def fetch_creator(self, sec_uid, max_scrolls=5):
        from downloadkit.douyin_browser import CreatorInfo
        return CreatorInfo(sec_uid=sec_uid, nickname=self.nickname,
                           avatar="", video_ids=list(self.ids))


@pytest.fixture
def db(tmp_path, monkeypatch):
    """只建临时库，不起浏览器 —— 给纯存储层测试用"""
    home = tmp_path / "home"
    (home / ".downloadkit").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(store.Path, "home", staticmethod(lambda: home))
    store._DB_DIR = home / ".downloadkit"
    store._DB_PATH = store._DB_DIR / "subscriptions.db"
    if getattr(store._local, "conn", None) is not None:
        store._local.conn.close()
    store._local.conn = None
    yield store
    if getattr(store._local, "conn", None) is not None:
        store._local.conn.close()
    store._local.conn = None


# ---------------- 水位线的建立 ----------------

@pytest.mark.asyncio
async def test_baseline_records_watermark(env):
    """水位线 = 基线时最新的那条 ID"""
    env["browser"] = FakeBrowser(["10", "9", "8"])
    store.add_creator(SEC, "x")

    r = await svc.check_creator(SEC)
    assert r["baselined"] is True
    assert r["baseline"] == "10"
    assert store.get_creator(SEC)["baseline_max_id"] == "10"
    assert env["enqueued"] == []


@pytest.mark.asyncio
async def test_watermark_is_set_only_once(env):
    """之后不管抓到多大的 ID，都不许覆盖水位线。

    覆盖了就会把「还没下载完的真新作品」压到水位线以下，导致漏下。
    """
    env["browser"] = FakeBrowser(["10", "9"])
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC)
    assert store.get_creator(SEC)["baseline_max_id"] == "10"

    # 又发了新作品，ID 更大
    env["browser"] = FakeBrowser(["99", "10", "9"])
    await svc.check_creator(SEC)
    assert store.get_creator(SEC)["baseline_max_id"] == "10", "水位线被覆盖了"


@pytest.mark.asyncio
async def test_empty_fetch_at_baseline_refused(env):
    """一个都没抓到时不能建基线，否则水位线是空的，
    下一轮会把所有存量作品当新作品下载"""
    env["browser"] = FakeBrowser([])
    store.add_creator(SEC, "x")

    with pytest.raises(ValueError):
        await svc.check_creator(SEC)

    rec = store.get_creator(SEC)
    assert rec["last_checked"] is None, "空抓取不应标记为已检查"
    assert env["enqueued"] == []


# ---------------- 滑窗漂移必须被拦住 ----------------

@pytest.mark.asyncio
async def test_drift_old_works_blocked(env):
    """核心：尾部漂移进来的老作品一个都不能下载"""
    # 基线：10/9/8，水位线 = 10
    env["browser"] = FakeBrowser(["10", "9", "8"])
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC)
    env["enqueued"].clear()

    # 下次抓取窗口尾部漂移，混进 7/6/5 这些老作品
    env["browser"] = FakeBrowser(["10", "9", "8", "7", "6", "5"])
    r = await svc.check_creator(SEC, download=True)

    assert r["new_count"] == 0
    assert r["queued"] == 0
    assert r["drift_blocked"] == 3
    assert env["enqueued"] == [], "漂移的老作品被下载了"
    # 顺手标成已见，让「已发现」计数准确
    for i in ("7", "6", "5"):
        assert store.is_work_seen(SEC, i)


@pytest.mark.asyncio
async def test_drift_at_head_below_watermark_blocked(env):
    """水位线以下的，即使排在信息流最前面也不算新"""
    env["browser"] = FakeBrowser(["100"])
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC)

    # "50" 从没见过，但比水位线小 → 漂移
    env["browser"] = FakeBrowser(["50", "100"])
    r = await svc.check_creator(SEC)
    assert r["new_count"] == 0
    assert r["drift_blocked"] == 1
    assert env["enqueued"] == []


# ---------------- 真新作品必须能连续捡回来 ----------------

@pytest.mark.asyncio
async def test_real_new_work_detected(env):
    env["browser"] = FakeBrowser(["10", "9"])
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC)
    env["enqueued"].clear()

    env["browser"] = FakeBrowser(["11", "10", "9"])
    r = await svc.check_creator(SEC)
    assert r["new_count"] == 1
    assert r["queued"] == 1
    assert env["enqueued"] == ["11"]


@pytest.mark.asyncio
async def test_pending_new_survives_multiple_checks(env):
    """max_new 截断后，剩下的真新作品必须能被后续检查捡回来。

    水位线不能跟着「已下载的最大 ID」走 —— 走了就永远漏。
    """
    env["browser"] = FakeBrowser(["10"])
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC)
    env["enqueued"].clear()

    # 一口气发了 4 个：14/13/12/11（信息流顺序倒序）
    feed = ["14", "13", "12", "11", "10"]

    env["browser"] = FakeBrowser(feed)
    r1 = await svc.check_creator(SEC, download=True, max_new=1)
    assert r1["new_count"] == 4
    assert r1["queued"] == 1
    assert r1["pending"] == 3
    assert env["enqueued"] == ["14"]
    # 水位线没动
    assert store.get_creator(SEC)["baseline_max_id"] == "10"

    # 第二轮：13/12/11 仍然是新作品
    env["browser"] = FakeBrowser(feed)
    r2 = await svc.check_creator(SEC, download=True, max_new=1)
    assert r2["new_count"] == 3, "没下载完的真新作品被水位线吃掉了"
    assert r2["queued"] == 1
    assert env["enqueued"] == ["14", "13"]

    # 第三轮
    env["browser"] = FakeBrowser(feed)
    r3 = await svc.check_creator(SEC, download=True, max_new=1)
    assert r3["new_count"] == 2
    assert env["enqueued"] == ["14", "13", "12"]


@pytest.mark.asyncio
async def test_download_false_leaves_new_unmarked(env):
    """只看不下载时，真新作品保持未见，下次还能下"""
    env["browser"] = FakeBrowser(["10"])
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC)

    env["browser"] = FakeBrowser(["11", "10"])
    r = await svc.check_creator(SEC, download=False)
    assert r["new_count"] == 1
    assert r["queued"] == 0
    assert not store.is_work_seen(SEC, "11")


# ---------------- 老库兼容 ----------------

@pytest.mark.asyncio
async def test_legacy_subscription_backfills_watermark(env):
    """升级前建的订阅：有 last_checked 但没有水位线。

    第一次检查补水位线且一个都不下，第二次才正常判新。
    """
    env["browser"] = FakeBrowser(["10", "9", "8"])
    store.add_creator(SEC, "x")
    # 伪造老版本状态：已检查过，但水位线为空
    store.mark_works_seen(SEC, [{"aweme_id": a} for a in ("10", "9", "8")])
    store.mark_creator_checked(SEC, last_found="")
    assert store.get_creator(SEC)["baseline_max_id"] == ""

    env["browser"] = FakeBrowser(["10", "9", "8", "7", "6"])
    r1 = await svc.check_creator(SEC, download=True)
    assert r1["baselined"] is True, "老订阅应先补水位线"
    assert env["enqueued"] == [], "补基线那一轮不允许下载"
    assert store.get_creator(SEC)["baseline_max_id"] == "10"

    # 第二轮：7/6 是水位线以下的漂移，11 才是新作品
    env["browser"] = FakeBrowser(["11", "10", "9", "8", "7", "6"])
    r2 = await svc.check_creator(SEC, download=True)
    assert r2["new_count"] == 1
    assert r2["drift_blocked"] == 2
    assert env["enqueued"] == ["11"]


# ---------------- split_new_vs_drift 单元 ----------------

def test_split_separates_new_from_drift(db):
    try:
        store.add_creator(SEC, "x")
        store.set_creator_baseline(SEC, "50")
        store.mark_works_seen(
            SEC,
            [{"aweme_id": a} for a in ("50", "40", "30")],
        )

        fresh, drift = store.split_new_vs_drift(
            SEC, ["60", "55", "50", "45", "40", "35", "30", "20"]
        )
        # 从没见过的：60 / 55 / 45 / 35 / 20
        # 其中 60、55 在水位线(50)之上 → 真新
        #      45、35、20 在水位线之下 → 滑窗漂移进来的老作品
        assert fresh == ["60", "55"]
        assert drift == ["45", "35", "20"]

        # 去重：同一条在一批里出现两次只算一次
        fresh2, drift2 = store.split_new_vs_drift(SEC, ["60", "60", "10"])
        assert fresh2 == ["60"]
        assert drift2 == ["10"]
    finally:
        if getattr(store._local, "conn", None) is not None:
            store._local.conn.close()
        store._local.conn = None


def test_split_without_watermark_falls_back_to_set_difference(db):
    """没水位线时退回纯集合差集（跟旧行为一致，宁可多判新也不误吞）"""
    try:
        store.add_creator(SEC, "x")
        store.mark_works_seen(SEC, [{"aweme_id": "100"}])
        fresh, drift = store.split_new_vs_drift(SEC, ["100", "5"])
        assert fresh == ["5"]
        assert drift == []
    finally:
        if getattr(store._local, "conn", None) is not None:
            store._local.conn.close()
        store._local.conn = None


def test_split_handles_non_numeric_ids(db):
    """非数字 ID 不该让比较崩溃"""
    try:
        store.add_creator(SEC, "x")
        store.set_creator_baseline(SEC, "50")
        fresh, drift = store.split_new_vs_drift(SEC, ["abc", "60"])
        assert fresh == ["60"]
        assert drift == ["abc"]
    finally:
        if getattr(store._local, "conn", None) is not None:
            store._local.conn.close()
        store._local.conn = None


def test_set_baseline_never_overwrites(db):
    try:
        store.add_creator(SEC, "x")
        assert store.set_creator_baseline(SEC, "50") is True
        assert store.set_creator_baseline(SEC, "99") is False
        assert store.get_creator(SEC)["baseline_max_id"] == "50"
        # 空值不写
        assert store.set_creator_baseline(SEC, "") is False
        assert store.get_creator(SEC)["baseline_max_id"] == "50"
    finally:
        if getattr(store._local, "conn", None) is not None:
            store._local.conn.close()
        store._local.conn = None
