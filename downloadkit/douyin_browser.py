"""
抖音适配层（Playwright 驱动）
================================
为什么用 Playwright 而不是纯 HTTP：

抖音现行风控（ArgusSecurityPlugin）会校验浏览器运行时产生的动态凭据。
实测结论（2026-09-26，见 docs/抖音路线验证报告-2026-09-26.md）：

  · 纯 httpx + 自写 a_bogus 签名      -> 403
  · curl_cffi 伪装 Chrome/Edge TLS 指纹 -> 403
  · F2 库 + 完整登录 Cookie（66 条）   -> 403 Uifid Not Found
  · 分享页 HTML 解析                    -> 响应仅 2492 字节 JS 挑战页

所以本模块用真实 Chromium 完成全部抖音交互：
  1. 打开创作者主页，滚动提取作品列表
  2. 打开作品页，捕获浏览器自己请求的视频流地址
  3. 在页面上下文中用 XHR 分块 Range 下载

实测性能：86MB 视频，21 秒，3.91 MB/s，ffprobe 验证通过。

登录态说明：
  用户首次扫码登录一次，浏览器 profile 会自己维持会话，之后无需干预。
  profile 目录：%LOCALAPPDATA%\\DownloadKit\\browser_profile
"""

import asyncio
import base64
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .logger import get_logger

logger = get_logger("douyin_browser")

# 作品链接中的 aweme_id
VIDEO_ID_RE = re.compile(r"/video/(\d+)")

# 只取「该创作者自己的作品网格」里的链接。
#
# 为什么不能用裸的 'a[href*="/video/"]'：抖音创作者主页上除了作品
# 网格，页脚还有全站推荐位（8 条，带 ?source=Baiduspider 的 SEO 链接），
# 它们也是 /video/ 结构，混进来会：
#   1. 把别人的视频当成该创作者的作品下载（实测下错过作者
#      「别想我没必要」的视频，而任务标题写的却是「笔吧评测室」）
#   2. 页脚推荐每次加载都变，导致「新作品」判定反复漂移
#
# 实测 DOM 结构（2026-09-26）：
#   <div data-e2e="user-post-list">        ← 外层：该作者帖子列表
#     <ul data-e2e="scroll-list">           ← 作品网格
#       <li><a href="/video/xxx">
#   <footer data-e2e="page-footer">         ← 不在 user-post-list 里，被排除
#
# 两个选择器取并集：querySelectorAll 本身去重，且滚动列表（scroll-list）
# 位于帖子列表（user-post-list）内部，任一改名都还能工作。
POST_LINK_SELECTOR = (
    '[data-e2e="user-post-list"] a[href*="/video/"], '
    '[data-e2e="scroll-list"] a[href*="/video/"]'
)

# 整页 /video/ 链接，仅用于诊断「有多少被过滤掉了」
ANY_VIDEO_LINK_SELECTOR = 'a[href*="/video/"]'


class RateLimited(Exception):
    """抖音触发风控（验证码中间页 / 安全验证 / 人机校验）。

    和「未登录」是两回事：未登录要引导用户扫码，风控要**停下来退避**，
    继续请求只会让风控更严。轮询调度器会据此指数退避，不硬刚。
    """


# 风控页的识别特征（页面标题或 URL 命中任一即判定）
# 抖音风控页标题实测为「验证码中间页」，跳转 URL 含 /captcha/
CAPTCHA_TITLE_MARKERS = ("验证码", "安全验证", "人机校验", "请完成验证")
CAPTCHA_URL_MARKERS = ("/captcha/", "verify.douyin", "/verify?")


def looks_like_captcha(title: str = "", url: str = "") -> bool:
    """判断当前页面是不是抖音的风控验证页。

    判不出来时返回 False（宁可漏判让上层按普通错误退避，
    也不要误判成风控而把正常请求停掉）。
    """
    t = (title or "").strip()
    u = (url or "").strip()
    if any(m in t for m in CAPTCHA_TITLE_MARKERS):
        return True
    return any(m in u for m in CAPTCHA_URL_MARKERS)

# 默认分块大小（实测 2MB/块 效果良好）
DEFAULT_CHUNK_SIZE = 2 * 1024 * 1024

# 短链解析结果缓存
# 抖音短链指向的内容不变，可长期缓存。
# 必要原因：v.douyin.com 限流很严（约 1 分钟放行 1~2 次），
# 订阅任务入库后不应重复请求短链域名。
_SHORT_URL_CACHE: dict[str, str] = {}

# 页面加载后的固定等待（毫秒）
PAGE_SETTLE_MS = 6000
STREAM_SETTLE_MS = 9000
SCROLL_SETTLE_MS = 1200

# 额外等待更高清晰度流出现的时间上限（毫秒）
STREAM_EXTRA_WAIT_MS = 12000

# 判定「已登录抖音」所需的 cookie 名。
# ⚠️ 只能当快速预筛，不能单独作为判定依据：
#    未登录访客抖音也会发一个「占位 sessionid」，
#    实测 4 个 cookie 全是同一个 32 位哈希值（e693e34d…），页面却没有用户信息。
#    早期版本只看 cookie 存在性，导致未登录被误判成已登录，
#    订阅功能会静默失效。最终判定见 DouyinBrowser.check_login_via_api()。
LOGIN_COOKIE_NAMES = ("sessionid", "sessionid_ss", "sid_tt", "sid_guard")

# 抖音首页（登录入口在页面右上角）
DOUYIN_HOME = "https://www.douyin.com/"

# 抖音自己的「当前登录用户」接口，未登录时返回 status_code=8 且 user 为空。
# 同源请求，浏览器会自动带上 cookie 与风控凭据。
LOGIN_PROBE_URL = (
    "https://www.douyin.com/aweme/v1/web/user/profile/self/"
    "?device_platform=webapp&aid=6383&channel=channel_pc_web"
)

_LOGIN_PROBE_JS = r"""
async ([url]) => {
    try {
        const r = await fetch(url, {
            method: 'GET',
            credentials: 'include',
            headers: {'accept': 'application/json'},
        });
        const t = await r.text();
        let j = null;
        try { j = JSON.parse(t); } catch (e) { /* 非 JSON */ }
        if (!j) {
            return {ok: false, err: '响应不是 JSON: ' + t.slice(0, 100)};
        }
        const u = j.user || j.user_info || (j.data && j.data.user);
        const logged = !!(u && (u.nickname || u.uid || u.sec_uid || u.unique_id));
        // msg 只描述「服务端说了什么」，不带「已登录/未登录」这类结论词。
        // 结论由调用方自己拼（前端会显示成「已登录：xxx」），
        // 早先这里带了「已登录: 」前缀，界面上就出现
        // 「已登录：已登录: 安琼」这种重复文案。
        if (logged) {
            return {ok: true, logged_in: true,
                    msg: (u.nickname || u.unique_id || '(无名)')
                             + ' / uid=' + (u.uid || '?')};
        }
        return {ok: true, logged_in: false,
                msg: '抖音返回 status_code=' + j.status_code + '（未登录）'};
    } catch (e) {
        return {ok: false, err: String(e)};
    }
}
"""


