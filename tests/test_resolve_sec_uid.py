"""分享文案 → sec_uid 解析的回归测试

2026-09-27 用户实测事故：「创作者订阅」页点订阅和预览都报

    TypeError: argument of type 'DouyinBrowser' is not iterable

根因有两层，两层都必须钉死，只修一层等于没修：

  1. 顺序：subscription_service 调
     resolve_short_url(browser, text)，而签名是
     resolve_short_url(url, retries=3, browser=None)
     → url 收到浏览器对象 → 函数里 `if "v.douyin.com" not in url` 直接炸
  2. 内容：就算顺序对了，传进去的也是整段分享文案
     （「长按复制此条消息… https://v.douyin.com/xxx/」）。httpx 对这种
     没 scheme 的输入不报错，而是拼出相对路径，send 时才抛
     UnsupportedProtocol → 白跑满 3 次指数退避（2s+4s）→ 浏览器回退也
     失败 → 返回原文 → 报一句误导性的「短链跳转后没找到创作者 ID」。

历史教训：tests/ 里 11 处 resolve_short_url 用例全是直接调函数，
没有一条走 _resolve_sec_uid 这个唯一调用方，所以这个 bug 溜到了线上。
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

import downloadkit.subscription as store
from downloadkit.subscription_service import (
    LoginRequired,
    _extract_share_url,
    _resolve_sec_uid,
    add_subscription,
    preview_creator,
)

SHARE_TEXT = "长按复制此条消息，打开抖音搜索，查看TA的更多作品。 https://v.douyin.com/AbCdEfGh/"
RESOLVED = "https://www.douyin.com/user/MS4wLjABAAAAresolvedsecuid000000000000000000/x"


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """订阅数据落到临时目录，别污染用户真实的 ~/.downloadkit/subscriptions.db"""
    home = tmp_path / "home"
    (home / ".downloadkit").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: home))

    store._DB_DIR = home / ".downloadkit"
    store._DB_PATH = store._DB_DIR / "subscriptions.db"
    if getattr(store._local, "conn", None) is not None:
        store._local.conn.close()
    store._local.conn = None
    yield store
    if getattr(store._local, "conn", None) is not None:
        store._local.conn.close()
    store._local.conn = None


class FakeBrowser:
    """只要它是个普通对象就够 —— 被当成 url 用时就会抛
    'argument of type ... is not iterable'，正是线上那个报错。"""

    async def check_login_via_api(self):
        return True, "ok"

    async def fetch_creator(self, sec_uid, max_scrolls=3):
        return SimpleNamespace(
            nickname="笔吧评测室",
            avatar="https://img/a.jpg",
            video_ids=["1", "2", "3"],
        )

    async def start(self):
        raise RuntimeError("假浏览器不该被启动")


@pytest.fixture
def fake_browser(monkeypatch):
    b = FakeBrowser()
    monkeypatch.setattr("downloadkit.subscription_service._browser", lambda: b)
    return b


@pytest.fixture
def capture_resolve(monkeypatch):
    """替换 resolve_short_url，记录它到底收到了什么"""
    calls = []

    async def fake_resolve(url, retries=3, browser=None):
        calls.append({"url": url, "retries": retries, "browser": browser})
        return RESOLVED

    monkeypatch.setattr("downloadkit.douyin_browser.resolve_short_url", fake_resolve)
    return calls


# ------------------------------------------------------------------
# 第 1 层：抽出的必须是纯 URL
# ------------------------------------------------------------------

def test_extract_share_url_from_full_share_text():
    """整段分享文案 → 纯短链 URL（带 scheme、不含中文、不含多余文案）"""
    got = _extract_share_url(SHARE_TEXT)
    assert got == "https://v.douyin.com/AbCdEfGh/"


def test_extract_share_url_bare_link_without_scheme():
    """没带 scheme 的裸短链也要能捞到并补上 https://"""
    got = _extract_share_url("打开看看 v.douyin.com/XyZ123/ 就知道了")
    assert got == "https://v.douyin.com/XyZ123/"


