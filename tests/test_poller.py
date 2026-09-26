"""订阅自动轮询（A5）测试

三个最容易写坏又最难发现的点，必须有测试锁死：

1. **不能撞抖音风控** —— 实测已触发过验证码中间页。
   触发后必须指数退避，绝不能下一轮照常敲。
2. **不和登录抢浏览器** —— Chromium 同 profile 单实例。
   登录窗口开着时轮询必须让路；反过来登录也要让轮询先跑完。
3. **中断要分情况** —— 风控走退避，未登录走「等用户扫码」，
   两者不能混为一谈（混了就会在没登录时白白退避几小时）。
"""

import asyncio
from datetime import datetime, timedelta

import pytest

import downloadkit.poller as poller
import downloadkit.subscription as store
import downloadkit.subscription_service as svc
from downloadkit.douyin_browser import RateLimited, looks_like_captcha

SEC = "MS4wLjABAAAA_test_poller"


# ------------------------------------------------------------------
# 配置
# ------------------------------------------------------------------

@pytest.fixture
def cfg(monkeypatch):
    """把轮询配置挪进临时字典，不碰真实的 config.toml"""
    box = {"subscription": {
        "enabled": False,
        "interval_minutes": 60,
        "max_new_per_check": 3,
        "jitter_percent": 20,
    }}

    def fake_load():
        return {k: dict(v) for k, v in box.items()}

    def fake_save(config):
        for section, values in config.items():
            box.setdefault(section, {}).update(values)

    monkeypatch.setattr(poller, "load_config", fake_load)
    monkeypatch.setattr(poller, "save_config", fake_save)
    yield box


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
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


@pytest.fixture(autouse=True)
def clean_state():
    """每条测试都从干净的运行时状态开始（poller 是模块级单例）"""
    saved = dict(poller._state)
    poller._state.clear()
    poller._state.update({
        "running": False, "rounds": 0, "last_run_at": "", "last_result": {},
        "consecutive_failures": 0, "backoff_until": "", "needs_login": False,
        "next_run_at": "",
    })
    yield
    poller._state.clear()
    poller._state.update(saved)


def test_default_config_is_off(cfg):
    """默认必须是关的：装完不该自己在后台跑起来"""
    s = poller.load_settings()
    assert s["enabled"] is False
    assert s["interval_minutes"] == 60
    assert s["max_new_per_check"] == 3
    assert s["jitter_percent"] == 20


@pytest.mark.parametrize("raw, want", [
    (5, 15),            # 低于下限 → 抬到 15 分钟
    (0, 15),
    (99999, 1440),      # 高于上限 → 压到 24 小时
    ("abc", 60),        # 非法 → 回落默认
    (None, 60),
    (30, 30),           # 合法值原样保留
])
def test_interval_clamped(cfg, raw, want):
    cfg["subscription"]["interval_minutes"] = raw
    assert poller.load_settings()["interval_minutes"] == want


def test_save_settings_persists_and_clamps(cfg):
    out = poller.save_settings(interval_minutes=99999, enabled=True)
    assert out["interval_minutes"] == 1440, "写入时也必须裁剪"
    assert out["enabled"] is True
    assert cfg["subscription"]["enabled"] is True, "没写进配置"


def test_save_settings_ignores_none(cfg):
    """None = 不改这个字段，不能把已有值清掉"""
    cfg["subscription"]["interval_minutes"] = 45
    out = poller.save_settings(interval_minutes=None, enabled=True)
    assert out["interval_minutes"] == 45
    assert out["enabled"] is True


# ------------------------------------------------------------------
# 退避
# ------------------------------------------------------------------

@pytest.mark.parametrize("base, failures, want", [
    (60, 0, 0),
    (60, 1, 120),     # 翻一倍
    (60, 2, 240),
    (60, 3, 480),
    (60, 10, 1440),   # 封顶 24 小时
    (60, 999, 1440),  # 失败次数再大也不能溢出
    (15, 1, 30),
])
def test_backoff_is_exponential_and_capped(base, failures, want):
    assert poller._backoff_minutes(base, failures) == want


def test_compute_wait_includes_backoff(cfg):
    """退避未过时，至少要等到退避结束，不能按正常间隔醒"""
    cfg["subscription"]["interval_minutes"] = 15   # 正常 15 分钟
    poller._state["last_run_at"] = "2026-09-26 10:00:00"
    poller._state["backoff_until"] = (
        datetime.now() + timedelta(hours=3)
    ).strftime("%Y-%m-%d %H:%M:%S")

    wait = poller._compute_wait(poller.load_settings())
    assert wait >= 3 * 3600 - 5, f"退避 3 小时却只等 {wait:.0f}s"