@dataclass
class CreatorInfo:
    """创作者信息"""
    sec_uid: str
    nickname: str = ""
    avatar: str = ""
    video_ids: list[str] = field(default_factory=list)


@dataclass
class VideoItem:
    """视频作品信息"""
    aweme_id: str
    title: str = ""
    author: str = ""
    author_sec_uid: str = ""
    cover: str = ""
    stream_url: str = ""
    size: int = 0
    # 发布日期 YYYY-MM-DD（页面「发布时间：…」字段，取不到为空串）
    publish_date: str = ""


class DouyinLoginRequired(Exception):
    """需要用户登录抖音"""


class _StreamExpired(Exception):
    """
    视频流签名过期（内部异常）

    抖音 CDN 的流地址带短时效签名，实测有效期约 5~15 秒。
    过期后同一 URL 返回 403，此时需要重新解析拿新地址并断点续传。
    """


class DouyinBrowser:
    """
    抖音浏览器会话

    典型用法::

        async with DouyinBrowser() as dy:
            if not await dy.is_logged_in():
                await dy.open_login_window()   # 需要有头模式
            creator = await dy.fetch_creator(sec_uid)
            path = await dy.download(video_id, out_dir)

    注意：
      · 实例不可跨事件循环复用
      · Playwright 同步 API 与本项目异步风格冲突，这里全用 async API
    """

    def __init__(
        self,
        headless: bool = True,
        profile_dir: Optional[Path] = None,
        download_chunk_size: int = DEFAULT_CHUNK_SIZE,
    ):
        """
        Args:
            headless: True=后台运行不弹窗；False=显示窗口（登录时用）
            profile_dir: 浏览器配置目录，存登录态
            download_chunk_size: 下载分块大小（字节）
        """
        self.headless = headless
        self.profile_dir = Path(profile_dir) if profile_dir else self._default_profile()
        self.chunk_size = download_chunk_size

        self._pw = None
        self._ctx = None
        self._lock = asyncio.Lock()

    @staticmethod
    def _default_profile() -> Path:
        """默认 profile 目录：%LOCALAPPDATA%\\DownloadKit\\browser_profile"""
        import os
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / "DownloadKit" / "browser_profile"
        return Path.home() / ".downloadkit" / "browser_profile"

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """启动浏览器（幂等）"""
        if self._ctx is not None:
            return

        async with self._lock:
            if self._ctx is not None:
                return

            try:
                from playwright.async_api import async_playwright
            except ImportError as e:
                raise RuntimeError(
                    "缺少 playwright 依赖。请执行："
                    "pip install -e \".[browser]\" && playwright install chromium"
                ) from e

            self.profile_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"启动抖音浏览器 (headless={self.headless}) profile={self.profile_dir}")

            self._pw = await async_playwright().start()
            try:
                self._ctx = await self._launch()
            except BaseException:
                # 起不来别把 playwright driver 悬着：A5 每小时失败一次
                # 就会累积一个 driver 进程。注意不能调 close()——它也要拿
                # self._lock，而当前已持锁，asyncio.Lock 不可重入会死锁。
                await self._cleanup()
                raise
            self._ctx.set_default_timeout(60000)

    async def _launch(self):
        """启动 persistent context：系统 Edge 优先，Playwright 自带 Chromium 兜底。

        channel 的各平台可执行路径由 Playwright 自己维护
        （win32: \\Microsoft\\Edge\\Application\\msedge.exe、
          linux: /opt/microsoft/msedge/msedge、darwin: /Applications/...），
        此处只传 channel 名，不重复造一份路径表。

        --no-sandbox 与 --disable-dev-shm-usage 是容器里 Chromium 系的刚需
        （root 身份、/dev/shm 默认只有 64MB），在 Windows 上无害，故统一
        加载、不按平台分支——保证 Windows exe 与 Docker 用同一份代码。
        """
        args = [
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]
        last_err: Optional[BaseException] = None
        for channel in ("msedge", None):   # None = playwright 自带 chromium
            label = channel or "chromium"
            try:
                return await self._pw.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    headless=self.headless,
                    locale="zh-CN",
                    viewport={"width": 1440, "height": 900},
                    args=args,
                    **({"channel": channel} if channel else {}),
                )
            except Exception as e:         # noqa: BLE001 — 逐个内核试到能用为止
                last_err = e
                logger.warning(f"以 channel={label} 启动抖音浏览器失败，回退: {e}")

        raise RuntimeError(
            "抖音浏览器启动失败：系统 Edge 与 Playwright 自带 Chromium 都不可用。"
            "Windows 请确认已安装 Microsoft Edge；"
            "Docker/Linux 请执行 `playwright install chromium`"
            "或安装 microsoft-edge-stable。"
        ) from last_err

    async def _cleanup(self) -> None:
        """释放浏览器与 playwright driver（不加锁，调用方必须已持锁）。

        与 close() 分离，是因为 start() 的失败路径本身就在锁内，
        再调 close() 会因 asyncio.Lock 不可重入而死锁。
        """
        if self._ctx is not None:
            try:
                await self._ctx.close()
            except Exception as e:
                logger.warning(f"关闭浏览器上下文失败: {e}")
            self._ctx = None
        if self._pw is not None:
            try:
                await self._pw.stop()
            except Exception as e:
                logger.warning(f"停止 Playwright 失败: {e}")
            self._pw = None
        logger.info("抖音浏览器已关闭")

    async def close(self) -> None:
        """关闭浏览器（幂等）"""
        async with self._lock:
            await self._cleanup()

    async def __aenter__(self) -> "DouyinBrowser":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    def _require_ctx(self):
        if self._ctx is None:
            raise RuntimeError("浏览器未启动，请先 await start()")
        return self._ctx

    async def _get_page(self, reuse: bool = True):
        """取一个页面。reuse=False 时开新标签，避免污染主页状态"""
        ctx = self._require_ctx()
        if reuse and ctx.pages:
            return ctx.pages[0]
        return await ctx.new_page()

    # ------------------------------------------------------------------
    # 登录态
    # ------------------------------------------------------------------

    async def has_login_cookies(self) -> bool:
        """只读 cookie 做快速预筛（<100ms，不导航页面）。

        ⚠️ 命中不等于已登录：未登录访客也有占位 sessionid。
        仅用于「值不值得再花钱调接口确认」，或页面已在抖音域名时
        配合 check_login_via_api() 使用。

        Returns:
            True 表示存在登录态 cookie（可能是占位值）
        """
        await self.start()
        ctx = self._require_ctx()
        try:
            cookies = await ctx.cookies(DOUYIN_HOME)
        except Exception:
            # 部分 Playwright 版本不接受带参数的 cookies()
            cookies = await ctx.cookies()
        names = {c["name"] for c in cookies if c.get("value")}
        return bool(set(LOGIN_COOKIE_NAMES) & names)

    async def check_login_via_api(self) -> tuple[bool, str]:
        """用抖音自己的接口判定登录态（权威判定）

        为什么必须走接口：
            未登录访客抖音也会发占位 sessionid（实测 4 个 cookie
            全是同一个 32 位哈希值），只看 cookie 会把未登录
            误判成已登录，订阅功能就会静默失效。
            /aweme/v1/web/user/profile/self/ 未登录时返回
            status_code=8 且 user 为空，这是服务端给的权威答案。

        必须在 www.douyin.com 页面上下文里调用，否则 fetch 变成跨域，
        cookie 不会带上，判定必然失败。本方法会保证页面已在抖音域名。

        Returns:
            (是否已登录, 说明文字)
        """
        await self.start()
        page = await self._get_page()

        # about:blank 上发同源 fetch 会被 CORS 拦，先确保在抖音域名
        if not page.url.startswith("https://www.douyin.com"):
            try:
                await page.goto(DOUYIN_HOME, wait_until="domcontentloaded",
                                timeout=60000)
                await page.wait_for_timeout(2000)
            except Exception as e:
                return False, f"打开抖音首页失败：{e}"

        try:
            res = await page.evaluate(_LOGIN_PROBE_JS, [LOGIN_PROBE_URL])
        except Exception as e:
            return False, f"探测请求失败：{e}"

        if not res.get("ok"):
            return False, str(res.get("err", "探测失败"))
        return bool(res.get("logged_in")), str(res.get("msg", ""))

    async def open_login_page(self) -> None:
        """打开抖音首页，等用户自己点右上角扫码。

        必须在 headless=False 的实例上调用，否则用户看不到窗口。
        """
        await self.start()
        page = await self._get_page()
        await page.goto(DOUYIN_HOME, wait_until="domcontentloaded", timeout=60000)
        logger.info("已打开抖音登录页")

    async def is_logged_in(self) -> bool:
        """检查是否已登录抖音（走接口的权威判定）"""
        await self.start()
        try:
            logged, msg = await self.check_login_via_api()
        except Exception as e:
            logger.error(f"检查登录态失败: {e}")
            return False

        logger.info(f"登录态检查: {'已登录' if logged else '未登录'} — {msg}")
        return logged

    async def clear_login_cookies(self) -> int:
        """清除登录 cookie（退出登录）。

        Returns:
            实际清除的 cookie 数量
        """
        await self.start()
        ctx = self._require_ctx()
        try:
            cookies = await ctx.cookies(DOUYIN_HOME)
        except Exception:
            cookies = await ctx.cookies()
        targets = [c for c in cookies if c["name"] in LOGIN_COOKIE_NAMES]
        for c in targets:
            await ctx.clear_cookies(
                name=c["name"], domain=c["domain"], path=c.get("path", "/")
            )
        if targets:
            logger.info(f"已清除 {len(targets)} 条登录 cookie")
        return len(targets)

    async def wait_for_login(self, timeout: int = 300) -> bool:
        """
        等待用户完成登录（需要有头模式，用户手动扫码）

        只轮询 cookie，不重复导航页面。用户在当前页面扫码后
        cookie 会自动写入 profile，无需刷新。

        Args:
            timeout: 最长等待秒数

        Returns:
            是否登录成功
        """
        await self.start()
        logger.info(f"等待登录，最长 {timeout} 秒...")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            # 用接口判定而不是 cookie：未登录访客也有占位 sessionid，
            # 只看 cookie 会一进来就误判成「已登录」。
            try:
                logged, msg = await self.check_login_via_api()
            except Exception as e:
                logger.debug(f"[Login] 探测失败，继续等: {e}")
                logged, msg = False, str(e)
            if logged:
                logger.info(f"登录成功 — {msg}")
                return True
            await asyncio.sleep(3)

        logger.warning("等待登录超时")
        return False

    async def import_cookies(self, cookies_file: str | Path) -> int:
        """
        导入 Netscape 格式 cookies.txt

        用于首次配置时从已有浏览器迁移登录态，避免重新扫码。

        Args:
            cookies_file: cookies.txt 路径

        Returns:
            导入的 cookie 数量
        """
        await self.start()
        path = Path(cookies_file)
        if not path.exists():
            raise FileNotFoundError(f"Cookie 文件不存在: {path}")

        cookies = self._parse_netscape(path)
        if not cookies:
            logger.warning(f"未从 {path} 解析到 douyin.com 的 cookie")
            return 0

        await self._require_ctx().add_cookies(cookies)
        logger.info(f"已导入 {len(cookies)} 条 douyin cookie")
        return len(cookies)

    @staticmethod
    def _parse_netscape(path: Path) -> list[dict]:
        """解析 Netscape cookies.txt"""
        out: list[dict] = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line:
                    continue
                # HttpOnly 行以 #HttpOnly_ 开头，不是注释
                if line.startswith("#HttpOnly_"):
                    line = line[len("#HttpOnly_"):]
                elif line.startswith("#"):
                    continue

                cols = line.split("\t")
                if len(cols) < 7:
                    continue
                domain, _flag, cpath, secure, _exp, name, value = cols[:7]
                if "douyin.com" not in domain or not name.strip() or not value:
                    continue
                out.append({
                    "name": name.strip(),
                    "value": value,
                    "domain": domain,
                    "path": cpath or "/",
                    "secure": secure.upper() == "TRUE",
                })
        return out

    # ------------------------------------------------------------------
    # 创作者
    # ------------------------------------------------------------------

    async def _raise_if_captcha(self, page) -> None:
        """识别抖音风控验证页，命中就抛 RateLimited。

        取标题和 URL 一起判断：只看标题会在跳转过程中漏判，
        只看 URL 会漏掉「标题已变成验证码中间页但 URL 还没变」的瞬间。
        读标题失败（页面已关）按未命中处理，不掩盖真正的错误。
        """
        title = ""
        try:
            title = (await page.title() or "").strip()
        except Exception:
            return
        url = getattr(page, "url", "") or ""
        if looks_like_captcha(title, url):
            raise RateLimited(f"抖音触发风控验证页：{title or url}")

    async def fetch_creator(
        self,
        sec_uid: str,
        max_scrolls: int = 5,
    ) -> CreatorInfo:
        """
        获取创作者信息与作品列表

        Args:
            sec_uid: 创作者稳定 ID（从主页 URL 解析）
            max_scrolls: 滚动次数，决定抓多少条

        Returns:
            CreatorInfo（含 nickname 和 video_ids）
        """
        if not sec_uid:
            raise ValueError("sec_uid 不能为空")

        await self.start()
        page = await self._get_page(reuse=False)
        try:
            await page.goto(
                f"https://www.douyin.com/user/{sec_uid}",
                wait_until="domcontentloaded",
                timeout=90000,
            )
            await page.wait_for_timeout(PAGE_SETTLE_MS)

            # 风控页会把「抓不到作品」和「没有作品」混为一谈，
            # 必须先识别出来抛异常，否则会建出一个空基线，
            # 把该创作者所有存量作品当成新作品下载。
            await self._raise_if_captcha(page)

            nickname, avatar = await self._extract_creator_meta(page)

            links: set[str] = set()
            for _ in range(max_scrolls):
                await page.evaluate("() => window.scrollBy(0, 2500)")
                await page.wait_for_timeout(SCROLL_SETTLE_MS)
                found = await page.eval_on_selector_all(
                    POST_LINK_SELECTOR,
                    "els => els.map(e => e.getAttribute('href'))",
                )
                links.update(found)

            video_ids = sorted({
                m.group(1)
                for m in (VIDEO_ID_RE.search(link) for link in links)
                if m
            }, reverse=True)

            # 诊断：整页有多少 /video/ 链接、被过滤掉多少。
            # 过滤数为 0 说明页脚推荐没渲染（正常），不为 0 才值得关注。
            try:
                total = await page.eval_on_selector_all(
                    ANY_VIDEO_LINK_SELECTOR,
                    "els => els.length",
                )
            except Exception:
                total = -1

            if not video_ids and max_scrolls > 0:
                # 空结果必须报错而不是返回空列表：调用方会拿它建基线，
                # 空基线意味着「没有水位线」，下一轮会把所有存量作品
                # 当成新作品下载下来。
                #
                # max_scrolls=0 是「只取昵称头像、不抓列表」的调用
                # （add_subscription 订阅时就走这条）：循环一次都不跑，
                # 空列表是预期而不是故障。2026-09-27 用户实测：保护
                # 无条件触发，把每一个新订阅都挡死，预览（滚动 3 次）
                # 却一切正常，一好一坏很难往这上面想。
                raise RuntimeError(
                    f"主页没抓到任何作品（作品区选择器可能失效）。"
                    f"页面 /video/ 链接共 {total} 条"
                )

            if not max_scrolls:
                logger.info(f"创作者 {nickname or sec_uid}: 只取主页资料，未抓作品列表")
            elif total and total > len(video_ids):
                logger.info(
                    f"创作者 {nickname or sec_uid}: 作品区提取 {len(video_ids)} 条，"
                    f"整页 {total} 条，过滤掉 {total - len(video_ids)} 条非本人作品链接"
                )
            else:
                logger.info(f"创作者 {nickname or sec_uid}: 提取 {len(video_ids)} 个作品")
            return CreatorInfo(
                sec_uid=sec_uid,
                nickname=nickname,
                avatar=avatar,
                video_ids=video_ids,
            )
        finally:
            await page.close()

    @staticmethod
    async def _extract_creator_meta(page) -> tuple[str, str]:
        """从主页提取昵称和头像"""
        data = await page.evaluate(r"""() => {
            let nickname = '';
            const n = document.querySelector('[data-e2e="user-detail-nickname"]')
                   || document.querySelector('.user-info-name')
                   || document.querySelector('h1');
            if (n) {
                nickname = (n.innerText || '').trim();
            }
            if (!nickname) {
                // 兜底：user-info 块，按徽章关键词切分
                const info = document.querySelector('[data-e2e="user-info"]');
                if (info) {
                    let raw = (info.innerText || '').trim();
                    for (const mk of ['认证', '徽章', '粉丝', '获赞', '关注']) {
                        const i = raw.indexOf(mk);
                        if (i > 0) { raw = raw.slice(0, i); break; }
                    }
                    nickname = raw.trim();
                }
            }
            // 去掉可能残留的徽章尾巴
            for (const mk of ['认证', '徽章', '官方', '品牌']) {
                const i = nickname.indexOf(mk);
                if (i > 0) { nickname = nickname.slice(0, i); break; }
            }

            const a = document.querySelector('[data-e2e="user-detail-avatar"] img')
                   || document.querySelector('.user-info-avatar img')
                   || document.querySelector('img.avatar');
            return {
                nickname: nickname.slice(0, 40),
                avatar: a ? (a.src || '') : ''
            };
        }""")
        return data.get("nickname", ""), data.get("avatar", "")

    # ------------------------------------------------------------------
    # 视频
    # ------------------------------------------------------------------

    async def resolve_stream(self, aweme_id: str) -> VideoItem:
        """
        解析视频信息，捕获浏览器请求的真实视频流地址

        关键点：视频流地址带签名且有时效，不能用 httpx 直接取，
        必须在页面上下文中下载（见 download）。

        Args:
            aweme_id: 作品 ID

        Returns:
            VideoItem（含 stream_url 和 size）
        """
        if not aweme_id:
            raise ValueError("aweme_id 不能为空")

        await self.start()
        page = await self._get_page(reuse=False)

        # 抖音用 MSE 播放，浏览器会按 Range 分段拉取。
        #
        # ⚠️ 关键点：响应头 Content-Length 是【本次分片】的大小，
        #    不是整个视频的长度。真实总长在 Content-Range 末尾，形如：
        #        Content-Range: bytes 0-624247/54774762
        #                              ^分片        ^总长
        #
        # 早期实现误用 Content-Length 当总长，导致只下载到第一个分片
        # （624KB）就以为下完了。必须读 Content-Range。
        agg: dict[str, dict] = {}
        state = {"best_total": 0}

        def on_response(resp):
            ct = (resp.headers or {}).get("content-type", "")
            if "video" not in ct:
                return
            headers = resp.headers or {}

            # 本次响应体大小
            try:
                chunk = int(headers.get("content-length", 0) or 0)
            except (TypeError, ValueError):
                chunk = 0

            # 资源总长（从 Content-Range 尾部取）
            total = 0
            cr = headers.get("content-range", "")
            if cr and "/" in cr:
                tail = cr.rsplit("/", 1)[-1].strip()
                if tail.isdigit():
                    total = int(tail)

            if chunk <= 0 and total <= 0:
                return

            rec = agg.setdefault(
                resp.url,
                {"url": resp.url, "total": 0, "max_chunk": 0, "hits": 0},
            )
            rec["hits"] += 1
            if total > rec["total"]:
                rec["total"] = total
            if chunk > rec["max_chunk"]:
                rec["max_chunk"] = chunk
            if rec["total"] > state["best_total"]:
                state["best_total"] = rec["total"]

        page.on("response", on_response)
        try:
            await page.goto(
                f"https://www.douyin.com/video/{aweme_id}",
                wait_until="domcontentloaded",
                timeout=90000,
            )
            await page.wait_for_timeout(PAGE_SETTLE_MS)

            # 触发播放，让浏览器自己去请求视频流
            try:
                await page.evaluate(
                    "() => { const v = document.querySelector('video');"
                    " if (v) { v.muted = true; v.play(); } }"
                )
            except Exception:
                pass
            await page.wait_for_timeout(STREAM_SETTLE_MS)

            # 抖音会按清晰度依次请求多个流，等一会儿让高码率流也出现。
            # 实测：1080P 流（86MB）比 720P 流（54MB）晚约 5~8 秒出现，
            # 只等固定时间会漏掉最高画质。
            # 提前收敛：新出现的流比当前最大小 20% 以上就停止等待。
            settle = 0
            while settle < STREAM_EXTRA_WAIT_MS:
                await page.wait_for_timeout(1500)
                settle += 1500
                cur = state["best_total"]
                sized = [r["total"] for r in agg.values() if r["total"] > 0]
                if not sized:
                    continue
                if cur and max(sized) >= cur * 1.2:
                    continue
                break

            title, author, cover, author_sec_uid, publish_date = \
                await self._extract_video_meta(page)

            # 优先用 Content-Range 声明的总长
            sized = [r for r in agg.values() if r["total"] > 0]
            if sized:
                best = max(sized, key=lambda r: r["total"])
            elif agg:
                # 没有 Content-Range，退回按单次最大分片估算
                best = max(agg.values(), key=lambda r: r["max_chunk"])
                logger.warning(
                    f"作品 {aweme_id} 未捕获到 Content-Range，"
                    f"总长可能不准确"
                )
            else:
                raise RuntimeError(
                    f"未捕获到视频流，作品可能不存在或需要登录: {aweme_id}"
                )

            logger.info(
                f"作品 {aweme_id}: {title[:30]} "
                f"总长 {best['total'] or best['max_chunk']:,} bytes "
                f"({len(agg)} 个候选流)"
            )
            return VideoItem(
                aweme_id=aweme_id,
                title=title,
                author=author,
                author_sec_uid=author_sec_uid,
                cover=cover,
                stream_url=best["url"],
                size=best["total"] or best["max_chunk"],
                publish_date=publish_date,
            )
        finally:
            page.remove_listener("response", on_response)
            await page.close()

    @staticmethod
    async def _extract_video_meta(page) -> tuple[str, str, str, str, str]:
        """
        从作品页提取标题、作者、封面、作者 sec_uid、发布日期

        页面结构（2026-09 实测）：
          · 标题      [data-e2e="video-desc"]
          · 作者信息  [data-e2e="user-info"]，内含昵称 + 认证徽章 + 粉丝数
          · 作者主页  a[href*="/user/MS4wLj..."]，href 里带 sec_uid
          · 发布日期  播放器信息区「发布时间：2026-09-24 16:59」
            （2026-09-27 实测：body 文本正则直接命中；兜底再扫
             [data-e2e*="time"] 元素。取不到返回空串，命名层会回落）

        注意：作者区块的 innerText 混着昵称/徽章/粉丝数，不能直接用，
        需取第一行作为昵称；sec_uid 从链接 href 提取最可靠。

        JS 用 split 而非正则：正则里的反斜杠会和 Python 字符串转义打架
        （曾导致 SyntaxWarning 与 Page.evaluate SyntaxError）。
        """
        data = await page.evaluate(r"""() => {
            const t = document.querySelector('[data-e2e="video-desc"]')
                   || document.querySelector('h1');

            // 作者昵称 + sec_uid：一起从 /user/ 链接取
            // 注意：链接文本可能夹带"认证徽章""科技自媒体"等徽章文案
            //（实测该 DOM 节点无独立昵称元素），需要按徽章关键词切分。
            let author = '';
            let secUid = '';
            const links = document.querySelectorAll('a[href*="/user/MS4wLj"]');
            for (const a of links) {
                const href = a.getAttribute('href') || '';
                const parts = href.split('/user/');
                if (parts.length < 2) continue;
                const id = parts[1].split('?')[0].split('/')[0];
                if (!id) continue;
                if (!secUid) secUid = id;

                const raw = (a.innerText || '').trim();
                if (!raw || raw.length > 60) continue;

                // 徽章文案切分：取第一个徽章关键词之前的部分
                const marks = ['认证', '徽章', '官方', '品牌', '企业',
                               '实力', '榜上有名', '精选'];
                let name = raw;
                for (const mk of marks) {
                    const i = name.indexOf(mk);
                    if (i > 0) { name = name.slice(0, i); break; }
                }
                name = name.trim();
                if (name && name.length <= 30) {
                    author = name;
                    break;
                }
            }

            // 兜底：还没拿到昵称时，用 user-info 块
            if (!author) {
                const info = document.querySelector('[data-e2e="user-info"]');
                if (info) {
                    let raw = (info.innerText || '').trim();
                    for (const mk of ['认证', '徽章', '粉丝', '获赞', '关注']) {
                        const i = raw.indexOf(mk);
                        if (i > 0) { raw = raw.slice(0, i); break; }
                    }
                    author = raw.trim();
                }
            }
            if (!author) {
                const alt = document.querySelector('[data-e2e="video-author-name"]')
                         || document.querySelector('.account-name');
                if (alt) author = alt.innerText.trim();
            }

            const c = document.querySelector('[data-e2e="video-cover"] img')
                   || document.querySelector('.video-player img');

            // 发布日期：正文「发布时间：2026-09-24 16:59」，其次扫带 time 的元素
            let pubDate = '';
            const body = document.body.innerText || '';
            const m = body.match(/发布时间\s*[:：]\s*(\d{4}-\d{2}-\d{2})/);
            if (m) {
                pubDate = m[1];
            } else {
                const cand = document.querySelectorAll('[data-e2e*="time"], time');
                for (const el of cand) {
                    const m2 = ((el.innerText || '') + ' ' + (el.textContent || ''))
                        .match(/(\d{4}-\d{2}-\d{2})/);
                    if (m2) { pubDate = m2[1]; break; }
                }
            }

            return {
                title: t ? t.innerText.trim().slice(0, 300) : '',
                author: author.slice(0, 60),
                cover: c ? (c.src || '') : '',
                secUid: secUid,
                pubDate: pubDate
            };
        }""")
        return (
            data.get("title", ""),
            data.get("author", ""),
            data.get("cover", ""),
            data.get("secUid", ""),
            data.get("pubDate", ""),
        )

    async def download(
        self,
        aweme_id: str,
        out_dir: Path,
        filename: Optional[str] = None,
        progress_callback=None,
        max_attempts: int = 3,
    ) -> Path:
        """
        下载视频（分块 Range）

        为什么不用 httpx：
          视频流地址带签名，直接用 httpx 会返回 351 字节的 HTML 错误页。
          必须在页面上下文中用 XHR 请求。

        ⚠️ 关键约束：流地址有极短的有效期（实测约 5~15 秒）。
        超过有效期后同一个 URL 会返回 403 Forbidden。
        因此：
          1. 每次尝试都重新解析，拿最新 URL（不跨尝试复用）
          2. 分块过程中若收到 403/非 MP4，立即换新 URL 并从当前偏移续传
          3. 不做跨请求缓存 VideoItem.stream_url

        实测：54.7MB 视频，10 秒，5.2 MB/s，ffprobe 验证通过。

        Args:
            aweme_id: 作品 ID
            out_dir: 输出目录
            filename: 自定义文件名（不含扩展名）
            progress_callback: 进度回调 (downloaded: int, total: int)
            max_attempts: 签名过期重试次数

        Returns:
            下载文件的 Path
        """
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        target = out_dir / f"{filename or aweme_id}.mp4"
        part = target.with_suffix(".mp4.part")

        last_error: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            try:
                return await self._download_once(
                    aweme_id, target, part, progress_callback
                )
            except _StreamExpired as e:
                last_error = e
                if attempt == max_attempts:
                    break
                logger.warning(
                    f"流签名过期（第 {attempt}/{max_attempts} 次），"
                    f"重新解析并续传"
                )
                # 保留已下载的 .part，下次从断点继续
                await asyncio.sleep(1.5)

        # 全部失败：清理半成品
        part.unlink(missing_ok=True)
        raise last_error or RuntimeError("下载失败")

    async def _download_once(
        self,
        aweme_id: str,
        target: Path,
        part: Path,
        progress_callback,
    ) -> Path:
        """单次下载尝试（内部方法）"""
        import time

        # 每次尝试都重新解析，拿到新鲜的签名 URL
        item = await self.resolve_stream(aweme_id)

        # 断点续传：.part 已存在则接着写
        written = part.stat().st_size if part.exists() else 0
        if written:
            logger.info(f"断点续传，从 {written:,} bytes 继续")

        page = await self._get_page()
        started = time.time()

        logger.info(
            f"开始下载 {aweme_id} -> {target.name} "
            f"(总长 {item.size:,} bytes，已完成 {written:,})"
        )

        try:
            with open(part, "ab" if written else "wb") as f:
                start = written
                while start < item.size:
                    end = min(start + self.chunk_size - 1, item.size - 1)

                    res = await page.evaluate(
                        r"""async ([url, s, e, isFirst]) => {
                            try {
                                const r = await new Promise((ok, no) => {
                                    const x = new XMLHttpRequest();
                                    x.open('GET', url, true);
                                    x.responseType = 'arraybuffer';
                                    x.setRequestHeader('Range', 'bytes=' + s + '-' + e);
                                    x.onload = () => ok(x);
                                    x.onerror = () => no(new Error('xhr error'));
                                    x.timeout = 60000;
                                    x.send();
                                });
                                if (r.status === 403 || r.status === 401) {
                                    return {ok: false, expired: true,
                                            status: r.status};
                                }
                                const u8 = new Uint8Array(r.response);
                                if (u8.length === 0) {
                                    return {ok: false, empty: true};
                                }
                                // 只有第一块需要校验 MP4 头。
                                // 后续块是中间数据，没有 ftyp，
                                // 若也校验会全部误判为错误页。
                                if (isFirst && u8.length >= 8) {
                                    const head = String.fromCharCode(
                                        u8[4], u8[5], u8[6], u8[7]);
                                    if (head !== 'ftyp') {
                                        return {ok: false, notMp4: true};
                                    }
                                }
                                let str = '';
                                for (let i = 0; i < u8.length; i += 0x8000) {
                                    str += String.fromCharCode.apply(
                                        null, u8.subarray(i, i + 0x8000));
                                }
                                return {ok: true, b64: btoa(str)};
                            } catch (e) {
                                return {ok: false, err: String(e)};
                            }
                        }""",
                        [item.stream_url, start, end, start == 0 or written == 0],
                    )

                    if res.get("expired"):
                        # 签名过期：抛专用异常，外层换新 URL 续传
                        raise _StreamExpired(
                            f"流签名已过期 (HTTP {res.get('status')}) @{start}"
                        )

                    if not res.get("ok"):
                        if res.get("empty"):
                            raise _StreamExpired(f"分块返回空数据 @{start}")
                        if res.get("notMp4"):
                            raise RuntimeError(
                                f"@{start} 返回的不是视频数据（错误页）"
                            )
                        raise RuntimeError(
                            f"分块下载失败 @{start}-{end}: {res.get('err')}"
                        )

                    chunk = base64.b64decode(res["b64"])
                    if not chunk:
                        raise _StreamExpired(f"分块返回空数据 @{start}")

                    f.write(chunk)
                    written += len(chunk)
                    start = end + 1

                    if progress_callback:
                        progress_callback(written, item.size)

                    # 轻微限速，避免触发风控
                    await page.wait_for_timeout(80)

            part.replace(target)

            elapsed = time.time() - started
            actual = target.stat().st_size
            speed = actual / 1024 / 1024 / max(elapsed, 0.1)
            logger.info(
                f"下载完成 {target.name}: {actual:,} bytes "
                f"用时 {elapsed:.1f}s 速度 {speed:.2f} MB/s"
            )

            # 完整性校验：与声明总长比对
            if actual < item.size * 0.99:
                target.unlink(missing_ok=True)
                raise RuntimeError(
                    f"下载不完整：得到 {actual:,} bytes，"
                    f"预期 {item.size:,} bytes"
                )

            return target

        except Exception as e:
            logger.error(f"下载失败 {aweme_id}: {type(e).__name__}: {e}")
            raise

    async def resolve_note(
        self,
        aweme_id: str,
    ) -> dict:
        """解析图文/实况作品页，返回图片与实况视频配对数据。

        必须在已登录的浏览器会话中调用（带用户 cookie），
        纯 HTTP 无法拿到内容（slidesinfo API 返回 filter reason=8）。

        Returns:
            dict: {
                "aweme_id": str,
                "title": str,
                "author": str,
                "author_sec_uid": str,
                "images": list[str],   # 全部图片 URL（去重）
                "motion_pairs": list[dict],  # [{"img": ..., "video": ...}]
                "publish_date": str,
            }

            另外，落地页被重定向到非图文页（调用方类型判错）时返回
            ``{"type_mismatch": True, "aweme_id": ...}``，调用方应改走
            ``resolve_stream``，不要当图文解析。
        """
        if not aweme_id:
            raise ValueError("aweme_id 不能为空")

        await self.start()
        page = await self._get_page(reuse=False)

        note_url = f"https://www.douyin.com/note/{aweme_id}"
        logger.info(f"[ResolveNote] 打开图文页: {note_url}")
        try:
            await page.goto(note_url, wait_until="domcontentloaded", timeout=60000)
            # 图文页需要比视频页更久加载 swiper 内容
            await page.wait_for_timeout(PAGE_SETTLE_MS + 3000)

            # 风控检查
            await self._raise_if_captcha(page)

            # 抖音会把 /note/{视频ID} 重定向回 /video/{id}。导航后回读真实
            # 地址，确认这确实是图文页——否则说明调用方的类型判错了
            # （短链被限流时 resolve_short_url 返回原短链、或只传了裸
            # aweme_id），这时必须显式报回去，而不是把视频页当图文解析。
            landed = page.url or ""
            if not re.search(r"/(?:note|slides)/", landed):
                logger.warning(
                    f"[ResolveNote] 落地页不是图文页，跳过: {landed[:100]}"
                )
                return {"type_mismatch": True, "aweme_id": aweme_id}

            # 提取元数据
            meta = await page.evaluate(r"""() => {
                // 标题
                const desc = document.querySelector('[data-e2e="video-desc"]')
                          || document.querySelector('h1');
                let title = desc ? (desc.innerText || '').trim() : '';
                // 图文页上 video-desc / h1 都不存在（2026-10-14 实机验证），
                // 标题只能从 document.title 里取，去掉抖音的固定后缀
                if (!title && document.title) {
                    title = document.title.replace(/\s*-\s*抖音\s*$/, '').trim();
                }

                // 作者
                let author = '';
                const links = document.querySelectorAll('a[href*="/user/MS4wLj"]');
                for (const a of links) {
                    const raw = (a.innerText || '').trim();
                    if (!raw || raw.length > 60) continue;
                    let name = raw;
                    for (const mk of ['认证', '徽章', '官方', '品牌', '企业', '实力', '榜上有名', '精选']) {
                        const i = name.indexOf(mk);
                        if (i > 0) { name = name.slice(0, i); break; }
                    }
                    name = name.trim();
                    if (name && name.length <= 30) { author = name; break; }
                }

                // sec_uid
                let secUid = '';
                for (const a of links) {
                    const href = a.getAttribute('href') || '';
                    const parts = href.split('/user/');
                    if (parts.length >= 2) {
                        const id = parts[1].split('?')[0].split('/')[0];
                        if (id) { secUid = id; break; }
                    }
                }

                // 发布日期
                let pubDate = '';
                const body = document.body.innerText || '';
                const m = body.match(/发布时间\s*[:：]\s*(\d{4}-\d{2}-\d{2})/);
                if (m) pubDate = m[1];

                return { title, author, secUid, pubDate };
            }""")

            # 检测轮播项数。
            #
            # ⚠️ 必须和下面取图/取视频的 DOM 查询同一口径：都排除 clone。
            #    抖音轮播通常开 loop 模式，swiper.slides.length 会包含前后
            #    克隆项（N+2 或 N+4），拿它当循环上限的话，末尾几个 idx 会
            #    超出「排除 clone 后的 DOM 列表」——静默 return null，
            #    最后几张图就漏掉了。
            slide_count = await page.evaluate(r"""() => {
                const swiperEl = document.querySelector('.swiper, [class*="swiper-container"]');
                if (swiperEl && swiperEl.swiper) {
                    return Array.from(swiperEl.swiper.slides)
                        .filter(s => !s.classList.contains('swiper-slide-clone')).length;
                }
                return document.querySelectorAll(
                    '.dySwiperSlide:not(.swiper-slide-clone), .swiper-slide:not(.swiper-slide-clone)'
                ).length;
            }""")
            logger.info(f"[ResolveNote] 检测到 {slide_count} 个轮播项（已排除 clone）")

            # 切换每个 slide，收集图片和视频
            all_img_urls: list[str] = []
            motion_pairs: list[dict] = []
            seen_imgs: set[str] = set()
            seen_vids: set[str] = set()

            for i in range(slide_count):
                # 切换到第 i 个【真实】slide。
                #
                # ⚠️ 不能直接 slideTo(i)：loop 模式下 swiper 的索引里混着
                #    克隆项，i 会指到克隆上，取到的就是重复/错位的图。
                #    先定位到「排除 clone 后的第 i 个」真实元素，再回查它
                #    在完整 slides 数组里的绝对下标交给 swiper。
                await page.evaluate(r"""(idx) => {
                    const swiperEl = document.querySelector('.swiper, [class*="swiper-container"]');
                    if (swiperEl && swiperEl.swiper) {
                        const all = Array.from(swiperEl.swiper.slides);
                        const real = all.filter(s => !s.classList.contains('swiper-slide-clone'));
                        const target = real[idx];
                        if (!target) return;
                        const abs = all.indexOf(target);
                        swiperEl.swiper.slideTo(abs >= 0 ? abs : idx);
                        return;
                    }
                    // 2026-10-14 实机：抖音图文页的 .dySwiperSlide 上根本没挂
                    // swiper 对象（swiperEl 为 null 或 swiper 为 undefined），
                    // 上面这段永远走不到。这时退而求其次，把目标 slide 滚进
                    // 视口，至少让懒加载的 <img>/<video> 能加载出来。
                    const slides = document.querySelectorAll(
                        '.dySwiperSlide:not(.swiper-slide-clone), .swiper-slide:not(.swiper-slide-clone)'
                    );
                    const el = slides[idx];
                    if (el && el.scrollIntoView) {
                        el.scrollIntoView({block: 'center', inline: 'center'});
                    }
                }""", i)
                await page.wait_for_timeout(800)

                slide_data = await page.evaluate(r"""(idx) => {
                    const slides = document.querySelectorAll(
                        '.dySwiperSlide:not(.swiper-slide-clone), .swiper-slide:not(.swiper-slide-clone)'
                    );
                    if (idx >= slides.length) return null;
                    const slide = slides[idx];

                    // 取最大图片
                    let bestImg = null;
                    let bestSize = 0;
                    for (const img of slide.querySelectorAll('img')) {
                        const src = img.src || img.getAttribute('data-src') || '';
                        const w = img.naturalWidth || img.width || 0;
                        const h = img.naturalHeight || img.height || 0;
                        if (src && !src.startsWith('data:') && src.includes('douyinpic')
                                && w * h > bestSize && w >= 100 && h >= 100) {
                            bestSize = w * h;
                            bestImg = src;
                        }
                    }

                    // 取视频（实况照片的 video 元素）
                    let bestVid = null;
                    for (const v of slide.querySelectorAll('video')) {
                        const src = v.src || v.currentSrc || '';
                        if (src && !src.includes('.mp3') && !src.includes('about:blank')) {
                            bestVid = src;
                            break;
                        }
                    }
                    // 也检查 source 子元素
                    if (!bestVid) {
                        for (const v of slide.querySelectorAll('video source')) {
                            const src = v.src || '';
                            if (src && !src.includes('.mp3')) { bestVid = src; break; }
                        }
                    }

                    return { img: bestImg, vid: bestVid };
                }""", i)

                if not slide_data:
                    continue
                img_url = slide_data.get("img") or ""
                vid_url = slide_data.get("vid") or ""

                if img_url and img_url not in seen_imgs:
                    seen_imgs.add(img_url)
                    all_img_urls.append(img_url)

                if vid_url and vid_url not in seen_vids and img_url:
                    seen_vids.add(vid_url)
                    motion_pairs.append({"img": img_url, "video": vid_url})

            result = {
                "aweme_id": aweme_id,
                "title": (meta.get("title") or f"douyin_{aweme_id}")[:300],
                "author": (meta.get("author") or "")[:60],
                "author_sec_uid": meta.get("secUid") or "",
                "images": all_img_urls,
                "motion_pairs": motion_pairs,
                "publish_date": meta.get("pubDate") or "",
            }
            logger.info(
                f"[ResolveNote] 作品 {aweme_id}: "
                f"{len(all_img_urls)} 图, {len(motion_pairs)} 对实况"
            )
            return result

        finally:
            await page.close()