def test_extract_share_url_keeps_subdomain():
    """iesdouyin.com 不能被截成 douyin.com（正则前缀必须保住子域）"""
    got = _extract_share_url("分享 https://www.iesdouyin.com/share/user/MS4wLjABAAAAabc")
    assert got.startswith("https://www.iesdouyin.com/")


def test_extract_share_url_no_link_returns_empty():
    assert _extract_share_url("纯中文，没有任何链接") == ""
    assert _extract_share_url("") == ""


# ------------------------------------------------------------------
# 第 2 层：实参顺序 —— browser 必须走关键字参数
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_resolve_called_with_url_positional_and_browser_keyword(
    fake_browser, capture_resolve
):
    """钉死线上 bug：第一个位置参数必须是 URL，browser 必须是关键字"""
    sec = await _resolve_sec_uid(SHARE_TEXT)

    assert len(capture_resolve) == 1
    got = capture_resolve[0]
    assert isinstance(got["url"], str), "url 收到了非字符串（实参顺序又反了？）"
    assert got["url"].startswith("https://v.douyin.com/")
    assert got["browser"] is fake_browser


@pytest.mark.asyncio
async def test_resolve_sec_uid_never_raises_not_iterable(monkeypatch):
    """用真实 resolve_short_url + 假浏览器对象跑一遍。

    修复前这里抛 TypeError: argument of type 'FakeBrowser' is not iterable；
    修复后应该是正常的业务报错（短链没跳到主页）。
    """
    class _FailingClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            raise RuntimeError("模拟网络故障")

    async def _noop_sleep(*a, **kw):
        return None

    monkeypatch.setattr("httpx.AsyncClient", _FailingClient)
    monkeypatch.setattr("asyncio.sleep", _noop_sleep)

    b = FakeBrowser()
    monkeypatch.setattr("downloadkit.subscription_service._browser", lambda: b)

    with pytest.raises((ValueError, LoginRequired)) as exc:
        await _resolve_sec_uid(SHARE_TEXT)

    assert "not iterable" not in str(exc.value)


@pytest.mark.asyncio
async def test_resolve_short_url_normalizes_share_text(monkeypatch):
    """resolve_short_url 自己也要防一手：整段文案进去，出来必须是纯 URL"""
    from downloadkit.douyin_browser import resolve_short_url

    class _FailingClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            raise RuntimeError("模拟网络故障")

    async def _noop(*a, **kw):
        return None

    monkeypatch.setattr("httpx.AsyncClient", _FailingClient)
    monkeypatch.setattr("asyncio.sleep", _noop)

    out = await resolve_short_url(SHARE_TEXT, retries=1)
    # 不能再把整段文案原样退回去 —— 那会让调用方报「没找到创作者 ID」
    assert out == "https://v.douyin.com/AbCdEfGh/"


@pytest.mark.asyncio
async def test_resolve_short_url_passthrough_non_douyin_text():
    """不是 douyin 链接的普通文本要原样返回，别做多余解析"""
    from downloadkit.douyin_browser import resolve_short_url

    assert await resolve_short_url("https://www.example.com/a") == \
        "https://www.example.com/a"


# ------------------------------------------------------------------
# 两条用户可见入口：订阅 / 预览
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_subscription_accepts_share_text(fake_browser, capture_resolve):
    rec = await add_subscription(SHARE_TEXT)
    assert rec["sec_uid"] == "MS4wLjABAAAAresolvedsecuid000000000000000000"
    assert rec["nickname"] == "笔吧评测室"
    assert capture_resolve[0]["url"] == "https://v.douyin.com/AbCdEfGh/"


@pytest.mark.asyncio
async def test_preview_creator_accepts_share_text(fake_browser, capture_resolve):
    out = await preview_creator(SHARE_TEXT, max_scrolls=1)
    assert out["nickname"] == "笔吧评测室"
    assert out["video_count"] == 3
    assert out["subscribed"] is False
    assert capture_resolve[0]["url"] == "https://v.douyin.com/AbCdEfGh/"