def test_compute_wait_jitters_within_bounds(cfg):
    """抖动必须在 ±jitter 内，且下限 60 秒（不能忙轮询）"""
    cfg["subscription"]["interval_minutes"] = 60
    cfg["subscription"]["jitter_percent"] = 20
    poller._state["last_run_at"] = "2026-09-26 10:00:00"

    base = 60 * 60
    waits = [poller._compute_wait(poller.load_settings()) for _ in range(60)]
    assert min(waits) >= base * 0.8 - 1
    assert max(waits) <= base * 1.2 + 1
    assert len({round(w) for w in waits}) > 1, "抖动没生效，每次等待都一样"


def test_first_run_is_soon(cfg):
    """从没跑过时快速来一轮，用户打开开关要马上看到效果"""
    cfg["subscription"]["enabled"] = True
    poller._state["last_run_at"] = ""
    wait = poller._compute_wait(poller.load_settings())
    # 首轮是**一次性**的提前，允许低于常规的 60 秒下限；
    # 常规下限的目的是防忙轮询，而忙轮询指的是反复发生。
    assert poller.FIRST_RUN_DELAY_SECONDS - 1 <= wait <= poller.FIRST_RUN_DELAY_SECONDS + 1
    assert wait > 0, "不能为 0，否则打开开关瞬间就抓主页"


def test_regular_wait_never_below_floor(cfg):
    """常规等待必须有 60 秒下限，绝不忙轮询"""
    cfg["subscription"]["interval_minutes"] = 15
    cfg["subscription"]["jitter_percent"] = 50
    poller._state["last_run_at"] = "2026-09-26 10:00:00"
    for _ in range(30):
        assert poller._compute_wait(poller.load_settings()) >= 60


# ------------------------------------------------------------------
# 风控识别
# ------------------------------------------------------------------

@pytest.mark.parametrize("title, url, want", [
    ("验证码中间页", "", True),
    ("安全验证", "", True),
    ("请完成验证后继续", "", True),
    ("", "https://www.douyin.com/captcha/xxx", True),
    ("", "https://verify.douyin.com/x", True),
    ("笔吧评测室", "https://www.douyin.com/user/MS4w", False),
    ("", "", False),                       # 判不出来按正常处理，不误伤
    ("验证码中间页的标题", "", True),
])
def test_looks_like_captcha(title, url, want):
    assert looks_like_captcha(title, url) is want


def test_rate_limited_is_not_login_error():
    """两件事分开：没登录要引导扫码，风控要停下退避"""
    assert not issubclass(RateLimited, svc.LoginRequired)


# ------------------------------------------------------------------
# check_all 的中断语义
# ------------------------------------------------------------------

async def _run_check_all(monkeypatch, side_effects):
    """依次返回 side_effects，模拟逐个创作者的结果/异常"""
    calls = {"n": 0}

    async def fake_check(sec_uid, **kw):
        i = calls["n"]
        calls["n"] += 1
        item = side_effects[min(i, len(side_effects) - 1)]
        if isinstance(item, Exception):
            raise item
        return {"sec_uid": sec_uid, "queued": item, "new_count": item}

    monkeypatch.setattr(svc, "check_creator", fake_check)
    return await svc.check_all(download=True, max_new=1)


def _seed_creators(store_mod, n):
    for i in range(n):
        store_mod.add_creator(f"{SEC}{i}", f"博主{i}")


@pytest.mark.asyncio
async def test_check_all_stops_on_rate_limit(temp_db, monkeypatch):
    """触发风控必须立刻中断整轮，不能再敲第二个"""
    _seed_creators(temp_db, 4)
    r = await _run_check_all(
        monkeypatch, [0, RateLimited("抖音触发风控验证页：验证码中间页")]
    )
    assert r["rate_limited"] is True
    assert r["stopped_at"], "该记录是哪个创作者触发的"
    # 第一个成功(0)，第二个异常后就 break 了 → 只调用 2 次
    assert len(r["results"]) == 2
    assert r["total"] == 4


