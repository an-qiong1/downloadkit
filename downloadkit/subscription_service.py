"""
创作者订阅 - 服务层
=====================
把「订阅关系（SQLite）」和「抖音站点（Playwright）」接起来。

分层理由：
  subscription.py  只管存，不碰网络，好测
  service.py       碰网络（解析链接、抓主页），但不碰 SQL 细节
  server.py        只做 HTTP 收发

登录态说明：
  抓创作者主页需要登录。未登录时抖音对主页的限制明显，
  所以这里把登录态检查放在最前面，把「请先登录」当正常业务结果返回，
  而不是抛 500。
"""

import asyncio
import re
from typing import Optional

from .logger import get_logger
from . import subscription as store
from .douyin_browser import RateLimited  # noqa: F401  （对外也用它做 isinstance）

logger = get_logger("subscription")


# 从整段分享文案里捞 douyin 链接。
# 不带 http scheme 也要能捞到（「打开抖音搜索」那类文案里的 v.douyin.com/xxx
# 常常就是裸的），调用方补 scheme；前缀用 [a-z0-9.-]* 是为了保住
# www. / v. / www.ies 这些子域——否则「iesdouyin.com」会被截成「douyin.com」。
_SHARE_URL_RE = re.compile(
    r"(?:[a-z]+://)?[a-z0-9.-]*douyin\.com/[^\s一-鿿，。！？、）)]+",
    re.IGNORECASE,
)


def _with_scheme(url: str) -> str:
    """给没带 scheme 的链接补 https://"""
    return url if url.startswith(("http://", "https://")) else "https://" + url


def _extract_share_url(text: str) -> str:
    """从分享文案里抽出纯 douyin 链接（带 scheme），抽不到返回空串

    ⚠️ 这里必须返回**纯 URL**。历史 bug：把整段文案直接丢给
    resolve_short_url，httpx 会拼出一个没有 scheme 的相对路径，
    必然失败，还白等 3 次指数退避重试。
    """
    m = _SHARE_URL_RE.search(text or "")
    return _with_scheme(m.group(0)) if m else ""