@pytest.mark.asyncio
async def test_plain_user_page_link_skips_short_url(monkeypatch, fake_browser):
    """完整主页链接不需要走短链解析（不该白白消耗抖音限流额度）"""
    calls = []

    async def boom(*a, **kw):
        calls.append(a)
        raise AssertionError("完整主页链接不该调 resolve_short_url")

    monkeypatch.setattr("downloadkit.douyin_browser.resolve_short_url", boom)
    sec = await _resolve_sec_uid("https://www.douyin.com/user/MS4wLjABAAAAplainlink0000")
    assert sec == "MS4wLjABAAAAplainlink0000"
    assert calls == []


@pytest.mark.asyncio
async def test_share_text_without_link_raises_valueerror(fake_browser):
    """认不出的输入要给中文提示，而不是抛 TypeError"""
    with pytest.raises(ValueError):
        await _resolve_sec_uid("这里什么链接都没有")


# ------------------------------------------------------------------
# 2026-09-27 第二次用户实测：预览刚成功、紧接着订阅报 400
#   「短链跳转后没找到创作者 ID」
# 根因：v.douyin.com 风控把无 JS/无 cookie 的 httpx 请求拦到裸首页
# www.douyin.com/ —— 代码只挡「没跳转」（final==url），跳到首页算
# 成功，还写进 _SHORT_URL_CACHE：之后整个进程拿首页去提 sec_uid，
# 怎么提都是「没找到」，浏览器回退的机会也没了。
# ------------------------------------------------------------------

class _HomePageClient:
    """模拟 httpx 跟随后落在裸首页（风控拦截）"""

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **kw):
        class R:
            url = "https://www.douyin.com/"
        return R()


class _UserPageClient:
    """模拟 httpx 正常落到 /user/ 主页（不能被新判定误伤）"""

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **kw):
        class R:
            url = "https://www.douyin.com/user/MS4wLjABAAAAokuserpage00000"
        return R()


class _FailClient:
    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, *a, **kw):
        raise RuntimeError("模拟网络故障")


@pytest.fixture()
def clean_short_cache(monkeypatch):
    from downloadkit import douyin_browser as db

    db._SHORT_URL_CACHE.clear()

    async def _noop_sleep(*a, **kw):
        return None

    monkeypatch.setattr("asyncio.sleep", _noop_sleep)
    yield db._SHORT_URL_CACHE
    db._SHORT_URL_CACHE.clear()


@pytest.mark.asyncio
async def test_resolve_short_url_rejects_homepage_redirect(
        monkeypatch, clean_short_cache):
    """落到裸首页不算成功：不能返回、更不能缓存"""
    from downloadkit.douyin_browser import resolve_short_url

    monkeypatch.setattr("httpx.AsyncClient", _HomePageClient)

    out = await resolve_short_url("https://v.douyin.com/HomePgX/")
    assert out == "https://v.douyin.com/HomePgX/", \
        "没浏览器回退时应返回原文，让调用方报「请直接复制主页链接」"
    assert "https://v.douyin.com/HomePgX/" not in clean_short_cache, \
        "首页被缓存了 —— 整个进程之后都拿首页提 sec_uid，必 400"


@pytest.mark.asyncio
async def test_resolve_short_url_caches_valid_user_page(
        monkeypatch, clean_short_cache):
    """正常落 /user/ 主页要照常返回并缓存（别把新判定改成矫枉过正）"""
    from downloadkit.douyin_browser import resolve_short_url

    monkeypatch.setattr("httpx.AsyncClient", _UserPageClient)

    out = await resolve_short_url("https://v.douyin.com/OkUserX/")
    assert out == "https://www.douyin.com/user/MS4wLjABAAAAokuserpage00000"
    assert clean_short_cache.get("https://v.douyin.com/OkUserX/") == out


@pytest.mark.asyncio
async def test_browser_fallback_homepage_not_cached(
        monkeypatch, clean_short_cache):
    """浏览器回退也落到首页：返回原文且不缓存坏结果"""
    from downloadkit.douyin_browser import resolve_short_url

    monkeypatch.setattr("httpx.AsyncClient", _FailClient)

    class _HomeBrowser:
        async def start(self):
            return None

        async def _get_page(self, reuse=True):
            class _P:
                url = "https://www.douyin.com/"

                async def goto(self, *a, **k):
                    return None

                async def close(self):
                    return None
            return _P()

    out = await resolve_short_url(
        "https://v.douyin.com/FbHomeX/", browser=_HomeBrowser())
    assert out == "https://v.douyin.com/FbHomeX/"
    assert "https://v.douyin.com/FbHomeX/" not in clean_short_cache