@pytest.mark.asyncio
async def test_check_all_stops_on_login_required(temp_db, monkeypatch):
    _seed_creators(temp_db, 3)
    r = await _run_check_all(monkeypatch, [svc.LoginRequired("请先登录抖音")])
    assert r["needs_login"] is True
    assert r["rate_limited"] is False, "未登录绝不能被当成风控去退避"
    assert len(r["results"]) == 1
    assert r["stopped_at"]


@pytest.mark.asyncio
async def test_check_all_continues_on_ordinary_error(temp_db, monkeypatch):
    """普通失败不中断：一个创作者挂了不该拖垮整轮"""
    _seed_creators(temp_db, 3)
    r = await _run_check_all(
        monkeypatch, [0, RuntimeError("页面没加载出来"), 0]
    )
    assert r["rate_limited"] is False
    assert r["needs_login"] is False
    assert r["errors"] == 1
    assert len(r["results"]) == 3, "普通异常不该 break"


@pytest.mark.asyncio
async def test_check_all_normal_round(temp_db, monkeypatch):
    _seed_creators(temp_db, 2)
    r = await _run_check_all(monkeypatch, [1])
    assert r["queued"] == 2
    assert r["errors"] == 0
    assert r["rate_limited"] is False
    assert r["needs_login"] is False


# ------------------------------------------------------------------
# 单轮结果 → 状态
# ------------------------------------------------------------------

def test_rate_limit_round_applies_backoff(cfg):
    cfg["subscription"]["interval_minutes"] = 60
    poller._record_round(
        {"total": 2, "queued": 0, "new_found": 0, "errors": 0,
         "rate_limited": True, "needs_login": False},
        cfg=poller.load_settings(),
    )
    assert poller._state["consecutive_failures"] == 1
    assert poller._state["backoff_until"], "风控后必须设置退避截止时间"
    assert poller._state["last_result"]["rate_limited"] is True
    assert "风控" in poller._state["last_result"]["message"]


def test_backoff_grows_across_failures(cfg):
    cfg["subscription"]["interval_minutes"] = 60
    for _ in range(3):
        poller._record_round(
            {"total": 1, "queued": 0, "new_found": 0, "errors": 0,
             "rate_limited": True, "needs_login": False},
            cfg=poller.load_settings(),
        )
    assert poller._state["consecutive_failures"] == 3
    bo = datetime.strptime(poller._state["backoff_until"], "%Y-%m-%d %H:%M:%S")
    left = (bo - datetime.now()).total_seconds()
    # 3 次失败 → 60 * 2^3 = 480 分钟
    assert 475 * 60 <= left <= 481 * 60


def test_clean_round_resets_backoff(cfg):
    for _ in range(2):
        poller._record_round(
            {"total": 1, "queued": 0, "new_found": 0, "errors": 0,
             "rate_limited": True, "needs_login": False},
            cfg=poller.load_settings(),
        )
    assert poller._state["consecutive_failures"] == 2

    poller._record_round(
        {"total": 1, "queued": 0, "new_found": 0, "errors": 0,
         "rate_limited": False, "needs_login": False},
        cfg=poller.load_settings(),
    )
    assert poller._state["consecutive_failures"] == 0
    assert poller._state["backoff_until"] == ""
    assert poller._state["needs_login"] is False


def test_login_failure_is_not_backoff(cfg):
    """未登录 → 提示扫码，但不清已有的风控退避（两回事）"""
    poller._record_round(
        {"total": 1, "queued": 0, "new_found": 0, "errors": 0,
         "rate_limited": True, "needs_login": False},
        cfg=poller.load_settings(),
    )
    assert poller._state["consecutive_failures"] == 1

    poller._record_round(
        {"total": 1, "queued": 0, "new_found": 0, "errors": 0,
         "rate_limited": False, "needs_login": True},
        cfg=poller.load_settings(),
    )
    assert poller._state["needs_login"] is True
    assert poller._state["consecutive_failures"] == 1, "退避计数被未登录清掉了"
    assert poller._state["last_result"]["message"].find("登录") >= 0


def test_ordinary_errors_back_off_too(cfg):
    poller._record_round(
        {"total": 3, "queued": 0, "new_found": 0, "errors": 2,
         "rate_limited": False, "needs_login": False},
        cfg=poller.load_settings(),
    )
    assert poller._state["consecutive_failures"] == 1
    assert poller._state["backoff_until"]


# ------------------------------------------------------------------
# run_round 的互斥与跳过
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_auto_round_skips_during_backoff(cfg):
    poller._state["backoff_until"] = (
        datetime.now() + timedelta(minutes=30)
    ).strftime("%Y-%m-%d %H:%M:%S")
    r = await poller.run_round(manual=False)
    assert r["skipped"] is True
    assert r["reason"] == "backoff"


