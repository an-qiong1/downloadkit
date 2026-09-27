"""订阅自动轮询调度器（A5）

职责：按间隔自动检查所有启用的订阅，把新作品送进下载队列。

三条硬约束，都来自实测教训：
  1. **不要撞抖音风控** —— 实测已触发过验证码中间页。
     所以默认 60 分钟一轮、间隔带随机抖动、触发风控后指数退避，
     而不是固定节律地猛敲。
  2. **不和登录抢浏览器** —— Chromium 同一 profile 只能一个实例，
     登录开有头窗口时后台无头实例必须让路。两边互相检查、互相拒绝。
  3. **空结果不建基线** —— 抓不到作品时上游已经改成抛异常，
     调度器这边只负责把异常归类成「退避」还是「等用户扫码」。

分层：本模块只管「什么时候跑」，跑什么在 subscription_service.check_all()。
"""

import asyncio
import random
import re
from datetime import datetime, timedelta
from typing import Optional

from .logger import get_logger
from . import subscription as store
from .utils import load_config, save_config

logger = get_logger("poller")

# 配置边界（分钟）
MIN_INTERVAL = 15
MAX_INTERVAL = 1440          # 24 小时
DEFAULT_INTERVAL = 60
MIN_JITTER = 0
MAX_JITTER = 50

# 检查方式（P2-2）：
#   interval  每隔 interval_minutes 检查一次（原有行为）
#   daily_at  每天在 daily_at 这个时刻检查一次
MODES = ("interval", "daily_at")
DEFAULT_DAILY_AT = "09:00"
# daily_at 模式的随机抖动上限（秒）。固定到秒地敲同样是一种固定节律，
# 抖一点站点看不出规律；0-3 分钟用户完全无感。
DAILY_JITTER_MAX = 180

_DAILY_AT_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

# 退避封顶：连续触发风控时最长等 24 小时，不无限翻倍
MAX_BACKOFF_MINUTES = 24 * 60

# 关着的时候也要周期性看一眼配置，用户打开开关才能及时生效
CONFIG_RELOAD_SECONDS = 30

# 刚打开开关后的首轮延迟：短一点让用户马上看到效果，
# 但不设为 0 —— 用户点完开关紧接着又点别的是常态，给 15 秒缓冲
FIRST_RUN_DELAY_SECONDS = 15


def _clamp_int(value, lo: int, hi: int, default: int) -> int:
    """把任意配置值裁进 [lo, hi]，非法值回落到 default"""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, n))


def _valid_daily_at(value) -> str:
    """把任意值修成合法的 'HH:MM'（00:00-23:59），修不了回落 09:00。

    配置文件可能被手改成 `9点`、`25:70`、`''` 这类东西，静默修正是
    这个模块对配置的一贯态度（见 _clamp_int）——修完 load_settings
    返回的就是实际生效值，前端回读时显示的是真的那个时间。
    """
    m = _DAILY_AT_RE.match(str(value or "").strip())
    if not m:
        return DEFAULT_DAILY_AT
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def load_settings() -> dict:
    """读轮询配置，做边界裁剪（配置文件可能被手改成离谱的值）"""
    sec = load_config().get("subscription") or {}
    mode = str(sec.get("mode") or "").strip()
    return {
        "enabled": bool(sec.get("enabled", False)),
        "mode": mode if mode in MODES else "interval",
        "daily_at": _valid_daily_at(sec.get("daily_at")),
        "interval_minutes": _clamp_int(
            sec.get("interval_minutes"), MIN_INTERVAL, MAX_INTERVAL, DEFAULT_INTERVAL
        ),
        "max_new_per_check": max(
            0, _clamp_int(sec.get("max_new_per_check"), 0, 100, 3)
        ),
        "jitter_percent": _clamp_int(
            sec.get("jitter_percent"), MIN_JITTER, MAX_JITTER, 20
        ),
    }


def save_settings(**kwargs) -> dict:
    """更新轮询配置。只写传入的字段，返回裁剪后的完整配置。"""
    current = load_settings()
    updates = {k: v for k, v in kwargs.items() if v is not None}
    if "mode" in updates:
        m = str(updates["mode"] or "").strip()
        updates["mode"] = m if m in MODES else "interval"
    if "daily_at" in updates:
        updates["daily_at"] = _valid_daily_at(updates["daily_at"])
    if "enabled" in updates:
        updates["enabled"] = bool(updates["enabled"])
    if "interval_minutes" in updates:
        updates["interval_minutes"] = _clamp_int(
            updates["interval_minutes"], MIN_INTERVAL, MAX_INTERVAL, DEFAULT_INTERVAL
        )
    if "max_new_per_check" in updates:
        updates["max_new_per_check"] = max(
            0, _clamp_int(updates["max_new_per_check"], 0, 100, 3)
        )
    if "jitter_percent" in updates:
        updates["jitter_percent"] = _clamp_int(
            updates["jitter_percent"], MIN_JITTER, MAX_JITTER, 20
        )
    if updates:
        save_config({"subscription": updates})
        logger.info(f"轮询配置已更新: {updates}")
    return load_settings()