@pytest.mark.asyncio
async def test_browser_fallback_user_page_cached(
        monkeypatch, clean_short_cache):
    """浏览器回退拿到 /user/ 主页要正常返回并缓存（回退路径的正例）"""
    from downloadkit.douyin_browser import resolve_short_url

    monkeypatch.setattr("httpx.AsyncClient", _FailClient)

    class _UserBrowser:
        async def start(self):
            return None

        async def _get_page(self, reuse=True):
            class _P:
                url = "https://www.douyin.com/user/MS4wLjABAAAAfbuser000000"

                async def goto(self, *a, **k):
                    return None

                async def close(self):
                    return None
            return _P()

    out = await resolve_short_url(
        "https://v.douyin.com/FbOkX/", browser=_UserBrowser())
    assert out == "https://www.douyin.com/user/MS4wLjABAAAAfbuser000000"
    assert clean_short_cache.get("https://v.douyin.com/FbOkX/") == out


# ------------------------------------------------------------------
# 验证码中间页（2026-09-27 第三次实测：多时机读 URL 诊断出
# title=「验证码中间页」稳定不变 —— 不是读早了，是真实风控拦截）
# ------------------------------------------------------------------

class _CaptchaPage:
    url = "https://www.douyin.com/"

    async def goto(self, *a, **k):
        return None

    async def close(self):
        return None

    async def title(self):
        return "验证码中间页"


class _CaptchaBrowser:
    async def start(self):
        return None

    async def _get_page(self, reuse=True):
        return _CaptchaPage()


@pytest.mark.asyncio
async def test_browser_fallback_captcha_raises_rate_limited(
        monkeypatch, clean_short_cache):
    """验证码要按风控上报 RateLimited，不能笼统报「落到首页」

    两种情况处置完全不同：验证码 = 停下来退避（继续请求只会更严），
    普通落首页 = 链接无效、引导贴主页链接。混成一种，调用方没法退避。
    """
    from downloadkit.douyin_browser import RateLimited, resolve_short_url

    # httpx 落首页（真实场景第一步）→ break → 浏览器回退 → 验证码页
    monkeypatch.setattr("httpx.AsyncClient", _HomePageClient)

    with pytest.raises(RateLimited) as e:
        await resolve_short_url(
            "https://v.douyin.com/CaptchaX/", browser=_CaptchaBrowser())

    assert "风控验证" in str(e.value)
    assert "https://v.douyin.com/CaptchaX/" not in clean_short_cache, \
        "验证码结果不许进缓存"


@pytest.mark.asyncio
async def test_browser_fallback_captcha_not_treated_as_plain_error(
        monkeypatch, clean_short_cache):
    """验证码不该被回退段的 except 吞成「回退失败」—— RateLimited 必须穿透"""
    from downloadkit.douyin_browser import RateLimited, resolve_short_url

    monkeypatch.setattr("httpx.AsyncClient", _FailClient)

    with pytest.raises(RateLimited):
        await resolve_short_url(
            "https://v.douyin.com/CaptchaY/", browser=_CaptchaBrowser())


@pytest.mark.asyncio
async def test_httpx_homepage_lands_once_no_retry(monkeypatch, clean_short_cache):
    """落首页是确定性拦截：httpx 打一次就转浏览器回退，不重试烧限流额度"""
    from downloadkit.douyin_browser import resolve_short_url

    class _CountingClient(_HomePageClient):
        calls = 0

        async def get(self, *a, **kw):
            type(self).calls += 1
            return await super().get(*a, **kw)

    monkeypatch.setattr("httpx.AsyncClient", _CountingClient)

    out = await resolve_short_url("https://v.douyin.com/OnceX/")

    assert out == "https://v.douyin.com/OnceX/"
    assert _CountingClient.calls == 1, \
        f"落首页还重试 {_CountingClient.calls} 次 = 白烧 v.douyin.com 限流额度"