@pytest.mark.asyncio
async def test_manual_round_ignores_backoff(cfg, monkeypatch):
    """手动触发用户说了算，退避只管自动轮询"""
    calls = {"n": 0}

    async def fake_check_all(**kw):
        calls["n"] += 1
        return {"total": 1, "queued": 0, "new_found": 0, "errors": 0,
                "rate_limited": False, "needs_login": False, "results": []}

    monkeypatch.setattr(svc, "check_all", fake_check_all)
    poller._state["backoff_until"] = (
        datetime.now() + timedelta(minutes=30)
    ).strftime("%Y-%m-%d %H:%M:%S")

    r = await poller.run_round(manual=True)
    assert not r.get("skipped"), "手动检查被退避挡掉了"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_round_skips_while_login_window_open(cfg, monkeypatch):
    """登录窗口占着 profile，这一轮必须让路"""
    import downloadkit.douyin as douyin
    monkeypatch.setattr(douyin, "is_login_running", lambda: True)

    calls = {"n": 0}

    async def fake_check_all(**kw):
        calls["n"] += 1
        return {"total": 0, "queued": 0, "new_found": 0, "errors": 0,
                "results": []}

    monkeypatch.setattr(svc, "check_all", fake_check_all)
    r = await poller.run_round(manual=True)
    assert r["skipped"] is True
    assert r["reason"] == "login"
    assert calls["n"] == 0, "登录期间还去抓了主页"


@pytest.mark.asyncio
async def test_auto_round_skips_when_busy(cfg, monkeypatch):
    """已有另一轮在跑 → 自动轮询直接跳过，不排队积压"""
    async def fake_check_all(**kw):
        await asyncio.sleep(0.3)
        return {"total": 0, "queued": 0, "new_found": 0, "errors": 0,
                "results": []}

    monkeypatch.setattr(svc, "check_all", fake_check_all)

    first = asyncio.ensure_future(poller.run_round(manual=False))
    await asyncio.sleep(0.05)          # 确保 first 已进锁
    second = await poller.run_round(manual=False)
    first_result = await first

    assert second["skipped"] is True
    assert second["reason"] == "busy"
    assert not first_result.get("skipped")


@pytest.mark.asyncio
async def test_manual_rounds_are_serialized(cfg, monkeypatch):
    """手动检查之间也必须串行 —— Chromium 只有一个页面"""
    order = []

    async def fake_check_all(**kw):
        order.append("start")
        await asyncio.sleep(0.2)
        order.append("end")
        return {"total": 0, "queued": 0, "new_found": 0, "errors": 0,
                "results": []}

    monkeypatch.setattr(svc, "check_all", fake_check_all)

    a = asyncio.ensure_future(poller.run_round(manual=True))
    await asyncio.sleep(0.05)
    b = asyncio.ensure_future(poller.run_round(manual=True))
    await asyncio.gather(a, b)

    # 严格交替，绝不出现 start start end end
    assert order == ["start", "end", "start", "end"], order


@pytest.mark.asyncio
async def test_running_flag_is_cleared_after_round(cfg, monkeypatch):
    async def fake_check_all(**kw):
        return {"total": 0, "queued": 0, "new_found": 0, "errors": 0,
                "results": []}

    monkeypatch.setattr(svc, "check_all", fake_check_all)
    assert poller.is_round_running() is False
    await poller.run_round(manual=True)
    assert poller.is_round_running() is False, "出错后 running 标志没清掉"


@pytest.mark.asyncio
async def test_running_flag_cleared_on_exception(cfg, monkeypatch):
    async def boom(**kw):
        raise RuntimeError("炸了")

    monkeypatch.setattr(svc, "check_all", boom)
    await poller.run_round(manual=True)
    assert poller.is_round_running() is False, "异常路径漏清 running 标志"
    assert poller._state["consecutive_failures"] == 1, "意外异常没计入退避"


def test_reset_for_enable_clears_stale_backoff(cfg):
    """关掉再打开开关时，不能还卡在上次会话的退避里"""
    poller._state["consecutive_failures"] = 3
    poller._state["backoff_until"] = "2099-01-01 00:00:00"
    poller._state["needs_login"] = True
    poller._state["next_run_at"] = ""

    poller.reset_for_enable()

    assert poller._state["consecutive_failures"] == 0
    assert poller._state["backoff_until"] == ""
    assert poller._state["needs_login"] is False