# ==================================================================
# 运行时状态（只在事件循环里读写，无需加锁）
# ==================================================================

_state = {
    "running": False,          # 一轮正在跑
    "rounds": 0,               # 累计轮数
    "last_run_at": "",
    "last_result": {},         # 上一轮 check_all 的摘要
    "consecutive_failures": 0,
    "backoff_until": "",       # 风控退避截止时间
    "needs_login": False,      # 上一轮因未登录中断
    "next_run_at": "",         # 计划中的下次执行时间
}

# 手动「检查全部更新」和自动轮询共用，避免两轮同时抓主页
round_lock = asyncio.Lock()

_task: Optional[asyncio.Task] = None


def is_round_running() -> bool:
    """是否有一轮检查正在跑（登录要靠它判断能不能开窗口）"""
    return _state["running"]


def reset_for_enable() -> None:
    """用户刚打开开关：清掉上一次会话留下的退避和失败计数。

    不清的话会出现「我明明把开关打开了，怎么还是不检查」——
    因为上次关程序前触发的风控退避还挂在状态里。
    退避只该对「当前这次运行期间真实发生的失败」生效。
    """
    _state["consecutive_failures"] = 0
    _state["backoff_until"] = ""
    _state["needs_login"] = False

    # 立刻给出「下次检查」的预估。否则要等调度线程从 30s 的配置轮询里
    # 醒来才会写入 next_run_at，这半分钟界面上什么都不显示，
    # 用户会以为开关没生效（实测踩过）。
    # 精度不是问题：线程醒来后会用同一套 _compute_wait 重算覆盖。
    try:
        wait = _compute_wait(load_settings())
        _state["next_run_at"] = (
            datetime.now() + timedelta(seconds=wait)
        ).strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        logger.debug(f"预估下次检查时间失败（不影响功能）: {e}")
        _state["next_run_at"] = ""

    logger.info("轮询已开启，退避状态已重置")


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse(text: str):
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return None


def status() -> dict:
    """给接口/前端用的状态快照"""
    cfg = load_settings()
    out = {
        **cfg,
        "running": _state["running"],
        "rounds": _state["rounds"],
        "last_run_at": _state["last_run_at"],
        "consecutive_failures": _state["consecutive_failures"],
        "backoff_until": _state["backoff_until"],
        "needs_login": _state["needs_login"],
        "next_run_at": _state.get("next_run_at", ""),
        "interval_range": {"min": MIN_INTERVAL, "max": MAX_INTERVAL},
        "creators_enabled": len(store.list_creators(enabled_only=True)),
    }
    last = _state.get("last_result") or {}
    out["last_result"] = {
        k: last.get(k)
        for k in ("total", "queued", "new_found", "errors",
                  "rate_limited", "needs_login", "message")
        if k in last
    }
    return out


# ==================================================================
# 单轮执行
# ==================================================================

def _backoff_minutes(base_interval: int, failures: int) -> int:
    """指数退避：1 次失败等 2 倍间隔，2 次等 4 倍…封顶 24 小时"""
    if failures <= 0:
        return 0
    # 先移位再算，避免 failures 很大时 2**n 溢出得离谱
    factor = 2 ** min(failures, 8)
    return min(base_interval * factor, MAX_BACKOFF_MINUTES)


