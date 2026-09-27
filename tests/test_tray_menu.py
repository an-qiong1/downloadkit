"""P3-3 托盘菜单快捷项（打开下载目录 / 检查订阅更新）

托盘菜单点击没法自动化 —— pystray 没有触发菜单项的公开 API，
test-exe-tray.py 里也写明了「UI 无法自动化点菜单」。所以分三层钉：

  1. pystray 实际构造一遍菜单 —— Menu.SEPARATOR / MenuItem 的用法
     在本机 pystray 版本上合法（用错就是打包后「托盘图标创建失败」，
     exe 验收的日志断言会拦住）；
  2. 两个动作是 run.py 顶层函数，把网络 / 文件操作 mock 掉跑真实
     调用链 —— 断言打开的路径、请求的 URL / 方法 / 超时、气泡收到的
     文案；
  3. 源文本断言菜单项与回调接线（网络动作必须线程化，托盘 UI 线程
     里等网络 = 卡整个右键菜单）。

红线：测试不发任何真实网络请求 —— 成功分支 mock urlopen，
失败分支让 urlopen 抛连接拒绝。
"""

import importlib.util
import json
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

RUN_PY = (ROOT / "run.py").read_text(encoding="utf-8")


def _load_run():
    """从文件加载 run 模块。顶层只有常量与函数定义，不启动任何服务。"""
    spec = importlib.util.spec_from_file_location("dk_run", ROOT / "run.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def run_mod():
    return _load_run()


class FakeIcon:
    def __init__(self):
        self.notifies = []

    def notify(self, message, title=None):
        self.notifies.append((message, title))


class _FakeResp:
    def __init__(self, payload: bytes):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._payload


# ---------------- 打开下载目录 ----------------


def test_open_download_dir(run_mod, monkeypatch):
    captured = {}

    def fake_startfile(path):
        captured["path"] = path

    logs = []
    monkeypatch.setattr(run_mod.os, "startfile", fake_startfile, raising=False)
    monkeypatch.setattr(run_mod, "log", logs.append)

    run_mod.open_download_dir()

    assert captured.get("path"), "os.startfile 没被调用"
    p = captured["path"]
    assert not p.startswith("~"), "路径没做 expanduser"
    assert Path(p).is_dir(), "打开的目录不存在（makedirs 没兜底）"
    assert any("打开下载目录" in m for m in logs), "没记日志"


# ---------------- 检查订阅更新 ----------------


def test_check_subscription_success(run_mod, monkeypatch):
    """成功分支：POST 正确的端点、气泡收到后端组织好的 message"""
    icon = FakeIcon()
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["data"] = req.data
        captured["timeout"] = timeout
        return _FakeResp(json.dumps(
            {"message": "发现 2 个新作品，入队 2 个"}
        ).encode("utf-8"))

    logs = []
    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(run_mod, "log", logs.append)

    run_mod.check_subscription_update(icon, 8767)

    assert captured["url"] == \
        "http://127.0.0.1:8767/api/subscriptions/check-all"
    assert captured["method"] == "POST"
    assert captured["data"] == b"{}", "body 该是空对象（走各字段默认值）"
    assert captured["timeout"] == 180, "一轮串行检查 + 下载，180 秒超时"
    assert icon.notifies == [("发现 2 个新作品，入队 2 个", "DownloadKit")]
    assert any("订阅检查完成" in m for m in logs)


def test_check_subscription_failure_notifies(run_mod, monkeypatch):
    """失败必须吞在函数里并气泡通知：托盘线程冒异常 = 点了没反应还没日志"""
    icon = FakeIcon()

    def boom(req, timeout=None):
        raise OSError("connection refused")

    logs = []
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(run_mod, "log", logs.append)

    run_mod.check_subscription_update(icon, 1)

    assert len(icon.notifies) == 1, "失败没有气泡，用户不知道点了没反应"
    msg, title = icon.notifies[0]
    assert msg.startswith("检查失败"), msg
    assert title == "DownloadKit"
    assert any("订阅检查失败" in m for m in logs)


def test_check_subscription_fallback_message(run_mod, monkeypatch):
    """响应缺 message 时气泡不能是空的 —— 兜底文案必须有"""
    icon = FakeIcon()
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda req, timeout=None: _FakeResp(b"{}"))
    monkeypatch.setattr(run_mod, "log", lambda m: None)

    run_mod.check_subscription_update(icon, 8767)

    assert icon.notifies and icon.notifies[0][0] == "检查完成"


# ---------------- 菜单构造与接线 ----------------


def test_pystray_menu_constructs():
    """实际构造一遍菜单：SEPARATOR / MenuItem 用法错了这里就炸"""
    pystray = pytest.importorskip("pystray")

    def noop(icon=None, item=None):
        pass

    menu = pystray.Menu(
        pystray.MenuItem("显示主窗口", noop, default=True),
        pystray.MenuItem("打开下载目录", noop),
        pystray.MenuItem("检查订阅更新", noop),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", noop),
    )
    assert menu is not None


def test_menu_items_present_in_source():
    assert 'pystray.MenuItem("打开下载目录", _open_dir)' in RUN_PY, \
        "菜单缺「打开下载目录」"
    assert 'pystray.MenuItem("检查订阅更新", _check_subs)' in RUN_PY, \
        "菜单缺「检查订阅更新」"
    assert "pystray.Menu.SEPARATOR" in RUN_PY, \
        "快捷项与「退出」之间缺分隔，容易误触退出"


def test_check_subscriber_action_is_threaded():
    """检查动作必须起线程：托盘回调里等网络会卡住整个右键菜单"""
    body = RUN_PY.split("def _check_subs")[1].split("def _quit")[0]
    assert "target=check_subscription_update" in body, \
        "_check_subs 没把动作丢给后台线程"
    assert "daemon=True" in body
    assert "name=\"tray-check\"" in body