def test_reset_for_enable_sets_next_run_immediately(cfg):
    """开关一开就要立刻显示「下次检查」，不能等调度线程醒来（最长 30s）

    实测踩过：界面上开关打开了但什么都不显示，像没生效。
    """
    poller._state["next_run_at"] = ""
    poller.reset_for_enable()

    nxt = poller._state["next_run_at"]
    assert nxt, "reset_for_enable 没预估下次检查时间"

    dt = datetime.strptime(nxt, "%Y-%m-%d %H:%M:%S")
    left = (dt - datetime.now()).total_seconds()
    # 从没跑过 → 首轮提前到 FIRST_RUN_DELAY（15s）
    assert 0 < left <= poller.FIRST_RUN_DELAY_SECONDS + 5, f"预估还有 {left:.0f}s"


def test_reset_for_enable_uses_interval_when_already_ran(cfg):
    """已经跑过的，预估应该按正常间隔而不是首轮的 15 秒"""
    cfg["subscription"]["interval_minutes"] = 60
    cfg["subscription"]["jitter_percent"] = 20
    poller._state["last_run_at"] = "2026-09-26 10:00:00"
    poller._state["next_run_at"] = ""

    poller.reset_for_enable()

    dt = datetime.strptime(poller._state["next_run_at"], "%Y-%m-%d %H:%M:%S")
    left = (dt - datetime.now()).total_seconds()
    assert 60 * 60 * 0.8 - 5 <= left <= 60 * 60 * 1.2 + 5, f"预估还有 {left:.0f}s"


# ------------------------------------------------------------------
# 参数透传（手动接口必须能覆盖配置）
# ------------------------------------------------------------------

@pytest.fixture
def capture_check_all(monkeypatch):
    """记录 check_all 收到的 kwargs，不真去抓主页"""
    seen = []

    async def fake_check_all(**kw):
        seen.append(kw)
        return {"total": 0, "queued": 0, "new_found": 0, "errors": 0,
                "results": []}

    monkeypatch.setattr(svc, "check_all", fake_check_all)
    return seen


@pytest.mark.asyncio
async def test_manual_round_honours_request_params(cfg, capture_check_all):
    """前端传 max_new=1（测试期限制）不能被配置里的 3 覆盖掉

    这个 bug 真实出现过：run_round 早期签名只有 manual，
    手动接口的 download / max_new 被静默丢弃。
    """
    cfg["subscription"]["max_new_per_check"] = 3

    await poller.run_round(manual=True, download=False, max_new=1)

    assert len(capture_check_all) == 1
    assert capture_check_all[0]["download"] is False, "download 被丢弃了"
    assert capture_check_all[0]["max_new"] == 1, "max_new 被配置覆盖了"


@pytest.mark.asyncio
async def test_round_defaults_to_config_max_new(cfg, capture_check_all):
    """不传 max_new 时用配置值（自动轮询走这条）"""
    cfg["subscription"]["max_new_per_check"] = 7

    await poller.run_round(manual=True)

    assert capture_check_all[0]["max_new"] == 7
    assert capture_check_all[0]["download"] is True, "download 默认必须是 True"


@pytest.mark.asyncio
async def test_max_new_clamped_not_none_collapsed(cfg, capture_check_all):
    """0 是合法值（=不限），不能被 None 默认值吃掉；超大值要裁剪"""
    cfg["subscription"]["max_new_per_check"] = 3

    await poller.run_round(manual=True, max_new=0)
    assert capture_check_all[-1]["max_new"] == 0, "0 应该原样传下去（=不限制）"

    await poller.run_round(manual=True, max_new=99999)
    assert capture_check_all[-1]["max_new"] == 100, "超大值没被裁剪"

    await poller.run_round(manual=True, max_new=None)
    assert capture_check_all[-1]["max_new"] == 3, "None 应回落到配置值"

    assert len(capture_check_all) == 3, "三次调用都要真的到达 check_all"


def test_status_snapshot_is_serializable(cfg, temp_db):
    import json
    _seed_creators(temp_db, 2)
    st = poller.status()
    json.dumps(st, ensure_ascii=False)
    assert st["creators_enabled"] == 2
    assert set(st) >= {"enabled", "interval_minutes", "running",
                       "next_run_at", "last_result", "interval_range"}


def test_is_round_running_false_by_default():
    assert poller.is_round_running() is False
