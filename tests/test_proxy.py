"""P3-1 代理三态 + 按平台覆盖 + 测试连接

三态语义（proxy.MODES）：
    off     关闭 —— 一律直连，手动地址全忽略
    system  跟随系统 —— 用系统代理，手动地址忽略
    manual  手动 —— 平台专属 > 全局 > 直连

要守住的三条：

  1. **旧配置兼容推导不能改用户行为**（resolve_mode）：
     只有 enabled 的老配置 → false=off / 有地址=manual / 全空=system。
     推错了会出现「界面显示手动、实际走系统代理」这类两边分裂，
     或者升级后 YouTube 突然直连打不开。
  2. **off 是硬关闭**：哪怕手动地址填满，off 也必须返回 None ——
     用户点「关闭」就是要直连，填过的旧地址不许悄悄生效。
  3. **proxy/test 永远 200**：代理不通是测试结果（body.ok=false），
     不是服务故障；抛 4xx/5xx 会让前端把「代理坏了」和「接口炸了」
     混为一谈。测试全程 mock httpx，不发真实请求。
"""

import re
from pathlib import Path

import httpx
import pytest

import server
from downloadkit import proxy as proxy_mod

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "downloadkit" / "static"

# ---------------- resolve_mode：三态解析与旧配置兼容 ----------------


def test_mode_from_new_config():
    assert proxy_mod.resolve_mode({"mode": "off"}) == "off"
    assert proxy_mod.resolve_mode({"mode": "system"}) == "system"
    assert proxy_mod.resolve_mode({"mode": "manual"}) == "manual"
    # 非法 mode 当缺失处理，落回推导而不是把非法值透传下去
    assert proxy_mod.resolve_mode({"mode": "haha"}) == "system"


def test_mode_legacy_enabled_false_is_off():
    """旧 enabled=false → off，且优先于任何残留地址"""
    assert proxy_mod.resolve_mode(
        {"enabled": False, "global": "http://127.0.0.1:7890"}
    ) == "off"


def test_mode_legacy_enabled_true_with_address_is_manual():
    """旧配置填过地址 → manual：忽略它等于用户的代理悄悄失效"""
    assert proxy_mod.resolve_mode({"enabled": True, "youtube": "http://p:1"}) == "manual"
    assert proxy_mod.resolve_mode({"enabled": True, "global": "http://p:1"}) == "manual"
    # 没写 enabled 但有地址也算（enabled 缺省默认开）
    assert proxy_mod.resolve_mode({"global": "http://p:1"}) == "manual"


def test_mode_legacy_enabled_true_all_empty_is_system():
    """旧配置全空 → system：老版本 youtube 的实际行为就是走系统代理"""
    assert proxy_mod.resolve_mode(
        {"enabled": True, "global": "", "youtube": "", "douyin": "",
         "bilibili": "", "xiaohongshu": ""}
    ) == "system"


def test_mode_empty_config_is_system():
    assert proxy_mod.resolve_mode({}) == "system"
    assert proxy_mod.resolve_mode(None) == "system"


# ---------------- get_proxy_for_platform：三态行为 ----------------


def _cfg(proxy: dict):
    return {"proxy": proxy}


def test_off_is_hard_off(monkeypatch):
    """off 是硬关闭：手动地址填满也不许生效"""
    monkeypatch.setattr(proxy_mod, "get_system_proxy",
                        lambda: "http://sys:7890")
    cfg = _cfg({"mode": "off", "global": "http://manual:7890",
                "youtube": "http://yt:1"})
    for plat in ("youtube", "bilibili", "douyin", "xiaohongshu"):
        assert proxy_mod.get_proxy_for_platform(plat, cfg) is None, \
            f"{plat} 在 off 态走了代理"


def test_system_uses_system_proxy_for_every_platform(monkeypatch):
    monkeypatch.setattr(proxy_mod, "get_system_proxy",
                        lambda: "http://sys:7890")
    cfg = _cfg({"mode": "system", "global": "http://manual:7890"})
    for plat in ("youtube", "bilibili", "douyin", "xiaohongshu"):
        assert proxy_mod.get_proxy_for_platform(plat, cfg) == "http://sys:7890", \
            f"{plat} 跟随系统态没用系统代理"
    # 系统没配代理 = 直连
    monkeypatch.setattr(proxy_mod, "get_system_proxy", lambda: None)
    assert proxy_mod.get_proxy_for_platform("youtube", cfg) is None