async def run_round(manual: bool = False, download: bool = True,
                    max_new: int | None = None,
                    scope: str = "", scope_param: str = "") -> dict:
    """跑一轮检查。

    自动轮询和手动「检查全部更新」都走这里，靠 round_lock 串起来，
    保证任何时刻只有一轮在抓主页（Chromium 单页面 + 抖音风控）。

    跳过条件分两处判断：
      · 锁外（自动轮询才看）—— 退避未过、已有另一轮在跑 → 直接跳过，
        不排队，否则每到时间就积压一轮
      · 锁内（自动和手动都看）—— 登录窗口插进来了 → 让路，
        因为此时 Chromium profile 被有头实例占着

    Args:
        manual: True = 用户手动触发，不受退避影响，且会排队等上一轮
        download: 本轮要不要真下载（False = 只发现不入队，排查用）
        max_new: 本轮最多入队几个，0 = 不限制；None = 用配置里的
                 max_new_per_check。手动接口必须能覆盖它 —— 测试期
                 前端固定传 1，如果这里只读配置，接口上的 max_new
                 会被静默丢掉
        scope: 临时覆盖下载范围（P2-3 手动检查策略），空 = 各创作者
                 自己设置的。自动轮询不传，永远跟随
        scope_param: 配合 scope=backfill_n 的 N

    Returns:
        本轮结果摘要；跳过时带 skipped=True 和 reason
    """
    cfg = load_settings()

    if not manual:
        bo = _parse(_state["backoff_until"])
        if bo and bo > datetime.now():
            wait = int((bo - datetime.now()).total_seconds())
            msg = f"风控退避中，本轮跳过（还剩 {max(1, wait // 60)} 分钟）"
            logger.info(msg)
            return {"skipped": True, "reason": "backoff", "message": msg}

        if round_lock.locked():
            msg = "已有另一轮检查在跑，本轮跳过"
            logger.info(msg)
            return {"skipped": True, "reason": "busy", "message": msg}

    # None → 用配置；给了值就裁剪到合理区间（0 是合法值 = 不限制）
    effective_max_new = _clamp_int(
        max_new, 0, 100, cfg["max_new_per_check"]
    )

    async with round_lock:
        # 拿到锁后再确认登录没在这一瞬间插进来
        from .douyin import is_login_running
        if is_login_running():
            msg = "登录窗口打开中，本轮跳过"
            logger.info(msg)
            return {"skipped": True, "reason": "login", "message": msg}

        _state["running"] = True
        _state["next_run_at"] = ""
        try:
            from . import subscription_service as svc
            result = await svc.check_all(
                download=download, max_new=effective_max_new,
                scope=scope, scope_param=scope_param,
            )
        except Exception as e:
            # check_all 自己会捕获大部分异常，走到这里说明是意外
            logger.error(f"轮询异常: {e}", exc_info=True)
            result = {"error": str(e), "results": [], "total": 0, "queued": 0,
                      "new_found": 0, "errors": 1,
                      "rate_limited": False, "needs_login": False}
        finally:
            _state["running"] = False

    _record_round(result, cfg=cfg)
    return result


def _record_round(result: dict, cfg: dict) -> None:
    """把一轮的结果写进状态，决定要不要退避"""
    _state["rounds"] += 1
    _state["last_run_at"] = _now_str()

    queued = int(result.get("queued", 0) or 0)
    new_found = int(result.get("new_found", 0) or 0)
    errors = int(result.get("errors", 0) or 0)

    if result.get("rate_limited"):
        message = "触发抖音风控，已进入退避"
    elif result.get("needs_login"):
        message = "登录态失效，请重新扫码"
    elif errors:
        message = f"{errors} 个创作者检查失败"
    elif new_found:
        message = f"发现 {new_found} 个新作品，入队 {queued} 个"
    else:
        message = "没有新作品"

    _state["last_result"] = {
        "total": result.get("total", 0),
        "queued": queued,
        "new_found": new_found,
        "errors": errors,
        "rate_limited": bool(result.get("rate_limited")),
        "needs_login": bool(result.get("needs_login")),
        "message": message,
    }

    if result.get("rate_limited"):
        _state["consecutive_failures"] += 1
        _apply_backoff(cfg)
        _state["needs_login"] = False
        logger.warning(
            f"触发抖音风控（连续第 {_state['consecutive_failures']} 次），"
            f"退避到 {_state['backoff_until']}"
        )
        return

    if result.get("needs_login"):
        # 未登录不是风控，不清退避计数（两回事），但要提醒用户
        _state["needs_login"] = True
        logger.warning("登录态失效，本轮中止，等用户重新扫码")
        return

    _state["needs_login"] = False

    if errors:
        _state["consecutive_failures"] += 1
        _apply_backoff(cfg)
        logger.warning(
            f"本轮有 {errors} 个创作者检查失败，"
            f"连续失败 {_state['consecutive_failures']} 次"
        )
        return

    # 干净的一轮：清零退避
    if _state["consecutive_failures"]:
        logger.info("轮询恢复正常，退避计数已清零")
    _state["consecutive_failures"] = 0
    _state["backoff_until"] = ""


