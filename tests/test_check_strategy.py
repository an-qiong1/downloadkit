"""P2-3 手动「检查全部更新」的策略入口

策略三件套：下载开关 / 单轮上限 / 下载范围（临时覆盖）。

要守住的不变量：

  1. **范围临时覆盖不落库** —— 手动检查选「全部补下」只影响这一轮，
     各创作者卡片上设置的范围一个字都不能被改。落了库就等于
     一次手滑永久改了订阅配置，下次自动轮询会照着错的范围跑。
  2. **校验必须开跑前拦下** —— 非法 scope / N=0 要在进 run_round
     之前 400，不能等抓完主页、甚至入了队才发现策略写错了。
  3. **两种范围来源共用一套规则** —— 卡片写库走 set_creator_scope，
     策略走 validate_scope，必须是同一个函数；两套规则迟早分裂。
"""

from pathlib import Path

import pytest
from fastapi import HTTPException

import downloadkit.poller as poller
import downloadkit.subscription as store
import downloadkit.subscription_service as svc

SEC = "MS4wLjABAAAA_test_check_strategy"

STATIC = Path(__file__).resolve().parent.parent / "downloadkit" / "static"


# ---------------- 复用 test_download_scope 的脚手架 ----------------

def _ids(n, start=1):
    """n 个作品 ID，按数值降序（模拟主页排列）"""
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


# ---------------- validate_scope：与卡片同一套规则 ----------------

def test_validate_scope_three_modes():
    assert store.validate_scope("only_new") == ("only_new", "")
    assert store.validate_scope("backfill_n", "5") == ("backfill_n", "5")
    assert store.validate_scope("all") == ("all", "")
    # 非 backfill_n 模式带参数 → 清掉（卡片和策略来回切不留残留）
    assert store.validate_scope("all", "42") == ("all", "")


def test_validate_scope_normalizes():
    assert store.validate_scope("  all  ") == ("all", "")
    assert store.validate_scope("backfill_n", "007") == ("backfill_n", "7")


@pytest.mark.parametrize("scope, param", [
    ("haha", ""),                 # 范围取值非法
    ("", ""),                     # 空范围
    ("since_date", ""),           # 本期缓做的取值，不能被策略偷渡进来
    ("backfill_n", ""),           # N 缺失
    ("backfill_n", "abc"),        # N 不是整数
    ("backfill_n", "0"),          # N 越界
    ("backfill_n", "10000"),      # N 越界
])
def test_validate_scope_rejects(scope, param):
    with pytest.raises(ValueError):
        store.validate_scope(scope, param)


# ---------------- 路由：开跑前拦下非法策略 ----------------

def _endpoint():
    from server import api_subscriptions_check_all, CheckAllRequest
    return api_subscriptions_check_all, CheckAllRequest


@pytest.mark.asyncio
async def test_route_rejects_bad_scope_before_running(monkeypatch):
    """非法 scope 必须 400，且一轮都不能开跑"""
    started = []

    async def fake_run_round(**kw):
        started.append(kw)
        return {}

    monkeypatch.setattr(poller, "run_round", fake_run_round)
    fn, Req = _endpoint()

    with pytest.raises(HTTPException) as e:
        await fn(Req(scope="haha"))
    assert e.value.status_code == 400
    assert started == [], "校验没拦住，策略带着非法值开跑了"


@pytest.mark.asyncio
async def test_route_rejects_bad_backfill_n(monkeypatch):
    started = []

    async def fake_run_round(**kw):
        started.append(kw)
        return {}

    monkeypatch.setattr(poller, "run_round", fake_run_round)
    fn, Req = _endpoint()

    with pytest.raises(HTTPException) as e:
        await fn(Req(scope="backfill_n", scope_param="0"))
    assert e.value.status_code == 400
    assert started == []


@pytest.mark.asyncio
async def test_route_passes_normalized_scope(monkeypatch):
    """合法策略要透传；参数先规范化（007 → 7）"""
    seen = []

    async def fake_run_round(**kw):
        seen.append(kw)
        return {}

    monkeypatch.setattr(poller, "run_round", fake_run_round)
    fn, Req = _endpoint()

    await fn(Req(scope="backfill_n", scope_param="007", max_new=1))
    assert seen[0]["scope"] == "backfill_n"
    assert seen[0]["scope_param"] == "7"
    assert seen[0]["max_new"] == 1, "已有字段不能被策略改造误伤"

    # 不给 scope = 跟随各创作者设置，传空串（后端约定空 = 不覆盖）
    await fn(Req())
    assert seen[1]["scope"] == ""
    assert seen[1]["scope_param"] == ""
    assert seen[1]["download"] is True, "默认值必须保持原行为"


# ---------------- 透传链：run_round → check_all ----------------

@pytest.mark.asyncio
async def test_run_round_passes_scope_to_check_all(monkeypatch, tmp_path):
    seen = []

    async def fake_check_all(**kw):
        seen.append(kw)
        return {"total": 0, "queued": 0, "new_found": 0, "errors": 0,
                "results": []}

    monkeypatch.setattr(svc, "check_all", fake_check_all)
    monkeypatch.setattr(poller, "load_config",
                        lambda: {"subscription": {"enabled": True}})
    monkeypatch.setattr(poller, "save_config", lambda c: None)

    await poller.run_round(manual=True, download=True, max_new=2,
                           scope="all", scope_param="")
    assert seen[0]["scope"] == "all", "run_round 把范围覆盖吃掉了"
    assert seen[0]["max_new"] == 2