def test_system_ignores_manual_addresses(monkeypatch):
    """跟随系统态下手动地址是死值，不许生效"""
    monkeypatch.setattr(proxy_mod, "get_system_proxy", lambda: None)
    cfg = _cfg({"mode": "system", "global": "http://manual:7890"})
    assert proxy_mod.get_proxy_for_platform("youtube", cfg) is None


def test_manual_platform_overrides_global(monkeypatch):
    monkeypatch.setattr(proxy_mod, "get_system_proxy",
                        lambda: "http://sys:7890")
    cfg = _cfg({"mode": "manual", "global": "http://global:7890",
                "youtube": "http://yt:7891"})
    assert proxy_mod.get_proxy_for_platform("youtube", cfg) == "http://yt:7891"
    # 平台没填 → 回落全局（国内平台也吃到全局）
    assert proxy_mod.get_proxy_for_platform("bilibili", cfg) == "http://global:7890"
    # 全局也没填 → 直连
    cfg2 = _cfg({"mode": "manual"})
    assert proxy_mod.get_proxy_for_platform("youtube", cfg2) is None


def test_no_config_means_system(monkeypatch):
    """不传 config = 空配置 = 跟随系统（默认态），不是「youtube 特判」"""
    monkeypatch.setattr(proxy_mod, "get_system_proxy",
                        lambda: "http://sys:7890")
    assert proxy_mod.get_proxy_for_platform("youtube") == "http://sys:7890"


def test_proxy_dict_and_yt_dlp_wrapper(monkeypatch):
    monkeypatch.setattr(proxy_mod, "get_system_proxy", lambda: None)
    cfg = _cfg({"mode": "manual", "global": "http://g:7890"})
    assert proxy_mod.get_proxy_dict("youtube", cfg) == {
        "http://": "http://g:7890", "https://": "http://g:7890",
    }
    assert proxy_mod.get_yt_dlp_proxy("youtube", cfg) == "http://g:7890"
    assert proxy_mod.get_proxy_dict("youtube", _cfg({"mode": "off"})) is None


# ---------------- POST /api/proxy/test ----------------


class FakeResp:
    def __init__(self, status_code=200):
        self.status_code = status_code


class FakeAsyncClient:
    """替身 httpx 客户端：记录构造参数，get 返回预设状态码"""

    status = 200
    last_kwargs = None
    last_url = None
    raise_on_get = None

    def __init__(self, *args, **kwargs):
        FakeAsyncClient.last_kwargs = kwargs
        FakeAsyncClient.last_url = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        FakeAsyncClient.last_url = url
        if FakeAsyncClient.raise_on_get is not None:
            raise FakeAsyncClient.raise_on_get
        return FakeResp(FakeAsyncClient.status)


@pytest.fixture(autouse=True)
def fake_httpx(monkeypatch):
    FakeAsyncClient.status = 200
    FakeAsyncClient.last_kwargs = None
    FakeAsyncClient.last_url = None
    FakeAsyncClient.raise_on_get = None
    monkeypatch.setattr(server.httpx, "AsyncClient", FakeAsyncClient)
    yield FakeAsyncClient


@pytest.mark.asyncio
async def test_proxy_test_ok_with_latency(fake_httpx):
    r = await server.api_proxy_test(server.ProxyTestRequest(proxy="http://p:7890"))
    assert r["ok"] is True
    assert isinstance(r["latency_ms"], int) and r["latency_ms"] >= 0
    assert "延迟" in r["message"]
    # 代理地址要真的传给 httpx
    assert fake_httpx.last_kwargs["proxy"] == "http://p:7890"
    assert fake_httpx.last_url == "http://www.baidu.com"


@pytest.mark.asyncio
async def test_proxy_test_empty_proxy_means_direct(fake_httpx):
    r = await server.api_proxy_test(server.ProxyTestRequest(proxy=""))
    assert r["ok"] is True
    assert fake_httpx.last_kwargs["proxy"] is None, "空代理必须走直连"
    assert fake_httpx.last_kwargs.get("proxies") is None, \
        "httpx 0.28 用 proxy=，proxies= 已移除"


@pytest.mark.asyncio
async def test_proxy_test_timeout_is_result_not_error(fake_httpx):
    """超时是测试结果：200 + ok=false + 中文原因，不是 4xx/5xx"""
    fake_httpx.raise_on_get = httpx.TimeoutException("timed out")
    r = await server.api_proxy_test(server.ProxyTestRequest(proxy="http://p:7890"))
    assert r["ok"] is False
    assert "超时" in r["message"]
    assert "端口" in r["message"] or "代理" in r["message"]