def _apply_backoff(cfg: dict) -> None:
    """按连续失败次数设置退避截止时间，封顶 24 小时"""
    mins = _backoff_minutes(cfg["interval_minutes"],
                            _state["consecutive_failures"])
    _state["backoff_until"] = (
        datetime.now() + timedelta(minutes=mins)
    ).strftime("%Y-%m-%d %H:%M:%S")


# ==================================================================
# 主循环
# ==================================================================

def _wait_until_daily(at: str) -> float:
    """到下一个 daily_at 的秒数，外加 0~DAILY_JITTER_MAX 的随机抖动。

    今天这个点已经过了就算明天的：09:01 打开「每天 09:00」的开关，
    该等的是明天 09:00，而不是立刻跑一轮。

    首轮是例外：_compute_wait 会把「从没跑过」的等待压到 15 秒，
    让用户打开开关马上看到效果，跑完这一轮才进入每天的节律 ——
    否则等上十几个小时才见第一次检查，会被当成开关没生效。
    """
    hh, mm = 9, 0
    try:
        h, m = str(at).split(":")
        hh, mm = int(h), int(m)
    except (AttributeError, TypeError, ValueError):
        pass

    now = datetime.now()
    target = now.replace(
        hour=max(0, min(23, hh)), minute=max(0, min(59, mm)),
        second=0, microsecond=0,
    )
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds() + random.uniform(0, DAILY_JITTER_MAX)


def _compute_wait(cfg: dict) -> float:
    """算下一次醒来等多久。

    两种检查方式（P2-2）：
      · interval  按 interval ± jitter
      · daily_at  等到下一个每天固定时刻，加 0~3 分钟随机抖动

    两种模式共用的三步（顺序有讲究，不能随便调）：
      1. 先按模式算出基础 wait，再套 60 秒下限 —— 保证不会忙轮询
      2. 从没跑过 → 提前到 FIRST_RUN_DELAY，让打开开关马上看到效果
         （必须在下限**之后**做，否则 15 秒会被下限顶回 60 秒，形同虚设）
      3. 退避最后做，且只往上抬 —— 风控退避的优先级高于一切，
         每天定时的那一轮也一样要让路（模式换掉的只是「基础等待」）
    """
    if cfg.get("mode") == "daily_at":
        wait = _wait_until_daily(cfg.get("daily_at") or DEFAULT_DAILY_AT)
    else:
        base = cfg["interval_minutes"] * 60
        jitter = base * cfg["jitter_percent"] / 100.0
        wait = base + random.uniform(-jitter, jitter)

    wait = max(60.0, wait)

    # 从没跑过 → 快速来一轮
    if not _state["last_run_at"]:
        wait = min(wait, FIRST_RUN_DELAY_SECONDS)

    bo = _parse(_state["backoff_until"])
    if bo:
        remain = (bo - datetime.now()).total_seconds()
        if remain > 0:
            wait = max(wait, remain)

    return wait


async def _loop() -> None:
    logger.info(
        f"订阅轮询调度器已启动（默认 {DEFAULT_INTERVAL} 分钟一轮，"
        f"当前配置: {load_settings()}）"
    )
    while True:
        try:
            cfg = load_settings()
        except Exception as e:
            logger.error(f"读取轮询配置失败，稍后重试: {e}")
            await asyncio.sleep(CONFIG_RELOAD_SECONDS)
            continue

        if not cfg["enabled"]:
            _state["next_run_at"] = ""
            await asyncio.sleep(CONFIG_RELOAD_SECONDS)
            continue

        wait = _compute_wait(cfg)
        _state["next_run_at"] = (
            datetime.now() + timedelta(seconds=wait)
        ).strftime("%Y-%m-%d %H:%M:%S")
        logger.debug(f"轮询下一次: {_state['next_run_at']}（等待 {wait:.0f}s）")

        try:
            await asyncio.sleep(wait)
        except asyncio.CancelledError:
            _state["next_run_at"] = ""
            raise

        # 醒来后重新读配置：期间用户可能改了间隔或关掉了开关
        if not load_settings()["enabled"]:
            continue
        try:
            await run_round(manual=False)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error(f"轮询轮次未捕获异常: {e}", exc_info=True)


def start() -> None:
    """启动后台调度器（幂等）"""
    global _task
    if _task is not None and not _task.done():
        return
    # 必须在事件循环里调用（server 的 startup 钩子满足）
    _task = asyncio.create_task(_loop())
    logger.info("订阅轮询后台任务已创建")


async def stop() -> None:
    """停掉后台调度器（服务关闭时调用）"""
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except (asyncio.CancelledError, Exception):
        pass
    _task = None
    _state["next_run_at"] = ""
    logger.info("订阅轮询后台任务已停止")
