"""服务端 /api/cookies/* 端点单元测试

覆盖 3 个端点：
  GET  /api/cookies/open-login        — 打开登录页
  POST /api/cookies/load-from-browser — 从浏览器读取 Cookie
  POST /api/cookies/save              — 保存 Cookie 到文件

测试策略：直接 import route 函数，monkeypatch webbrowser / browser_cookie 模块，
不启动真实服务，不依赖系统浏览器。
"""
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import (
    api_cookies_open_login,
    api_cookies_load_from_browser,
    api_cookies_save,
    CookieLoadFromBrowserRequest,
    CookieSaveRequest,
)


# ============================ open-login ============================

@pytest.mark.asyncio
async def test_open_login_valid_douyin(monkeypatch):
    """正常平台返回 URL，webbrowser 返回值参与 opened 字段。"""
    monkeypatch.setattr("webbrowser.open", lambda url, new=0: True)
    result = await api_cookies_open_login(platform="douyin")
    assert result["ok"] is True
    assert result["url"] == "https://www.douyin.com/"
    assert result["platform"] == "douyin"
    assert result["opened"] is True


@pytest.mark.asyncio
async def test_open_login_valid_bilibili(monkeypatch):
    monkeypatch.setattr("webbrowser.open", lambda url, new=0: True)
    result = await api_cookies_open_login(platform="bilibili")
    assert result["ok"] is True
    assert result["url"] == "https://passport.bilibili.com/login"


@pytest.mark.asyncio
async def test_open_login_invalid_platform():
    with pytest.raises(HTTPException) as exc:
        await api_cookies_open_login(platform="unsupported")
    assert exc.value.status_code == 400
    assert "不支持的平台" in exc.value.detail


@pytest.mark.asyncio
async def test_open_login_webbrowser_exception(monkeypatch):
    """webbrowser.open 抛异常时仍返回 URL，前端可手动复制。"""
    monkeypatch.setattr(
        "webbrowser.open",
        lambda url, new=0: (_ for _ in ()).throw(RuntimeError("无浏览器")),
    )
    result = await api_cookies_open_login(platform="douyin")
    assert result["ok"] is False
    assert result["url"] == "https://www.douyin.com/"
    assert "error" in result


# ============================ load-from-browser ============================

def _make_fake_bc(douyin_cookie="", bilibili_cookie=""):
    """构造伪造的 downloadkit.browser_cookie 模块。"""
    class FakeMod:
        @staticmethod
        def get_douyin_cookie_string(browser="edge"):
            return douyin_cookie

        @staticmethod
        def get_bilibili_cookie_string(browser="edge"):
            return bilibili_cookie
    return FakeMod()


@pytest.mark.asyncio
async def test_load_from_browser_douyin_success(monkeypatch):
    fake_mod = _make_fake_bc(douyin_cookie="session_id=abc123; user_id=456")
    monkeypatch.setitem(sys.modules, "downloadkit.browser_cookie", fake_mod)
    req = CookieLoadFromBrowserRequest(platform="douyin", browser="edge")
    result = await api_cookies_load_from_browser(req)
    assert result["ok"] is True
    assert result["platform"] == "douyin"
    assert result["count"] == 2
    names = {c["name"] for c in result["cookies"]}
    assert names == {"session_id", "user_id"}


@pytest.mark.asyncio
async def test_load_from_browser_bilibili_success(monkeypatch):
    fake_mod = _make_fake_bc(bilibili_cookie="bili_jct=xyz")
    monkeypatch.setitem(sys.modules, "downloadkit.browser_cookie", fake_mod)
    req = CookieLoadFromBrowserRequest(platform="bilibili", browser="chrome")
    result = await api_cookies_load_from_browser(req)
    assert result["ok"] is True
    assert result["browser"] == "chrome"
    assert result["count"] == 1


@pytest.mark.asyncio
async def test_load_from_browser_empty_cookie(monkeypatch):
    """浏览器里没有 Cookie 时返回 ok=False，不抛异常。"""
    fake_mod = _make_fake_bc()
    monkeypatch.setitem(sys.modules, "downloadkit.browser_cookie", fake_mod)
    req = CookieLoadFromBrowserRequest(platform="douyin", browser="edge")
    result = await api_cookies_load_from_browser(req)
    assert result["ok"] is False
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_load_from_browser_invalid_platform():
    with pytest.raises(HTTPException) as exc:
        req = CookieLoadFromBrowserRequest(platform="twitter", browser="edge")
        await api_cookies_load_from_browser(req)
    assert exc.value.status_code == 400
    assert "不支持的平台" in exc.value.detail