@pytest.mark.asyncio
async def test_proxy_test_connection_error_is_chinese(fake_httpx):
    """连不上要按代理/直连分开说人话，不能甩 httpx 英文原文"""
    fake_httpx.raise_on_get = httpx.ConnectError("refused")
    r = await server.api_proxy_test(server.ProxyTestRequest(proxy="http://p:1"))
    assert r["ok"] is False
    assert r["message"].startswith("连不上代理"), r["message"]
    assert "代理软件" in r["message"]
    # 直连场景则是网络不通
    r = await server.api_proxy_test(server.ProxyTestRequest(proxy=""))
    assert r["message"].startswith("网络不通"), r["message"]


@pytest.mark.asyncio
async def test_proxy_test_http_error_status_not_ok(fake_httpx):
    fake_httpx.status = 502
    r = await server.api_proxy_test(server.ProxyTestRequest())
    assert r["ok"] is False
    assert "502" in r["message"]


# ---------------- settings 联动 ----------------


@pytest.fixture
def fake_cfg(monkeypatch):
    cfg = {"proxy": {"mode": "manual", "global": "http://127.0.0.1:7890"}}
    saved = []
    monkeypatch.setattr(server, "load_config", lambda: cfg)
    monkeypatch.setattr(server, "save_config", lambda c: saved.append(c))
    return cfg, saved


@pytest.mark.asyncio
async def test_settings_get_returns_system_proxy(monkeypatch, fake_cfg):
    """跟随系统态要能回显系统代理值，否则那一态是黑盒"""
    monkeypatch.setattr(proxy_mod, "get_system_proxy",
                        lambda: "http://sys:7890")
    r = await server.api_settings_get()
    assert r["proxy_system"] == "http://sys:7890"
    assert r["settings"]["proxy"]["mode"] == "manual"

    monkeypatch.setattr(proxy_mod, "get_system_proxy", lambda: None)
    r = await server.api_settings_get()
    assert r["proxy_system"] == ""


@pytest.mark.asyncio
async def test_settings_update_stores_mode(fake_cfg):
    cfg, saved = fake_cfg
    req = server.SettingsUpdateRequest(proxy={
        "mode": "off", "global": "", "youtube": "", "douyin": "",
        "bilibili": "", "xiaohongshu": "",
    })
    await server.api_settings_update(req)
    assert saved and saved[0]["proxy"]["mode"] == "off"
    # mode 落库后解析立即是 off，不用等重启
    assert proxy_mod.resolve_mode(saved[0]["proxy"]) == "off"


# ---------------- 界面 ----------------

HTML = (STATIC / "index.html").read_text(encoding="utf-8")
JS = (STATIC / "js" / "settings.js").read_text(encoding="utf-8")


def test_three_state_radios_in_html():
    for mode in ("off", "system", "manual"):
        assert f'id="setting-proxy-mode-{mode}"' in HTML, f"缺 {mode} 单选"
    assert HTML.count('name="setting-proxy-mode"') == 3, "三态必须同组"
    # 无配置默认 = 跟随系统，与服务端 resolve_mode 一致
    assert 'id="setting-proxy-mode-system" value="system" checked' in HTML
    assert 'id="setting-proxy-enabled"' not in HTML, "旧 checkbox 没删干净"


def test_proxy_test_ui_in_html():
    assert 'id="proxy-test-btn"' in HTML, "缺测试连接按钮"
    assert 'id="proxy-system-hint"' in HTML, "缺系统代理回显区"
    assert "三态开关" in HTML, "解答页没同步三态说明"


def test_settings_js_reads_and_saves_mode():
    assert "currentProxyMode" in JS, "没读三态"
    assert "mode: currentProxyMode()" in JS, "保存没带 mode"
    # 保存的 proxy 块里不许再写 enabled（双字段迟早互相矛盾）
    m = re.search(r"data\.proxy\s*=\s*\{(.*?)\};", JS, re.S)
    assert m, "找不到 data.proxy 赋值"
    assert "enabled" not in m.group(1), "保存还在写旧 enabled 字段"
    assert "proxy_system" in JS, "没回读系统代理回显值"


def test_settings_js_wires_test_and_states():
    assert "/api/proxy/test" in JS, "测试按钮没调端点"
    assert "updateProxySystemHint" in JS, "跟随系统态没回显"
    # 非手动态必须禁用地址输入框
    assert "(mode !== 'manual')" in JS, "地址框禁用没按三态走"