@pytest.mark.asyncio
async def test_check_all_passes_scope_to_each_creator(monkeypatch):
    captured = []

    async def fake_check_creator(sec_uid, **kw):
        captured.append((sec_uid, kw))
        return {"sec_uid": sec_uid, "nickname": "x",
                "queued": 0, "new_count": 0}

    monkeypatch.setattr(store, "list_creators",
                        lambda enabled_only=False: [
                            {"sec_uid": SEC, "nickname": "x"},
                            {"sec_uid": SEC + "2", "nickname": "y"},
                        ])
    monkeypatch.setattr(svc, "check_creator", fake_check_creator)

    await svc.check_all(download=True, max_new=2,
                        scope="backfill_n", scope_param="5")

    assert len(captured) == 2, "每个启用的创作者都要收到策略"
    for _sec, kw in captured:
        assert kw["scope"] == "backfill_n"
        assert kw["scope_param"] == "5"
        assert kw["max_new"] == 2


# ---------------- check_creator：临时覆盖不落库 ----------------

@pytest.mark.asyncio
async def test_scope_override_backfills_when_store_says_only_new(env):
    """存储的范围是 only_new，本轮策略选 backfill_n → 只补这一轮"""
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC, download=True)          # 建基线（不补）

    r = await svc.check_creator(SEC, download=True, max_new=0,
                                scope="backfill_n", scope_param="3")

    assert r.get("backfilled") == 3, "策略的 N=3 没生效"
    assert set(env["enqueued"]) == {"10", "9", "8"}

    rec = store.get_creator(SEC)
    assert rec["download_scope"] == "only_new", "临时覆盖写库了！"
    assert rec["scope_param"] == ""

    # 下一轮不带策略 → 回到存储的 only_new，一个都不补
    r2 = await svc.check_creator(SEC, download=True, max_new=0)
    assert r2.get("backfilled", 0) == 0, "策略的效果泄漏到了下一轮"
    assert len(env["enqueued"]) == 3


@pytest.mark.asyncio
async def test_scope_override_only_new_suppresses_stored_backfill(env):
    """反向：存储范围是 all，本轮策略选「仅新作品」→ 一个历史都不补"""
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC, download=True)          # 基线
    store.set_creator_scope(SEC, "all")

    r = await svc.check_creator(SEC, download=True, max_new=0,
                                scope="only_new")

    assert r.get("backfilled", 0) == 0
    assert env["enqueued"] == [], "策略说不补，存储的 all 不该冒出来"
    assert store.get_creator(SEC)["download_scope"] == "all", "覆盖写库了！"


@pytest.mark.asyncio
async def test_scope_override_on_first_check(env):
    """首查带策略：建基线当轮就按策略补（P2-1 的行为不被 P2-3 改掉）"""
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")

    r = await svc.check_creator(SEC, download=True, max_new=0,
                                scope="all")

    assert r["baselined"] is True
    assert r.get("backfilled") == 10, "基线当轮应按策略全补"
    assert store.get_creator(SEC)["download_scope"] == "only_new", \
        "临时覆盖写库了！"


@pytest.mark.asyncio
async def test_scope_override_respects_budget(env):
    """策略也受单轮上限约束：max_new=2 → 增量 1 + 补下 1"""
    env["browser"] = FakeBrowser(_ids(10))
    store.add_creator(SEC, "x")
    await svc.check_creator(SEC, download=True)          # 基线

    env["browser"] = FakeBrowser(["11"] + _ids(10))
    r = await svc.check_creator(SEC, download=True, max_new=2,
                                scope="all")

    assert r["new_count"] == 1
    assert r["queued"] == 2, "增量 1 + 补下余量 1"
    assert r.get("backfilled") == 1
    assert r.get("backfill_left") == 9, "10 个候选补了 1，剩 9 记清楚"


# ---------------- 界面 ----------------

def test_strategy_controls_in_html():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert 'id="sub-check-strategy"' in html, "缺策略折叠区"
    assert 'id="strat-download"' in html, "缺下载开关"
    assert 'id="strat-maxnew"' in html, "缺单轮上限"
    assert 'id="strat-scope"' in html, "缺下载范围"
    assert '<option value="">跟随各创作者设置</option>' in html, "缺「跟随」默认项"
    assert 'id="strat-n"' in html, "缺 N 输入框"
    # 默认值必须 = 改造前的行为：勾着下载、单轮 1 个、跟随
    assert 'id="strat-download" checked' in html, "下载开关默认值变了"
    assert '<option value="1">1 个</option>' in html, "单轮上限默认项变了"


def test_strategy_wired_in_js():
    js = (STATIC / "js" / "subscriptions.js").read_text(encoding="utf-8")
    assert "readStrategy" in js, "checkAll 没读策略控件"
    assert "bindStrategy" in js, "策略控件没绑定"
    assert "scope: strat.scope" in js, "checkAll body 没带范围"
    assert "scope_param" in js, "checkAll body 没带 N"
    # 范围选「全部补下」要有 confirm 防呆（与卡片行为一致）
    assert "strat-scope" in js
    # 临时覆盖的说明必须写给用户看：不改订阅设置
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    assert "不修改各创作者的订阅设置" in html, "没告诉用户策略是临时的"
