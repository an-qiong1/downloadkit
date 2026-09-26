# -*- coding: utf-8 -*-
"""开机自启动 —— 写 HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run。

为什么是 HKCU 而不是 HKLM：
    写 HKLM 需要管理员权限，装给小白的桌面程序一弹 UAC 就会把人吓退；
    HKCU 只影响当前用户，语义也正好是「我这台电脑登录后自动打开」。

为什么 winreg 放在函数里 import：
    winreg 只在 Windows 存在。这个模块会被 server.py 无条件 import，
    如果顶层 import winreg，将来跑在 Linux/Docker 里会直接 ImportError。
    那时开机启动本来就 unavailable，没理由让整个服务起不来。

测试怎么做：
    set_enabled()/get_status() 接受 run_key/value_name 参数，默认才是真键。
    测试传一个 Software\\DownloadKit_test_* 临时键，跑完删掉，
    不碰用户真实的 Run 键。
"""
from __future__ import annotations

import sys
from typing import Optional

# 真键。测试请用自己的临时键，别动这两个默认值。
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "DownloadKit"

# 走 HKCU：当前用户，免管理员
_HIVE = "HKEY_CURRENT_USER"

_REASON_NOT_FROZEN = "只有打包成 exe 后才能设置开机启动（源码运行时没有可自启的程序）"
_REASON_NOT_WINDOWS = "开机启动仅支持 Windows"


def is_frozen() -> bool:
    """是否运行在 PyInstaller 打包产物里。"""
    return bool(getattr(sys, "frozen", False))


def is_windows() -> bool:
    return sys.platform.startswith("win")


def exe_path() -> Optional[str]:
    """开机启动应指向的程序绝对路径；不可用时返回 None。"""
    if not is_windows() or not is_frozen():
        return None
    return sys.executable


def _command() -> Optional[str]:
    """注册表值的完整命令行。

    路径必须带引号：装在 `C:\\Program Files\\DownloadKit\\` 这种带空格的
    目录下，不加引号会被 Windows 拆成两个程序。
    """
    path = exe_path()
    if not path:
        return None
    return '"%s"' % path


def _winreg():
    """延迟 import，理由见模块 docstring。"""
    import winreg
    return winreg


def _hive_handle():
    wr = _winreg()
    return getattr(wr, _HIVE)


def get_status(run_key: str = RUN_KEY,
               value_name: str = VALUE_NAME) -> dict:
    """读当前自启状态。

    Returns:
        available  当前环境能否设置（False 时 enabled 恒为 False）
        enabled    Run 键里是否已有本程序
        path       会自启的程序路径（不可用时为 None）
        reason     不可用的原因，直接给 UI 显示
    """
    path = exe_path()
    cmd = _command()
    if cmd is None:
        reason = _REASON_NOT_WINDOWS if not is_windows() else _REASON_NOT_FROZEN
        return {"available": False, "enabled": False, "path": path,
                "reason": reason}

    enabled = False
    try:
        wr = _winreg()
        with wr.OpenKey(_hive_handle(), run_key) as key:
            stored, _ = wr.QueryValueEx(key, value_name)
            # 只要存在就算启用：路径可能因为移动 exe 而不同，那属于
            # 「已设置但指向旧位置」，UI 上仍应显示为已开启，
            # 用户重新保存一次就会覆盖成新路径。
            enabled = isinstance(stored, str) and bool(stored.strip())
    except (FileNotFoundError, OSError):
        # 键或值不存在 = 尚未设置，这是最常见的初始状态
        enabled = False

    return {"available": True, "enabled": enabled, "path": path, "reason": ""}


def set_enabled(enabled: bool,
                run_key: str = RUN_KEY,
                value_name: str = VALUE_NAME) -> dict:
    """写入或删除 Run 键，返回写入后的完整状态。

    幂等：重复 enable 不会报错，重复 disable（值本就不存在）也静默成功。
    """
    cmd = _command()
    if cmd is None:
        status = get_status(run_key, value_name)
        status["ok"] = False
        status["message"] = status["reason"]
        return status

    wr = _winreg()
    try:
        with wr.CreateKeyEx(_hive_handle(), run_key, 0, wr.KEY_SET_VALUE) as key:
            if enabled:
                wr.SetValueEx(key, value_name, 0, wr.REG_SZ, cmd)
            else:
                try:
                    wr.DeleteValue(key, value_name)
                except FileNotFoundError:
                    pass  # 本来就没设过，关掉的目标已达成
    except OSError as e:
        status = get_status(run_key, value_name)
        status["ok"] = False
        status["message"] = "写入注册表失败：%s" % e
        return status

    status = get_status(run_key, value_name)
    status["ok"] = True
    status["message"] = ("已设置开机自动启动" if enabled
                         else "已取消开机自动启动")
    return status
