"""订阅「只取资料」链路的回归测试

2026-09-27 用户实测：预览正常（共抓到 17 个作品），点订阅必报

    添加订阅失败: 主页没抓到任何作品（作品区选择器可能失效）。
    页面 /video/ 链接共 25 条

根因：add_subscription 只要昵称头像，调 fetch_creator(max_scrolls=0)
—— range(0) 循环一次不跑，links 必空；而 fetch_creator 里「作品区
空就抛」的防空基线保护是无条件的，于是**每一个新订阅都被自己的
保护挡死**。预览 max_scrolls=3 循环会跑，所以一好一坏。

这条链以前没有测试：tests 里 add_subscription 用的替身浏览器
fetch_creator 直接返回数据，绕过了真实实现，全绿也照样线上炸
（同一入口第二次出事 —— 上次是短链解析，见 test_resolve_sec_uid.py
开头那段教训）。

钉三层：
  1. 真 fetch_creator(max_scrolls=0) + 空作品区 → 不抛，资料照取
  2. max_scrolls>0 抓空 → 仍然抛（防空基线保护不能顺手丢掉：
     空基线会把该创作者全部存量作品当成新作品下载）
  3. add_subscription 真链路（真 fetch_creator + 假页面）→ 成功入库
外加前端：预览消息必须是纯文本 —— showMsg 走 textContent（防注入），
拼 <b>/<span> 会字面显示在消息框里。
"""

from pathlib import Path

import pytest

import downloadkit.subscription as store
import downloadkit.subscription_service as svc
from downloadkit.douyin_browser import DouyinBrowser
from downloadkit.subscription_service import add_subscription

ROOT = Path(__file__).resolve().parent.parent

SEC_UID = "MS4wLjABAAAA_test"


# ------------------------------------------------------------------
# 临时库：别污染用户真实的 ~/.downloadkit/subscriptions.db
# ------------------------------------------------------------------

@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
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


class FakePage:
    """够 fetch_creator 用的最小页面：作品区默认空（正是事故场景）"""

    def __init__(self, grid=None, footer=None):
        self.grid = list(grid or [])
        self.footer = list(footer or [])
        self.closed = False

    async def goto(self, *a, **k):
        pass

    async def wait_for_timeout(self, *a, **k):
        pass

    async def close(self):
        self.closed = True

    async def evaluate(self, expr, *a, **k):
        if "nickname" in str(expr):
            return {"nickname": "测试博主", "avatar": ""}
        return None

    async def eval_on_selector_all(self, selector, expr):
        if "els.length" in str(expr):
            return len(self.grid) + len(self.footer)
        return list(self.grid)


def _make_browser(page) -> DouyinBrowser:
    b = DouyinBrowser()

    async def fake_start():
        return None

    async def fake_get_page(reuse=True):
        return page

    b.start = fake_start
    b._get_page = fake_get_page
    return b


# ------------------------------------------------------------------
# fetch_creator 层
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fetch_creator_zero_scrolls_skips_empty_guard():
    """max_scrolls=0 = 只取资料不抓列表，空作品区是预期，不能抛"""
    page = FakePage(grid=[], footer=[])  # 整页一条 /video/ 链接都没有也该过
    info = await _make_browser(page).fetch_creator(SEC_UID, max_scrolls=0)

    assert info.video_ids == [], "0 滚动本来就不该抓列表"
    assert info.nickname == "测试博主", "资料（昵称头像）必须照常提取"
    assert page.closed


@pytest.mark.asyncio
async def test_fetch_creator_guard_still_fires_when_scrolling():
    """max_scrolls>0 抓空必须抛 —— 防空基线的保护不能因为这次修丢掉"""
    page = FakePage(grid=[], footer=["https://www.douyin.com/video/1"])
    b = _make_browser(page)

    with pytest.raises(RuntimeError) as e:
        await b.fetch_creator(SEC_UID, max_scrolls=3)

    assert "没抓到任何作品" in str(e.value)
    assert "1" in str(e.value), "报错要带整页 /video/ 链接数，方便诊断"


# ------------------------------------------------------------------
# add_subscription 真链路（真 fetch_creator，不走替身）
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_add_subscription_fetch_profile_succeeds(monkeypatch):
    """订阅入口真实走通：resolve → 登录检查 → fetch_creator(0) → 入库

    事故时这一链必炸在 fetch_creator(0) 的空保护上。
    """
    page = FakePage(grid=[])          # 作品区空 = 用户实测的页面状态
    b = _make_browser(page)

    async def fake_resolve(url):
        return SEC_UID

    async def fake_login():
        return None

    monkeypatch.setattr(svc, "_resolve_sec_uid", fake_resolve)
    monkeypatch.setattr(svc, "_require_login", fake_login)
    monkeypatch.setattr(svc, "_browser", lambda: b)

    rec = await add_subscription("https://v.douyin.com/fake/")

    assert rec["sec_uid"] == SEC_UID
    assert rec["nickname"] == "测试博主", "订阅应拿到昵称"
    assert store.get_creator(SEC_UID) is not None, "没真正入库"


@pytest.mark.asyncio
async def test_add_subscription_existing_returns_early(monkeypatch):
    """重复订阅走查重早退，不该再开一次主页（省一次限流额度）"""
    store.add_creator(SEC_UID, "老昵称", "", "")

    async def fake_resolve(url):
        return SEC_UID

    monkeypatch.setattr(svc, "_resolve_sec_uid", fake_resolve)

    async def boom(*a, **k):
        raise AssertionError("已订阅的创作者不该再抓主页")

    monkeypatch.setattr(svc, "_browser", boom)

    rec = await add_subscription("https://v.douyin.com/fake/")
    assert rec["nickname"] == "老昵称"


# ------------------------------------------------------------------
# 前端：预览消息纯文本
# ------------------------------------------------------------------

def test_preview_message_is_plain_text():
    """showMsg 用 textContent（防注入），HTML 标签会字面显示"""
    js = (ROOT / "downloadkit" / "static" / "js" / "subscriptions.js") \
        .read_text(encoding="utf-8")
    block = js.split("function previewCreator")[1].split("function ", 1)[0]

    assert "共抓到 <b>" not in block, "预览文案又拼回 HTML 了，会字面显示"
    assert "<span style=" not in block, "「已经订阅过了」不许用 HTML 拼"
    assert "textContent" in js.split("function showMsg")[1].split("function ", 1)[0], \
        "showMsg 必须保持 textContent，改 innerHTML 会开注入面"