# ----------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------

def extract_sec_uid(url: str) -> Optional[str]:
    """
    从抖音链接中提取创作者稳定 ID (sec_uid)

    支持的链接格式：
      · https://www.douyin.com/user/MS4wLjABAAAA...
      · https://www.douyin.com/share/user/MS4wLjABAAAA...
      · https://www.iesdouyin.com/share/user/MS4wLjABAAAA...
      · https://v.douyin.com/XXXX/  （短链，无法直接解析，需先跳转）
      · 含 sec_user_id= / sec_uid= 参数的分享链接

    Args:
        url: 抖音链接

    Returns:
        sec_uid，提取失败返回 None
    """
    if not url:
        return None

    # URL 参数优先：短链跳转后的 URL 往往同时带路径和参数，
    # 参数最可靠
    for pat in (
        r"[?&]sec_?user_?id=([A-Za-z0-9_\-]{20,})",
        r"[?&]sec_uid=([A-Za-z0-9_\-]{20,})",
    ):
        m = re.search(pat, url)
        if m:
            return m.group(1)

    # 路径形式：/user/<sec_uid> 和 /share/user/<sec_uid>
    # （兼容 www.douyin.com 与 www.iesdouyin.com）
    m = re.search(r"douyin\.com/(?:share/)?user/([A-Za-z0-9_\-]{20,})", url)
    if m:
        return m.group(1)

    return None


