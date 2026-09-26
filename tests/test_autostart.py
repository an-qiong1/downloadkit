# -*- coding: utf-8 -*-
"""开机自启动（注册表）测试。

红线：绝不碰用户真实的 HKCU\\...\\Run\\DownloadKit ——
所有写操作都打在 Software\\DownloadKit_test_* 临时键上，跑完必删。
测试里用 monkeypatch 伪造 sys.frozen / sys.executable，
这样「源码运行」和「exe 运行」两种状态都能测到，而不用真打一个包。
"""
import sys

import pytest

from downloadkit import autostart

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("win"),
    reason="注册表仅 Windows 可用",
)

# 测试专用临时键，与真键 RUN_KEY 明显不同，且带前缀方便辨认与清理
TEMP_KEY = r"Software\DownloadKit_test_autostart"


def _purge(key_path: str):
    """删掉整棵测试键（DeleteKey 只能删无子键的键，测试用例不建子键）。"""
    import winreg
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
    except FileNotFoundError:
        pass


@pytest.fixture(autouse=True)
def clean_key():
    """每个用例前后都清理，避免上一个用例的残留影响下一个。"""
    _purge(TEMP_KEY)
    yield
    _purge(TEMP_KEY)


@pytest.fixture
def as_exe(monkeypatch):
    """把当前进程伪装成一个安装在带空格路径下的 exe。"""
    exe = r"C:\Program Files\DownloadKit\downloadkit.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", exe)
    return exe


# ---------- 可用性判定 ----------

def test_source_mode_is_unavailable():
    """源码运行时不该有可自启的程序，也绝不能去写注册表。"""
    st = autostart.get_status(TEMP_KEY, "T")
    assert st["available"] is False
    assert st["enabled"] is False
    assert st["path"] is None
    assert "exe" in st["reason"]


def test_source_mode_set_enabled_refuses():
    """源码模式调 set_enabled 要返回 ok=False 并说明原因，不能抛异常。"""
    res = autostart.set_enabled(True, TEMP_KEY, "T")
    assert res["ok"] is False
    assert res["available"] is False
    assert res["message"]
    # 关键：没写成注册表
    st = autostart.get_status(TEMP_KEY, "T")
    assert st["enabled"] is False


def test_command_quotes_path_with_space(as_exe):
    """路径含空格必须加引号，否则 Windows 会把它拆成两个程序。"""
    assert autostart.exe_path() == as_exe
    assert autostart._command() == '"C:\\Program Files\\DownloadKit\\downloadkit.exe"'


# ---------- 读写注册表 ----------

def test_default_state_is_off(as_exe):
    st = autostart.get_status(TEMP_KEY, "T")
    assert st == {"available": True, "enabled": False,
                  "path": as_exe, "reason": ""}


def test_enable_then_disable_roundtrip(as_exe):
    on = autostart.set_enabled(True, TEMP_KEY, "T")
    assert on["ok"] is True
    assert on["enabled"] is True
    assert on["available"] is True
    assert "已设置" in on["message"]

    # 状态确实落到注册表里了
    st = autostart.get_status(TEMP_KEY, "T")
    assert st["enabled"] is True

    off = autostart.set_enabled(False, TEMP_KEY, "T")
    assert off["ok"] is True
    assert off["enabled"] is False
    assert "已取消" in off["message"]
    assert autostart.get_status(TEMP_KEY, "T")["enabled"] is False


def test_enable_is_idempotent(as_exe):
    """重复开启不能报错，状态保持开启。"""
    for _ in range(3):
        res = autostart.set_enabled(True, TEMP_KEY, "T")
        assert res["ok"] is True
        assert res["enabled"] is True
    assert autostart.get_status(TEMP_KEY, "T")["enabled"] is True


def test_disable_when_never_enabled_is_safe(as_exe):
    """从没开过就关掉，要静默成功而不是抛 FileNotFoundError。"""
    res = autostart.set_enabled(False, TEMP_KEY, "T")
    assert res["ok"] is True
    assert res["enabled"] is False


def test_value_stores_quoted_command(as_exe):
    """写进去的必须是带引号的完整命令行。"""
    import winreg
    autostart.set_enabled(True, TEMP_KEY, "T")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEMP_KEY) as k:
        stored, kind = winreg.QueryValueEx(k, "T")
    assert kind == winreg.REG_SZ
    assert stored.startswith('"') and stored.endswith('"')
    assert stored.strip('"') == as_exe


def test_empty_value_treated_as_disabled(as_exe):
    """值存在但为空串 = 没有可启动的程序，按未开启处理。"""
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, TEMP_KEY,
                            0, winreg.KEY_SET_VALUE) as k:
        winreg.SetValueEx(k, "T", 0, winreg.REG_SZ, "   ")
    st = autostart.get_status(TEMP_KEY, "T")
    assert st["available"] is True
    assert st["enabled"] is False


def test_value_takes_effect_after_path_moves(as_exe, monkeypatch):
    """exe 被移动后，注册表里是旧路径 —— 仍显示为已开启，
    再保存一次即可覆盖成新路径。"""
    autostart.set_enabled(True, TEMP_KEY, "T")
    moved = r"D:\New Location\downloadkit.exe"
    monkeypatch.setattr(sys, "executable", moved)

    st = autostart.get_status(TEMP_KEY, "T")
    assert st["enabled"] is True
    assert st["path"] == moved  # path 是「下次会启动的」

    # 重新保存后，注册表指向新路径
    autostart.set_enabled(True, TEMP_KEY, "T")
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TEMP_KEY) as k:
        stored, _ = winreg.QueryValueEx(k, "T")
    assert stored == '"D:\\New Location\\downloadkit.exe"'
