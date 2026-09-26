"""
douyin_browser 单元测试（纯函数，不启动浏览器）

运行：
  pytest tests/test_douyin_browser.py -v
  python tests/test_douyin_browser.py      # 也可直接运行
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from downloadkit.douyin_browser import (  # noqa: E402
    extract_aweme_id,
    extract_sec_uid,
    parse_creator_url,
    parse_video_url,
    resolve_short_url,
)

SEC_UID = "MS4wLjABAAAA9jVXMI9P5Gye45GdF88OIr1Frk2Gf1q7PS416m3PxGo"
AWEME_ID = "7689023840848006451"


# ----------------------------------------------------------------------
# sec_uid 提取（纯本地，无网络）
# ----------------------------------------------------------------------

@pytest.mark.parametrize("url,expect", [
    (f"https://www.douyin.com/user/{SEC_UID}", SEC_UID),
    (f"https://www.douyin.com/user/{SEC_UID}?from_ssr=1", SEC_UID),
    (f"https://www.douyin.com/share/user/{SEC_UID}", SEC_UID),
    (f"https://www.douyin.com/user/{SEC_UID}?vid=123", SEC_UID),
    ("https://www.douyin.com/share/user/abc?sec_uid=MS4wLjABAAAAtest123456",
     "MS4wLjABAAAAtest123456"),
    ("https://www.douyin.com/x?sec_user_id=MS4wLjABAAAAparam123456",
     "MS4wLjABAAAAparam123456"),
])
def test_extract_sec_uid(url, expect):
    assert extract_sec_uid(url) == expect


@pytest.mark.parametrize("url", [
    "",
    None,
    "https://www.douyin.com/video/123",
    "https://example.com/user/abc",
    "不是抖音链接",
])
def test_extract_sec_uid_fail(url):
    assert extract_sec_uid(url) is None


# ----------------------------------------------------------------------
# aweme_id 提取
# ----------------------------------------------------------------------

@pytest.mark.parametrize("text,expect", [
    (f"https://www.douyin.com/video/{AWEME_ID}", AWEME_ID),
    (f"https://www.douyin.com/note/{AWEME_ID}", AWEME_ID),
    (f"https://www.douyin.com/jingxuan?modal_id={AWEME_ID}", AWEME_ID),
    (f"https://www.douyin.com/discover?modal_id={AWEME_ID}", AWEME_ID),
    (f"3.82 :9pm 11/29 手搓游戏本  https://www.douyin.com/video/{AWEME_ID}  复制此链接",
     AWEME_ID),
    (f"9.41 04/10 一直占着？#未来导演扶持计划  {AWEME_ID}", AWEME_ID),
])
def test_extract_aweme_id(text, expect):
    assert extract_aweme_id(text) == expect


@pytest.mark.parametrize("text", [
    "",
    None,
    "https://v.douyin.com/NmgEXMPQS-Y/",   # 短链，无法本地解析
    "完全无关的文本",
    "12345",
])
def test_extract_aweme_id_fail(text):
    assert extract_aweme_id(text) is None


# ----------------------------------------------------------------------
# 短链解析（真实网络）
#
# ⚠️ v.douyin.com 限流很严：实测约 1 分钟只放行 1~2 次请求，
#    超出会 ConnectError（连接层被拒，不是 HTTP 4xx/5xx）。
#    因此这些用例需要显式开关，默认跳过，避免污染测试结果。
#
# 开启方式：
#     set DOWNLOADKIT_NETWORK_TESTS=1
#     pytest tests/test_douyin_browser.py -v
# ----------------------------------------------------------------------

import os  # noqa: E402

_network_required = pytest.mark.skipif(
    os.environ.get("DOWNLOADKIT_NETWORK_TESTS") != "1",
    reason="需要真实网络。设置 DOWNLOADKIT_NETWORK_TESTS=1 开启"
)


@_network_required
@pytest.mark.asyncio
async def test_resolve_short_url_creator():
    """主页短链 -> 能提取出 sec_uid"""
    final = await resolve_short_url("https://v.douyin.com/XSM0myNtEX8/")
    sec = extract_sec_uid(final)
    assert sec is not None, f"未能从 {final} 提取 sec_uid"
    assert sec == SEC_UID


@_network_required
@pytest.mark.asyncio
async def test_resolve_short_url_video():
    """视频短链 -> 能提取出 aweme_id"""
    final = await resolve_short_url("https://v.douyin.com/NmgEXMPQS-Y/")
    aid = extract_aweme_id(final)
    assert aid is not None, f"未能从 {final} 提取 aweme_id"
    assert aid == AWEME_ID


@_network_required
@pytest.mark.asyncio
async def test_short_url_cache():
    """短链解析结果应被缓存，第二次不再请求网络"""
    from downloadkit.douyin_browser import _SHORT_URL_CACHE

    url = "https://v.douyin.com/VlWn1dDzS2w/"
    first = await resolve_short_url(url, retries=1)
    assert url in _SHORT_URL_CACHE, "第一次解析后应写入缓存"

    cached = _SHORT_URL_CACHE[url]
    second = await resolve_short_url(url, retries=1)
    assert second == cached, "第二次应命中缓存"
    assert first == second


@pytest.mark.asyncio
async def test_resolve_short_url_passthrough():
    """非短链 URL 应原样返回，不发请求"""
    url = "https://www.douyin.com/video/123"
    assert await resolve_short_url(url) == url


@pytest.mark.asyncio
async def test_short_url_cache_hit_no_network(monkeypatch):
    """
    缓存命中时不应发起网络请求（纯本地，可离线运行）

    这是缓存逻辑的关键保证：订阅入库后重复解析不会碰抖音限流。
    """
    from downloadkit.douyin_browser import _SHORT_URL_CACHE

    url = "https://v.douyin.com/TESTCACHE123/"
    target = f"https://www.douyin.com/video/{AWEME_ID}"
    _SHORT_URL_CACHE[url] = target

    def _boom(*a, **kw):
        raise AssertionError("缓存命中时不应创建 HTTP 客户端")

    monkeypatch.setattr("httpx.AsyncClient", _boom)

    try:
        assert await resolve_short_url(url) == target
    finally:
        _SHORT_URL_CACHE.pop(url, None)


@pytest.mark.asyncio
async def test_short_url_failure_returns_original(monkeypatch):
    """网络失败时应返回原 url，不抛异常"""
    url = "https://v.douyin.com/FAILCASE123/"

    async def _noop(*a, **kw):
        return None

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            raise RuntimeError("模拟网络故障")

    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    monkeypatch.setattr("asyncio.sleep", _noop)

    assert await resolve_short_url(url, retries=2) == url


# ----------------------------------------------------------------------
# 高层解析函数
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_parse_creator_url_full_link():
    """完整主页链接（不走网络）"""
    sec = await parse_creator_url(
        f"长按复制此条消息 https://www.douyin.com/user/{SEC_UID}")
    assert sec == SEC_UID


@pytest.mark.asyncio
async def test_parse_video_url_share_text():
    """分享文案（不走网络）"""
    aid = await parse_video_url(
        f"9.41 04/10 一直占着 https://www.douyin.com/video/7687290113549733135 复制此链接")
    assert aid == "7687290113549733135"


@pytest.mark.asyncio
async def test_parse_urls_invalid():
    """无效输入返回 None，不抛异常"""
    assert await parse_creator_url("") is None
    assert await parse_video_url("") is None
    assert await parse_creator_url("纯文本没有链接") is None
    assert await parse_video_url("纯文本没有链接") is None


# ----------------------------------------------------------------------
# 直接运行支持
# ----------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "--no-header", "-x"]))