def extract_aweme_id(url_or_text: str) -> Optional[str]:
    """
    从链接或分享文案中提取作品 ID

    支持：
      · https://www.douyin.com/video/7689023840848006451
      · https://v.douyin.com/XXXX/  （短链，需先跳转）
      · 整段分享文案（含链接）

    Args:
        url_or_text: 链接或分享文案

    Returns:
        aweme_id，提取失败返回 None
    """
    if not url_or_text:
        return None

    m = re.search(r"/video/(\d{15,25})", url_or_text)
    if m:
        return m.group(1)

    m = re.search(r"[?&]modal_id=(\d{15,25})", url_or_text)
    if m:
        return m.group(1)

    m = re.search(r"\b(7\d{18})\b", url_or_text)
    if m:
        return m.group(1)

    return None


async def resolve_short_url(
    url: str,
    retries: int = 3,
    browser: Optional["DouyinBrowser"] = None,
) -> str:
    """
    解析抖音短链，返回最终 URL

    用 httpx 跟随跳转即可，不需要浏览器。
    实测 7/7 短链解析成功（见验证报告 2.1）。

    ⚠️ 已知限制：v.douyin.com 短链域名有严格限流。
    实测约 1 分钟内只放行 1~2 次请求，超出会 ConnectError
    （注意是连接层被拒，不是 HTTP 4xx/5xx）。

    对策：
      1. 进程内缓存已解析结果（短链内容不变，可长期缓存）
      2. httpx 带指数退避重试
      3. 回退到浏览器跳转

    生产环境的正确做法是：用户添加订阅/下载任务时解析一次并入库，
    之后都用完整 URL，不再重复请求短链域名。

    Args:
        url: 短链，如 https://v.douyin.com/XXXX/
        retries: httpx 重试次数
        browser: 可选的浏览器实例，用于回退方案

    Returns:
        最终 URL；全部失败时返回原 url
    """
    import httpx

    # 入口规整：调用方可能传进整段分享文案，或没带 scheme 的裸链接。
    # httpx 对无 scheme 的输入不会在 build_request 时报错，而是拼出一个
    # 相对路径，直到 send 时才抛 UnsupportedProtocol —— 于是白跑满 retries
    # 次指数退避（2s+4s），再走一次注定失败的浏览器回退，最后返回原文，
    # 调用方只能拿到一句「没找到创作者 ID」的误导性报错。
    raw = (url or "").strip()
    if raw and not raw.startswith(("http://", "https://")):
        m = re.search(
            r"[a-z0-9.-]*douyin\.com/[^\s一-鿿，。！？、）)]+",
            raw,
            re.IGNORECASE,
        )
        raw = "https://" + m.group(0) if m else ""
    if not raw or "v.douyin.com" not in raw:
        return url
    url = raw

    # 1) 缓存命中
    cached = _SHORT_URL_CACHE.get(url)
    if cached:
        logger.debug(f"短链缓存命中: {url}")
        return cached

    def _useless_landing(final: str) -> bool:
        """落到裸首页 = 被风控拦了，不是创作者主页。

        v.douyin.com 风控时会把无 JS/无 cookie 的请求直接重定向到
        www.douyin.com/ —— 跳是跳了，但提不出 sec_uid。这种结果
        一旦写进缓存，整个进程都拿首页去提 ID，怎么提都是
        「短链跳转后没找到创作者 ID」。2026-09-27 用户实测：
        预览刚成功、紧接着订阅就 400，坏落地/坏缓存就是元凶。
        """
        try:
            return urllib.parse.urlparse(final).path in ("", "/")
        except Exception:
            return True

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }

    for attempt in range(1, retries + 1):
        try:
            async with httpx.AsyncClient(
                timeout=30, follow_redirects=True, headers=headers
            ) as client:
                resp = await client.get(url)
                final = str(resp.url)
                if final.rstrip("/") == url.rstrip("/"):
                    raise RuntimeError("短链未跳转")
                if _useless_landing(final):
                    # 落到裸首页 = 确定性拦截（验证码/风控降级），不是
                    # 瞬时网络错：重试只会白白消耗 v.douyin.com 的限流
                    # 额度、加重风控，直接 break 去浏览器回退（带 cookie）
                    logger.info(f"短链被拦到首页（疑似风控），转浏览器回退: {final[:80]}")
                    break
                _SHORT_URL_CACHE[url] = final
                logger.info(f"短链解析: {url} -> {final[:80]}")
                return final
        except Exception as e:
            if attempt < retries:
                delay = 2 ** attempt
                logger.debug(
                    f"短链解析失败({attempt}/{retries}) {url}: {e}，{delay}s 后重试"
                )
                await asyncio.sleep(delay)
            else:
                logger.warning(f"短链解析失败({retries}次) {url}: {e}")

    # 回退：让浏览器去跳转
    if browser is not None:
        try:
            await browser.start()
            page = await browser._get_page(reuse=False)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                final = page.url
                if _useless_landing(final):
                    # 落首页先看是不是验证码中间页 —— 两种情况处置完全不同：
                    # 验证码要按风控语义上报（RateLimited 穿透出去，调用方
                    # 退避，继续请求只会让风控更严）；普通落首页按链接无效
                    # 处理（不缓存坏结果，返回原文让调用方引导贴主页链接）。
                    try:
                        title = (await page.title() or "").strip()
                    except Exception:
                        title = ""
                    if looks_like_captcha(title, final):
                        raise RateLimited(
                            f"短链触发抖音风控验证：{title or final[:80]}"
                        )
                    raise RuntimeError(f"浏览器回退也落到首页: {final[:80]}")
                _SHORT_URL_CACHE[url] = final
                logger.info(f"短链解析(浏览器回退): {url} -> {final[:80]}")
                return final
            finally:
                await page.close()
        except RateLimited:
            raise
        except Exception as e:
            logger.warning(f"短链浏览器回退失败 {url}: {e}")

    return url