def _to_int(value) -> int:
    """aweme_id 转整数，转不出来按 0 处理。

    抖音 aweme_id 是雪花算法的 19 位数字，转成 int 才能比较大小；
    直接比字符串在位数不同时会出错。
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


class LoginRequired(Exception):
    """需要先登录抖音"""


def _browser():
    """取共享的浏览器实例（不启动，只取）"""
    from .douyin import _browser_instance
    return _browser_instance


async def _resolve_sec_uid(url: str) -> str:
    """把用户粘贴的各种东西解析成 sec_uid

    支持：
      · 直接粘 sec_uid 本身
      · https://www.douyin.com/user/MS4wLjABAAAA...
      · https://v.douyin.com/xxx/ 短链（走浏览器跳转）
      · 带一堆文案的分享内容（正则捞 URL 出来）
    """
    from .douyin_browser import extract_sec_uid

    text = (url or "").strip()
    if not text:
        raise ValueError("请输入创作者主页链接")

    sec_uid = extract_sec_uid(text)
    if sec_uid:
        return sec_uid

    # 分享文案里捞第一个 douyin 链接
    share_url = _extract_share_url(text)
    if share_url:
        sec_uid = extract_sec_uid(share_url)
        if sec_uid:
            return sec_uid

    # 短链：必须用浏览器跳转解析。注意 v.douyin.com 限流很严
    # （实测约 1 分钟只放行 1~2 次），所以先查进程内缓存。
    if "v.douyin.com" in text or "iesdouyin.com/share" in text:
        if not share_url:
            raise ValueError(
                "没从这段文字里找到 douyin.com 链接，请直接复制主页链接"
            )
        browser = _browser()
        if browser is None:
            raise LoginRequired("解析短链需要浏览器，请先启动程序并登录抖音")
        from .douyin_browser import resolve_short_url
        # 实参顺序曾经写反过：resolve_short_url(url, retries=3, browser=None)，
        # 早年写成 resolve_short_url(browser, text) → url 收到浏览器对象 →
        # 函数里 `if "v.douyin.com" not in url` 直接抛
        # TypeError: argument of type 'DouyinBrowser' is not iterable。
        # 所以这里：URL 走位置参数，浏览器**必须**走关键字参数。
        final_url = await resolve_short_url(share_url, browser=browser)
        sec_uid = extract_sec_uid(final_url)
        if sec_uid:
            return sec_uid
        raise ValueError("短链跳转后没找到创作者 ID，请直接复制主页链接")

    # 裸 sec_uid
    if text.startswith("MS4wLjABAAAA") and len(text) >= 40:
        return text

    raise ValueError(
        "认不出这个链接。请复制创作者主页链接，"
        "长这样：https://www.douyin.com/user/MS4wLjABAAAA..."
    )


async def _require_login() -> None:
    browser = _browser()
    if browser is None:
        raise LoginRequired("后台浏览器未启动，请重启程序后重试")
    logged, detail = await browser.check_login_via_api()
    if not logged:
        raise LoginRequired(f"请先在「设置 → 抖音账号登录」里登录抖音（{detail}）")


# ==================================================================
# 对外接口
# ==================================================================

async def list_subscriptions() -> dict:
    """列出全部订阅 + 总览"""
    creators = store.list_creators()
    # 附带每个创作者已发现的作品数
    for c in creators:
        c["works_count"] = len(store.list_seen_works(c["sec_uid"], limit=10_000))
    return {"creators": creators, "stats": store.stats()}


async def add_subscription(url: str, fetch_profile: bool = True) -> dict:
    """订阅一个创作者

    Args:
        url: 主页链接 / 短链 / sec_uid
        fetch_profile: 是否顺便抓一次主页拿昵称头像。
            False 则只存 ID，昵称留空（省一次页面加载，但要手动填）

    Returns:
        订阅记录

    Raises:
        ValueError: 链接认不出
        LoginRequired: 需要登录
    """
    sec_uid = await _resolve_sec_uid(url)

    existing = store.get_creator(sec_uid)
    if existing:
        return existing

    nickname = avatar = home_url = ""
    if fetch_profile:
        await _require_login()
        browser = _browser()
        # max_scrolls=0：订阅时只要昵称头像，不抓作品列表。
        # 抓列表留给 A4 的增量检查（check_creator）去做，订阅阶段不需要。
        info = await browser.fetch_creator(sec_uid, max_scrolls=0)
        nickname = info.nickname
        avatar = info.avatar
        home_url = f"https://www.douyin.com/user/{sec_uid}"
        logger.info(f"订阅 {nickname or sec_uid}（抓了主页资料）")
    else:
        home_url = f"https://www.douyin.com/user/{sec_uid}"

    rec = store.add_creator(sec_uid, nickname, avatar, home_url)
    rec["works_count"] = 0
    return rec


async def remove_subscription(sec_uid: str) -> bool:
    """取消订阅。已发现的作品记录保留，重新加回不会重复下载。"""
    return store.remove_creator(sec_uid)


async def toggle_subscription(sec_uid: str, enabled: bool) -> dict:
    """暂停/恢复轮询"""
    if not store.set_creator_enabled(sec_uid, enabled):
        raise ValueError("没有订阅这个创作者")
    return store.get_creator(sec_uid)


async def update_scope(sec_uid: str, scope: str, param: str = "") -> dict:
    """设置某创作者的下载范围（P2-1）。

    改完**下次检查生效**，不立刻触发下载 —— 立刻下会让「改配置」
    这个动作变成「马上开一坨任务」，出乎意料。

    Args:
        sec_uid: 创作者 ID
        scope: only_new / backfill_n / all
        param: 仅 backfill_n 用的 N

    Returns:
        更新后的订阅记录

    Raises:
        ValueError: 取值非法，或创作者不存在
    """
    return store.set_creator_scope(sec_uid, scope, param)


async def get_creator_detail(sec_uid: str, limit: int = 50) -> dict:
    """单个创作者详情 + 已发现作品列表"""
    rec = store.get_creator(sec_uid)
    if not rec:
        raise ValueError("没有订阅这个创作者")
    return {
        "creator": rec,
        "works": store.list_seen_works(sec_uid, limit=limit),
    }


# ==================================================================
# 预览：不入库，只看主页能抓到什么
# ==================================================================

async def preview_creator(url: str, max_scrolls: int = 3) -> dict:
    """抓一次主页看看有多少作品，但不入库。

    给用户一个「订阅前先看看」的能力，也方便排查
    「为什么抓不到作品」这类问题。

    Args:
        url: 主页链接
        max_scrolls: 滚动次数，决定抓多少条
    """
    sec_uid = await _resolve_sec_uid(url)
    await _require_login()
    browser = _browser()

    info = await browser.fetch_creator(sec_uid, max_scrolls=max_scrolls)
    existing = store.get_creator(sec_uid)
    return {
        "sec_uid": sec_uid,
        "nickname": info.nickname,
        "avatar": info.avatar,
        "video_count": len(info.video_ids),
        "video_ids": info.video_ids[:20],
        "subscribed": existing is not None,
    }


# ==================================================================
# 增量检查（A4 核心）
# ==================================================================
# 为什么首次检查只建基线、不回补历史视频：
#   订阅一个已有 500 个作品的博主，用户要的是「他以后发什么」，
#   不是「把他过去 500 个全下下来」。后者既慢又占盘，而且
#   大概率触发抖音风控。所以第一次检查只把现有作品标记为
#   「已见」，之后只处理基线之后新增的作品。
#
# 这不只是测试期的权宜之计，是订阅功能应有的默认语义。

# 每次检查滚动几次。抓太多会明显变慢，也更容易撞上限流。
CHECK_SCROLLS = 3

# 单次检查最多下载几个。0 = 不限制。
# 上限存在的意义：万一创作者一口气发 20 条，不该一次全塞进队列。
DEFAULT_MAX_NEW = 3


def _budget(max_new: int, used: int = 0) -> int:
    """本轮给补下的配额槽位。

    max_new <= 0 表示不限，映射成 -1（`_apply_backfill` 的约定）；
    否则返回剩余槽位，可能为 0 —— 0 是「这轮没你的份」，不是「随便下」。
    """
    if max_new <= 0:
        return -1
    return max(0, max_new - used)


async def _apply_backfill(rec: dict, video_ids: list[str], watermark: str,
                          budget: int, nickname: str = "",
                          scope: str = "", scope_param: str = "") -> dict:
    """按下载范围补下水位线之下的历史作品（P2-1）。

    与增量检查共用一套防重复：候选由 store.list_backfill_candidates
    筛（水位线之下 + task_id 为空），入队成功才 mark_works_seen 写
    task_id —— 所以反复检查只会捡起上次没下成的，不会重复下载。

    配额：budget 是本轮给补下的槽位（max_new 减去增量已占用的），
    0 = 不限。增量优先，余量才轮到补下 —— 新作品有时效性。

    Args:
        rec: 创作者记录（含 download_scope / scope_param）
        video_ids: 本次抓到的作品 ID，候选只能从这里出
        watermark: 基线水位线，补它之下的历史
        budget: 本轮最多入队几个，**负数 = 不限**（0 就是「一个都不剩」，
            必须和「不限」区分开，否则增量吃满配额时余量是 0，
            会被当成不限，把历史一口气全塞进队列）
        nickname: 入队任务的标题用
        scope: 临时覆盖下载范围（P2-3 手动「检查全部更新」的策略），
            空 = 用 rec 里各创作者自己设的。**不落库**，只影响本轮
        scope_param: 配合 scope=backfill_n 的 N；空 = 用 rec 的

    Returns:
        {"backfilled": 本轮入队数, "left": 按范围还差几个, "task_ids": [...]}
        scope 为 only_new 时直接回全 0。
    """
    scope = scope or rec.get("download_scope") or "only_new"
    sec_uid = rec["sec_uid"]
    if scope == "only_new":
        return {"backfilled": 0, "left": 0, "task_ids": []}

    candidates = store.list_backfill_candidates(sec_uid, video_ids, watermark)
    if not candidates:
        return {"backfilled": 0, "left": 0, "task_ids": []}

    if scope == "backfill_n":
        # N 是累计上限：先看水位线之下已经补过几个，还差多少补多少。
        # 没有这一步，每次检查都取「未下的前 N 个」，N 会被无限刷新。
        # N 的来源优先级：本轮临时策略 > 各创作者自己设的。
        raw = scope_param or rec.get("scope_param") or 0
        try:
            target = int(raw)
        except (TypeError, ValueError):
            target = 0
        already = store.count_backfilled(sec_uid, watermark)
        remaining = max(0, target - already)
        if remaining <= 0:
            return {"backfilled": 0, "left": 0, "task_ids": []}
        candidates = candidates[:remaining]
    else:  # all
        remaining = len(candidates)

    to_queue = candidates if budget < 0 else candidates[:budget]

    backfilled = 0
    task_ids = []
    for aweme_id in to_queue:
        ok, task_id, err = await _enqueue_video(
            aweme_id, sec_uid, nickname or rec.get("nickname") or ""
        )
        if ok:
            backfilled += 1
            task_ids.append(task_id)
            # 与增量同一条铁律：先入队成功，才标记已下
            store.mark_works_seen(
                sec_uid, [{"aweme_id": aweme_id, "task_id": task_id}]
            )
        else:
            logger.warning(f"补下作品 {aweme_id} 入队失败: {err}")

    left = max(0, remaining - backfilled)
    if backfilled:
        logger.info(
            f"创作者 {nickname or sec_uid}：按范围 {scope} 补下 "
            f"{backfilled} 个，还剩 {left} 个"
        )
    return {"backfilled": backfilled, "left": left, "task_ids": task_ids}


async def check_creator(
    sec_uid: str,
    download: bool = True,
    max_new: int = DEFAULT_MAX_NEW,
    max_scrolls: int = CHECK_SCROLLS,
    scope: str = "",
    scope_param: str = "",
) -> dict:
    """检查一个创作者有没有新作品。

    流程：
      1. 抓主页，拿作品 ID 列表
      2. 首次检查（还没基线）→ 全部标记为已见，一个都不下
      3. 后续检查 → filter_new_works 去重，只处理新增的
      4. 新作品入下载队列，入队成功的才标记已见

    第 4 步的顺序很关键：先入队再标记。反过来的话，
    入队失败的作品会被永久标记成「已见」，再也不会下载。

    Args:
        sec_uid: 创作者 ID
        download: False = 只检测不入队（用于「看看有没有更新」）
        max_new: 本次最多入队几个，0 = 不限制。超出的留到下次检查。
        max_scrolls: 抓主页时滚动次数
        scope: 临时覆盖下载范围（P2-3 手动检查策略），空 = 用该创作者
            自己设置的；只影响本轮，不写库
        scope_param: 配合 scope=backfill_n 的 N，空 = 用自己设置的

    Returns:
        检查结果摘要
    """
    rec = store.get_creator(sec_uid)
    if not rec:
        raise ValueError("没有订阅这个创作者")
    if not rec["enabled"]:
        return {
            "sec_uid": sec_uid, "nickname": rec["nickname"],
            "skipped": True, "reason": "已暂停轮询",
            "fetched": 0, "new_count": 0, "queued": 0, "download": False,
        }

    await _require_login()
    browser = _browser()
    info = await browser.fetch_creator(sec_uid, max_scrolls=max_scrolls)
    fetched = len(info.video_ids)

    # 昵称/头像顺手补上（订阅时用 fetch_profile=false 加的多半是空的）
    if info.nickname and info.nickname != rec["nickname"]:
        store.add_creator(sec_uid, info.nickname, info.avatar or rec["avatar"],
                          rec["home_url"])

    # ---- 首次检查：建基线，不回补 ----
    if not rec["last_checked"]:
        if not info.video_ids:
            # 一个都没抓到，基线不能建立在空数据上，
            # 否则水位线是空的，下次会把所有存量作品当新作品下载
            raise ValueError(
                "主页没抓到任何作品（可能是页面没加载完或被风控），"
                "没有建立基线，请稍后重试"
            )

        # 水位线 = 基线时最新那条作品的 ID，只写一次，之后不再更新
        watermark = max(info.video_ids, key=lambda a: _to_int(a))
        store.set_creator_baseline(sec_uid, watermark)
        marked = store.mark_works_seen(
            sec_uid,
            [{"aweme_id": a, "title": ""} for a in info.video_ids],
        )
        store.mark_creator_checked(sec_uid, last_found="")
        logger.info(
            f"创作者 {info.nickname or sec_uid} 建立基线："
            f"标记 {marked} 个存量作品为已见，不下载；水位线={watermark}"
        )
        result = {
            "sec_uid": sec_uid,
            "nickname": info.nickname or rec["nickname"],
            "baselined": True,
            "fetched": fetched,
            "marked_as_seen": marked,
            "baseline": watermark,
            "new_count": 0,
            "queued": 0,
            "download": False,
            "task_ids": [],
            "message": (
                f"已建立基线：现有 {marked} 个作品标记为「已见」，不会下载。"
                f"之后只下载订阅后新发的作品。"
            ),
        }

        # 范围补下（P2-1）：选了 backfill_n / all 的，建基线这一轮就开始补，
        # 不用等下一次检查 —— 用户订阅时就选好范围了，没必要多跑一轮。
        # 只在 download=True 时补；download=False 是「看看有没有更新」的探针。
        if download:
            bf = await _apply_backfill(
                rec, info.video_ids, watermark, budget=_budget(max_new),
                nickname=info.nickname or rec["nickname"],
                scope=scope, scope_param=scope_param,
            )
            if bf["backfilled"] or bf["left"]:
                result["queued"] = bf["backfilled"]
                result["task_ids"] = bf["task_ids"]
                result["backfilled"] = bf["backfilled"]
                result["backfill_left"] = bf["left"]
                segs = []
                if bf["backfilled"]:
                    segs.append(f"按范围补下 {bf['backfilled']} 个历史作品")
                if bf["left"]:
                    segs.append(f"还剩 {bf['left']} 个待补")
                result["message"] += "；".join([""] + segs)
        return result

    # ---- 后续检查：只处理水位线之上的真新作品 ----
    # 兼容升级前就存在的订阅：有 last_checked 但水位线是空的。
    # 这时先拿本次抓到的最大 ID 补一条保守水位线（宁可严不能松，
    # 严了只是这轮不下载，松了会把老视频下下来），下一轮开始正常。
    if not (rec.get("baseline_max_id") or "") and info.video_ids:
        watermark = max(info.video_ids, key=lambda a: _to_int(a))
        store.set_creator_baseline(sec_uid, watermark)
        store.mark_creator_checked(sec_uid, last_found="")
        logger.info(
            f"创作者 {info.nickname or sec_uid} 补建基线水位线={watermark}，本轮不下载"
        )
        return {
            "sec_uid": sec_uid,
            "nickname": info.nickname or rec["nickname"],
            "baselined": True,
            "fetched": fetched,
            "marked_as_seen": 0,
            "baseline": watermark,
            "new_count": 0,
            "queued": 0,
            "download": False,
            "message": (
                f"已补建基线水位线（{watermark}），本轮不下载任何作品，"
                f"下次检查开始生效。"
            ),
        }

    fresh, drift = store.split_new_vs_drift(sec_uid, info.video_ids)
    if drift:
        # 滑窗漂移进来的老作品：标记已见但不下载。
        # 不标记的话每次都重新判定，纯属浪费；标记了还能让「已发现」计数准确。
        store.mark_works_seen(
            sec_uid,
            [{"aweme_id": a, "title": ""} for a in drift],
        )
        logger.info(
            f"创作者 {info.nickname or sec_uid}："
            f"{len(drift)} 个滑窗漂移的老作品被水位线拦下（不下载）"
        )

    result = {
        "sec_uid": sec_uid,
        "nickname": info.nickname or rec["nickname"],
        "baselined": False,
        "fetched": fetched,
        "new_count": len(fresh),
        "drift_blocked": len(drift),
        "queued": 0,
        "download": download,
        "task_ids": [],
    }

    if not download:
        # 只看不下载：不标已见，下次检查还会算作新作品。
        # 补下同样不做 —— download=False 是探针，任何情况下都不该产生任务。
        # last_checked 维持原行为：有新作品的探针不算「检查过」，
        # 没有新作品才算（跟改造前一致，免得轮询节奏跟着变）。
        if not fresh:
            store.mark_creator_checked(sec_uid, last_found="")
            result["message"] = "没有新作品"
        else:
            result["message"] = f"发现 {len(fresh)} 个新作品（本次不下载）"
        return result

    # ---- 增量入队：新作品优先占满配额 ----
    fresh_slots = 0          # 分给增量的槽位（max_new>0 时才有意义）
    fresh_queued = 0
    if fresh:
        if max_new <= 0:
            to_queue = fresh
        else:
            to_queue = fresh[:max_new]
            fresh_slots = len(to_queue)
            if len(fresh) > len(to_queue):
                # 只在真的有剩余时才报这个字段，避免响应里出现无意义的 0
                result["pending"] = len(fresh) - len(to_queue)

        for aweme_id in to_queue:
            ok, task_id, err = await _enqueue_video(
                aweme_id, sec_uid, info.nickname or rec["nickname"]
            )
            if ok:
                fresh_queued += 1
                result["queued"] += 1
                result["task_ids"].append(task_id)
                # 只有真的入队了才标记已见
                store.mark_works_seen(
                    sec_uid, [{"aweme_id": aweme_id, "task_id": task_id}]
                )
            else:
                logger.warning(f"作品 {aweme_id} 入队失败: {err}")

    # ---- 范围补下（P2-1）：增量吃完配额，余量轮到历史作品 ----
    bf = await _apply_backfill(
        rec, info.video_ids, rec.get("baseline_max_id") or "",
        budget=_budget(max_new, fresh_slots),
        nickname=info.nickname or rec["nickname"],
        scope=scope, scope_param=scope_param,
    )
    if bf["backfilled"]:
        result["queued"] += bf["backfilled"]
        result["task_ids"] += bf["task_ids"]
        result["backfilled"] = bf["backfilled"]
    if bf["left"]:
        result["backfill_left"] = bf["left"]

    store.mark_creator_checked(sec_uid, last_found="")

    parts = []
    if fresh:
        parts.append(
            f"发现 {result['new_count']} 个新作品，入队 {fresh_queued} 个"
        )
        if result.get("pending"):
            parts.append(f"其余 {result['pending']} 个留到下次检查")
    else:
        parts.append("没有新作品")
    if bf["backfilled"]:
        parts.append(f"按范围补下 {bf['backfilled']} 个历史作品")
    if bf["left"]:
        parts.append(f"还剩 {bf['left']} 个历史作品待补")
    result["message"] = "；".join(parts)
    return result


async def check_all(download: bool = True, max_new: int = DEFAULT_MAX_NEW,
                    scope: str = "", scope_param: str = "") -> dict:
    """检查所有启用的订阅

    串行执行，不并发。理由：
      · Chromium 独占一个页面，并发抓多个主页会互相踢掉
      · 抖音限流很严（今天实测已触发验证码中间页），
        并发请求只会让风控更敏感

    遇到下面两种情况会**立即中断整轮**，不继续逐个试：
      · RateLimited —— 已经触发风控，再敲只会更严
      · LoginRequired —— 没登录，每个创作者都会以同样方式失败

    Args:
        download: False = 只发现不入队
        max_new: 单轮入队上限，0 = 不限
        scope: 临时覆盖下载范围（P2-3 手动检查策略），空 = 各创作者
            自己设置的；逐个透传给 check_creator，不落库
        scope_param: 配合 scope=backfill_n 的 N

    Returns:
        results / total / queued / new_found，
        外加 needs_login、rate_limited、stopped_at 三个中断标记，
        供轮询调度器决定「退避」还是「停下来等用户扫码」。
    """
    creators = store.list_creators(enabled_only=True)
    results = []
    needs_login = False
    rate_limited = False
    stopped_at = ""

    for c in creators:
        try:
            r = await check_creator(c["sec_uid"], download=download,
                                    max_new=max_new,
                                    scope=scope, scope_param=scope_param)
        except RateLimited as e:
            # 风控：停止本轮，后续交由调度器指数退避
            logger.warning(f"抖音触发风控，中断本轮检查：{e}")
            results.append({"sec_uid": c["sec_uid"], "nickname": c["nickname"],
                            "error": str(e)})
            rate_limited, stopped_at = True, c["nickname"] or c["sec_uid"]
            break
        except LoginRequired as e:
            logger.warning(f"登录态失效，中断本轮检查：{e}")
            results.append({"sec_uid": c["sec_uid"], "nickname": c["nickname"],
                            "error": str(e)})
            needs_login, stopped_at = True, c["nickname"] or c["sec_uid"]
            break        # 没登录就别继续试了，全都会失败
        except Exception as e:
            logger.error(f"检查 {c['nickname'] or c['sec_uid']} 失败: {e}",
                         exc_info=True)
            results.append({"sec_uid": c["sec_uid"], "nickname": c["nickname"],
                            "error": str(e)})
        else:
            results.append(r)

    return {
        "results": results,
        "total": len(creators),
        "queued": sum(r.get("queued", 0) for r in results),
        "new_found": sum(r.get("new_count", 0) for r in results),
        "needs_login": needs_login,
        "rate_limited": rate_limited,
        "stopped_at": stopped_at,
        "errors": sum(1 for r in results if r.get("error")),
    }


async def _enqueue_video(aweme_id: str, sec_uid: str, nickname: str):
    """把一个作品塞进下载队列

    下载走 fetch_content + download_content，和界面上的「资源解析」
    完全同一套逻辑（实测 86MB 1080P 71 秒那条路径）。

    Returns:
        (是否成功, task_id, 错误信息)
    """
    from .download_queue import download_queue
    from .utils import get_download_dir

    url = f"https://www.douyin.com/video/{aweme_id}"
    task_id = f"sub_{sec_uid[:12]}_{aweme_id}"

    # 已在队列里就别重复加
    if task_id in download_queue.active_tasks:
        return False, task_id, "任务已在队列中"

    async def _run(task):
        from .douyin import download_content, fetch_content

        content = await fetch_content(url)
        filepaths = await download_content(
            content, get_download_dir(), task_id=task_id
        )
        names = [fp.name for fp in filepaths] if filepaths else []
        task.filename = names[0] if names else f"{aweme_id}.mp4"
        return names

    try:
        await download_queue.add_task(
            task_id=task_id,
            url=url,
            platform="douyin",
            title=f"[订阅] {nickname}",
            download_func=_run,
        )
    except Exception as e:
        return False, "", str(e)

    logger.info(f"订阅入队: {nickname} / {aweme_id} (task={task_id})")
    return True, task_id, ""