@pytest.mark.asyncio
async def test_load_from_browser_xhs_youtube_not_supported(monkeypatch):
    """xhs / youtube 在 load-from-browser 中返回不支持提示。"""
    fake_mod = _make_fake_bc()
    monkeypatch.setitem(sys.modules, "downloadkit.browser_cookie", fake_mod)
    for platform in ("xhs", "youtube"):
        req = CookieLoadFromBrowserRequest(platform=platform, browser="edge")
        result = await api_cookies_load_from_browser(req)
        assert result["ok"] is False
        assert "暂不支持" in result.get("error", "")


@pytest.mark.asyncio
async def test_load_from_browser_read_exception_returns_error(monkeypatch):
    """读取特定浏览器失败时返回 error 字段，不抛异常。"""
    class FailingMod:
        @staticmethod
        def get_douyin_cookie_string(browser="edge"):
            if browser == "bad":
                raise RuntimeError("锁定文件")
            return "good=cookie"

        @staticmethod
        def get_bilibili_cookie_string(browser="edge"):
            return ""
    monkeypatch.setitem(sys.modules, "downloadkit.browser_cookie", FailingMod())
    req = CookieLoadFromBrowserRequest(platform="douyin", browser="bad")
    result = await api_cookies_load_from_browser(req)
    assert result["ok"] is False
    assert "error" in result
    assert "锁定文件" in result["error"]


# ============================ save ============================

@pytest.mark.asyncio
async def test_save_empty_cookie_raises_400():
    with pytest.raises(HTTPException) as exc:
        await api_cookies_save(CookieSaveRequest(platform="douyin", cookie_string=""))
    assert exc.value.status_code == 400
    assert "不能为空" in exc.value.detail

    with pytest.raises(HTTPException) as exc:
        await api_cookies_save(CookieSaveRequest(platform="douyin", cookie_string="   "))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_save_invalid_platform():
    with pytest.raises(HTTPException) as exc:
        await api_cookies_save(CookieSaveRequest(platform="twitter", cookie_string="a=b"))
    assert exc.value.status_code == 400
    assert "不支持的平台" in exc.value.detail


@pytest.mark.asyncio
async def test_save_custom_path_writes_file(tmp_path, monkeypatch):
    """保存成功：写入指定文件，不更新 config。"""
    cookie_file = tmp_path / "cookies" / "douyin.txt"
    req = CookieSaveRequest(
        platform="douyin",
        cookie_string="session=abc; uid=123",
        save_to_config=False,
        custom_path=str(cookie_file),
    )
    result = await api_cookies_save(req)
    assert result["ok"] is True
    assert result["path"] == str(cookie_file)
    saved = cookie_file.read_text(encoding="utf-8")
    assert saved.strip() == "session=abc; uid=123"


@pytest.mark.asyncio
async def test_save_default_path_writes_file(tmp_path, monkeypatch):
    """不传 custom_path 时保存到 ~/.downloadkit/cookies/<platform>.txt。"""
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    req = CookieSaveRequest(
        platform="bilibili",
        cookie_string="bili=jct",
        save_to_config=False,
    )
    result = await api_cookies_save(req)
    assert result["ok"] is True
    expected = fake_home / ".downloadkit" / "cookies" / "bilibili.txt"
    assert expected.read_text(encoding="utf-8").strip() == "bili=jct"


@pytest.mark.asyncio
async def test_save_updates_config(tmp_path, monkeypatch):
    """save_to_config=True 时同步写入 config.toml。"""
    fake_home = tmp_path / "fakehome"
    fake_home.mkdir()
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    req = CookieSaveRequest(
        platform="douyin",
        cookie_string="s=v",
        save_to_config=True,
        custom_path=str(tmp_path / "cookies" / "douyin.txt"),
    )
    result = await api_cookies_save(req)
    assert result["ok"] is True
    # config.toml 应被更新，包含 douyin_path
    cfg_path = fake_home / ".downloadkit" / "config.toml"
    assert cfg_path.exists()
    cfg_text = cfg_path.read_text(encoding="utf-8")
    assert "douyin_path" in cfg_text
    # TOML 手动写入时会转义反斜杠，用 contains 兼容
    assert "cookies" in cfg_text and "douyin.txt" in cfg_text


@pytest.mark.asyncio
async def test_save_file_write_failure(tmp_path, monkeypatch):
    """写入路径抛异常时返回 500（通过 monkeypatch Path.mkdir 模拟）。"""
    import server
    orig_mkdir = Path.mkdir

    def failing_mkdir(self, *args, **kwargs):
        if "impossible" in str(self):
            raise OSError("No such file or directory")
        return orig_mkdir(self, *args, **kwargs)

    monkeypatch.setattr("pathlib.Path.mkdir", failing_mkdir)
    req = CookieSaveRequest(
        platform="douyin",
        cookie_string="x=y",
        custom_path=str(tmp_path / "impossible" / "deep" / "douyin.txt"),
        save_to_config=False,
    )
    with pytest.raises(HTTPException) as exc:
        await api_cookies_save(req)
    assert exc.value.status_code == 500
    assert "写入 Cookie 文件失败" in exc.value.detail