async def parse_creator_url(
    url: str,
    browser: Optional["DouyinBrowser"] = None,
) -> Optional[str]:
    """
    解析任意抖音链接，返回 sec_uid

    会自动处理短链。

    Args:
        url: 创作者主页链接或分享文案
        browser: 可选浏览器实例，短链限流时作为回退

    Returns:
        sec_uid；失败返回 None
    """
    sec = extract_sec_uid(url)
    if sec:
        return sec

    # 尝试从短链跳转结果中提取
    m = re.search(r"https?://[^\s]*douyin\.com/[^\s]*", url)
    if m:
        final = await resolve_short_url(m.group(0), browser=browser)
        return extract_sec_uid(final)

    return None


async def parse_video_url(
    url_or_text: str,
    browser: Optional["DouyinBrowser"] = None,
) -> Optional[str]:
    """
    解析任意抖音链接或分享文案，返回 aweme_id

    会自动处理短链。

    Args:
        url_or_text: 视频链接或整段分享文案
        browser: 可选浏览器实例，短链限流时作为回退

    Returns:
        aweme_id；失败返回 None
    """
    aid = extract_aweme_id(url_or_text)
    if aid:
        return aid

    m = re.search(r"https?://[^\s]*douyin\.com/[^\s]*", url_or_text)
    if m:
        final = await resolve_short_url(m.group(0), browser=browser)
        return extract_aweme_id(final)

    return None
