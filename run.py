"""One-click launcher for downloadkit desktop app.

Starts the FastAPI server in-process (no subprocess — works with PyInstaller)
and opens a native pywebview window pointing at it. No browser required.

PyInstaller-compatible: no console window in windowed mode, all uvicorn
sys.stdout / sys.stderr issues handled.
"""

import copy
import ctypes
import os
import socket
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime
from pathlib import Path

HOST = "127.0.0.1"
PORT = 8765
WINDOW_TITLE = "DownloadKit"
WINDOW_WIDTH = 1280
WINDOW_HEIGHT = 800
WEBVIEW2_DOWNLOAD_URL = (
    "https://developer.microsoft.com/en-us/microsoft-edge/webview2/"
)

# 启动必需的三方依赖（缺任何一个都不能跑）
REQUIRED_MODULES = ("uvicorn", "fastapi", "webview")

# 防止反复重启的环境变量标记
RELAUNCH_FLAG = "DOWNLOADKIT_VENV_RELAUNCHED"


# ---------- 虚拟环境自举 ----------

def missing_modules() -> list:
    """返回当前解释器里缺失的必需依赖名（空列表表示齐全）。"""
    import importlib.util

    missing = []
    for name in REQUIRED_MODULES:
        try:
            if importlib.util.find_spec(name) is None:
                missing.append(name)
        except (ImportError, ValueError):
            missing.append(name)
    return missing


def venv_python(interactive: bool) -> Path | None:
    """定位项目 .venv 里的解释器，找不到返回 None。"""
    root = Path(__file__).resolve().parent
    scripts = root / ".venv" / "Scripts"
    # 有控制台用 python.exe（保留报错输出），否则用 pythonw.exe（不弹黑窗）
    for name in ("python.exe", "pythonw.exe") if interactive else ("pythonw.exe", "python.exe"):
        exe = scripts / name
        if exe.is_file():
            return exe
    return None


def relaunch_in_venv() -> bool:
    """依赖不全时，自动改用 .venv 的解释器重新启动自己。

    为什么需要这段：
      Windows 双击 .py 文件走的是「全局 Python」（如
      C:\\Users\\<用户>\\AppData\\Local\\Programs\\Python\\Python3xx\\python.exe），
      而不是项目的 .venv。全局环境里没装 uvicorn/fastapi/pywebview，
      双击 run.py 必然报 ModuleNotFoundError。
      这里做一次自举，让用户双击 run.py 就能跑，不用记命令。

    Returns:
        True  = 已启动新进程，本进程应立即退出
        False = 无需/无法切换，继续正常启动
    """
    if getattr(sys, "frozen", False):
        return False  # 打包后 sys.executable 就是本体，无虚拟环境概念

    if os.environ.get(RELAUNCH_FLAG) == "1":
        return False  # 已经切换过一次，别死循环

    try:
        missing = missing_modules()
    except Exception:
        return False
    if not missing:
        return False  # 当前解释器就是对的

    # 有真实控制台就保留它，方便看报错
    interactive = False
    try:
        interactive = bool(sys.stdout) and sys.stdout.isatty()
    except Exception:
        interactive = False

    exe = venv_python(interactive)
    if exe is None:
        return False

    try:
        if exe.resolve() == Path(sys.executable).resolve():
            return False  # 已经是 .venv 的解释器了，说明 .venv 本身缺依赖
    except OSError:
        pass

    env = os.environ.copy()
    env[RELAUNCH_FLAG] = "1"
    flags = 0
    if not interactive:
        # 双击场景：脱离当前控制台，父窗口关闭不影响子进程
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
            subprocess, "DETACHED_PROCESS", 0
        )

    log(f"依赖缺失 {missing}，改用虚拟环境重启: {exe}")
    try:
        subprocess.Popen(
            [str(exe), str(Path(__file__).resolve())],
            env=env,
            cwd=str(Path(__file__).resolve().parent),
            creationflags=flags,
        )
    except Exception:
        log(f"虚拟环境重启失败:\n{traceback.format_exc()}")
        return False
    return True


def report_missing_deps(missing: list) -> None:
    """依赖缺失时给出可照着做的中文提示，而不是裸露的 ModuleNotFoundError。"""
    root = Path(__file__).resolve().parent
    venv = root / ".venv"
    if not venv.is_dir():
        msg = (
            f"缺少运行依赖：{', '.join(missing)}\n\n"
            "并且没有找到项目的虚拟环境 .venv。\n\n"
            "请在项目文件夹里按住 Shift 右键 →「在此处打开 PowerShell 窗口」，"
            "然后依次执行：\n\n"
            "  python -m venv .venv\n"
            "  .venv\\Scripts\\pip install -e \".[media,dev,douyin,desktop]\"\n"
            "  .venv\\Scripts\\python -m playwright install chromium\n"
        )
    else:
        msg = (
            f"虚拟环境缺少依赖：{', '.join(missing)}\n\n"
            "请在项目文件夹里按住 Shift 右键 →「在此处打开 PowerShell 窗口」，"
            "然后执行：\n\n"
            "  .venv\\Scripts\\pip install -e \".[media,dev,douyin,desktop]\"\n"
            "  .venv\\Scripts\\python -m playwright install chromium\n"
        )
    show_error_dialog("DownloadKit - 缺少依赖", msg)


# ---------- file logging (windowed mode has no console) ----------

def _log_path() -> Path:
    """Log file location: next to the EXE (or in CWD for dev runs)."""
    if getattr(sys, "frozen", False):
        # PyInstaller onefile: sys.executable points to the EXE
        return Path(sys.executable).parent / "downloadkit.log"
    return Path.cwd() / "downloadkit.log"


_LOG_FILE = None  # opened lazily


def log(msg: str) -> None:
    """Append a timestamped line to the log file. Best-effort, never raises."""
    global _LOG_FILE
    try:
        if _LOG_FILE is None:
            _LOG_FILE = open(_log_path(), "a", encoding="utf-8")
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        _LOG_FILE.write(f"[{ts}] {msg}\n")
        _LOG_FILE.flush()
    except Exception:
        pass  # logging must never crash the app


# ---------- helpers ----------

def check_port(port: int) -> bool:
    """Return True if port is already listening."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(1)
    result = sock.connect_ex((HOST, port))
    sock.close()
    return result == 0


def find_available_port(start_port: int = 8765, max_port: int = 8800) -> int:
    for port in range(start_port, max_port + 1):
        if not check_port(port):
            return port
    raise RuntimeError(f"No available port in {start_port}-{max_port}")


def is_webview2_installed() -> bool:
    """Check if Microsoft Edge WebView2 Runtime is installed on this machine.

    WebView2 is the Chromium-based runtime that pywebview's `edgechromium`
    backend uses to render the desktop window. It is pre-installed on
    Windows 10 1809+ and Windows 11.
    """
    candidates = [
        Path(r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application"),
        Path(r"C:\Program Files\Microsoft\EdgeWebView\Application"),
    ]
    for p in candidates:
        if p.exists() and any(p.iterdir()):
            log(f"WebView2 check: found at {p}")
            return True
    # Fallback: registry check
    try:
        import winreg
        reg_paths = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        ]
        for hkey, sub in reg_paths:
            try:
                with winreg.OpenKey(hkey, sub) as k:
                    winreg.QueryValueEx(k, "pv")
                    log("WebView2 check: found in registry")
                    return True
            except OSError:
                continue
    except Exception:
        pass
    log("WebView2 check: NOT FOUND")
    return False


def show_error_dialog(title: str, message: str) -> None:
    """Show a native Windows MessageBox (works in windowed PyInstaller EXE)."""
    log(f"show_error_dialog: {title}")
    ctypes.windll.user32.MessageBoxW(0, message, title, 0x40 | 0x1)  # 0x40=info, 0x1=OK


# ---------- 单实例保护 ----------

# 命名互斥体，进程崩溃时由系统自动释放，不会留下死锁
_MUTEX_NAME = "Local\\DownloadKit_SingleInstance_v1"
_mutex_handle = None


def acquire_single_instance() -> bool:
    """尝试抢占单实例锁。

    为什么要这个：
      下面 pick_port 遇到端口占用会换一个端口继续开，所以连双击两次
      就会开出两个窗口、两个 uvicorn、两个 Playwright Chromium。
      而 Chromium 独占 profile 目录（SingletonLock），
      两个实例抢同一份 profile 会让登录和下载互相破坏。

    Returns:
        True  = 抢到了锁，本实例是第一个
        False = 已有实例在跑
    """
    global _mutex_handle
    try:
        kernel32 = ctypes.windll.kernel32
        # CreateMutexW(安全属性, 初始拥有者=False, 名字)
        handle = kernel32.CreateMutexW(None, False, _MUTEX_NAME)
        if not handle:
            # 拿不到锁就别拦着用户，退回旧行为
            log("单实例锁创建失败，跳过检查")
            return True
        _mutex_handle = handle
        # 183 = ERROR_ALREADY_EXISTS
        already = kernel32.GetLastError() == 183
        log(f"单实例检查: {'已在运行' if already else '首个实例'}")
        return not already
    except Exception as e:
        log(f"单实例检查异常，跳过: {e}")
        return True


def focus_existing_window() -> bool:
    """把已在运行的窗口顶到前台，省得用户以为没启动"""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW(None, WINDOW_TITLE)
        if not hwnd:
            return False
        user32.ShowWindow(hwnd, 9)      # SW_RESTORE，先从最小化恢复
        user32.SetForegroundWindow(hwnd)
        log(f"已把已有窗口置前: HWND={hwnd}")
        return True
    except Exception as e:
        log(f"置前已有窗口失败: {e}")
        return False


def make_uvicorn_log_config():
    """Build a uvicorn log_config that won't touch sys.stdout/sys.stderr.isatty().

    In windowed PyInstaller EXEs, sys.stdout and sys.stderr are None, which
    makes uvicorn's default `use_colors=None` (→ sys.stdout.isatty()) crash.
    We force `use_colors=False` for every formatter, even ones that don't
    declare it in the default config (e.g. uvicorn's `access` formatter).
    """
    import uvicorn.config as uvicorn_config
    cfg = copy.deepcopy(uvicorn_config.LOGGING_CONFIG)
    if "formatters" in cfg:
        for name, fmt in cfg["formatters"].items():
            if isinstance(fmt, dict):
                fmt["use_colors"] = False
    return cfg


# ---------- main ----------

def main():
    global PORT
    log("=== downloadkit starting ===")
    log(f"sys.executable: {sys.executable}")
    log(f"frozen: {getattr(sys, 'frozen', False)}")
    log(f"sys.stdout: {sys.stdout}, sys.stderr: {sys.stderr}")

    # 0. 单实例保护。必须在任何重活（起浏览器、开端口）之前做。
    if not acquire_single_instance():
        log("已有实例在跑，激活它的窗口后退出")
        focus_existing_window()
        show_error_dialog(
            "DownloadKit - 已在运行",
            "DownloadKit 已经在运行了。\n\n"
            "本程序同一时间只允许开一个实例，\n"
            "因为下载和登录共用同一个浏览器配置，多开会互相冲突。\n\n"
            "如果窗口没出现，请在任务栏里找 DownloadKit。",
        )
        sys.exit(0)

    # 1. Pre-flight: check WebView2 (only matters when we actually need a window)
    if not is_webview2_installed():
        log("WebView2 missing, showing error dialog")
        msg = (
            "您的电脑缺少 Microsoft Edge WebView2 组件，无法启动下载窗口。\n\n"
            "WebView2 是 Windows 10/11 自带的组件，绝大部分电脑已自动安装。"
            "若本机检测不到，请按以下步骤操作：\n\n"
            "1. 点击 [确定] 后会打开微软官方下载页\n"
            "2. 下载 \"Evergreen Standalone Installer\" (约 80MB)\n"
            "3. 双击安装\n"
            "4. 重新运行本程序\n"
        )
        show_error_dialog("DownloadKit - 缺少必要组件", msg)
        try:
            webbrowser.open(WEBVIEW2_DOWNLOAD_URL)
        except Exception:
            pass
        sys.exit(1)
    log("WebView2 OK")

    # 2. Pick a port
    if check_port(PORT):
        log(f"Port {PORT} in use, finding another")
        PORT = find_available_port()
        log(f"Using port {PORT}")

    URL = f"http://{HOST}:{PORT}"
    log(f"Target URL: {URL}")

    # 3. Set up import path so `import server` works in onefile mode
    project_dir = Path(__file__).parent
    sys.path.insert(0, str(project_dir))
    log(f"project_dir: {project_dir}")

    # 4. Import server
    try:
        log("Importing uvicorn...")
        import uvicorn
        log("uvicorn imported")
        import server  # noqa: F401 — ensures server.app exists
        log(f"server module loaded: {server.__file__ if hasattr(server, '__file__') else '?'}")
    except ModuleNotFoundError as e:
        # 依赖缺失：给中文可操作提示，而不是裸露的英文报错
        log(f"ModuleNotFoundError: {e}")
        missing = missing_modules()
        if missing:
            report_missing_deps(missing)
        else:
            show_error_dialog(
                "DownloadKit - 启动失败",
                f"缺少模块 {e.name}。\n\n"
                "请在项目文件夹里按住 Shift 右键 →「在此处打开 PowerShell 窗口」，"
                "然后执行：\n\n"
                "  .venv\\Scripts\\pip install -e \".[media,dev,douyin,desktop]\"\n",
            )
        sys.exit(1)
    except Exception:
        log(f"Import error:\n{traceback.format_exc()}")
        show_error_dialog("DownloadKit - 启动失败", f"加载 server 模块失败：\n{traceback.format_exc()[:800]}")
        sys.exit(1)

    # 5. Build uvicorn config with patched log_config (no isatty)
    log("Building custom log_config...")
    try:
        log_config = make_uvicorn_log_config()
        log("log_config built")
    except Exception:
        log(f"log_config error:\n{traceback.format_exc()}")
        show_error_dialog("DownloadKit - 启动失败", f"构造日志配置失败：\n{traceback.format_exc()[:800]}")
        sys.exit(1)

    log("Creating uvicorn Config...")
    try:
        config = uvicorn.Config(
            server.app,
            host=HOST,
            port=PORT,
            log_level="warning",
            reload=False,
            log_config=log_config,
        )
        log("uvicorn Config created")
    except Exception:
        log(f"uvicorn.Config error:\n{traceback.format_exc()}")
        show_error_dialog("DownloadKit - 启动失败", f"uvicorn 初始化失败：\n{traceback.format_exc()[:800]}")
        sys.exit(1)

    try:
        server_obj = uvicorn.Server(config)
        log("uvicorn Server object created")
    except Exception:
        log(f"uvicorn.Server error:\n{traceback.format_exc()}")
        show_error_dialog("DownloadKit - 启动失败", f"uvicorn Server 创建失败：\n{traceback.format_exc()[:800]}")
        sys.exit(1)

    # 6. Start uvicorn in a background thread
    def _run_server():
        try:
            log("uvicorn: starting")
            server_obj.run()
        except Exception:
            log(f"uvicorn crashed:\n{traceback.format_exc()}")
        finally:
            log("uvicorn: stopped")

    server_thread = threading.Thread(target=_run_server, daemon=True, name="uvicorn")
    server_thread.start()
    log("uvicorn thread started")

    # 7. Wait until uvicorn is actually listening
    deadline = time.time() + 15
    while time.time() < deadline:
        if check_port(PORT):
            log(f"Port {PORT} is listening")
            break
        time.sleep(0.2)
    else:
        log(f"Server failed to listen on {URL} within 15s")
        show_error_dialog("DownloadKit - 启动失败", f"后端服务在 15 秒内未监听 {URL}")
        sys.exit(1)

    print(f"downloadkit server ready at {URL}")

    # 8. Open native window
    log("Creating pywebview window...")
    try:
        import webview
        window = webview.create_window(
            title=WINDOW_TITLE,
            url=URL,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            resizable=True,
            confirm_close=False,
        )
        log("pywebview window created")
    except Exception:
        log(f"pywebview window error:\n{traceback.format_exc()}")
        show_error_dialog("DownloadKit - 启动失败", f"创建桌面窗口失败：\n{traceback.format_exc()[:800]}")
        sys.exit(1)

    # When the user closes the window, signal uvicorn to stop.
    def _on_closed():
        log("Window closed by user")
        server_obj.should_exit = True

    window.events.closed += _on_closed

    # webview.start() blocks until all windows are closed
    log("webview.start() - blocking until window closes")
    try:
        webview.start()
    except Exception:
        log(f"webview.start() error:\n{traceback.format_exc()}")
    log("webview.start() returned")

    # 9. After window closes, give uvicorn up to 3s to shut down cleanly
    server_obj.should_exit = True
    server_thread.join(timeout=3)
    log("=== downloadkit exiting ===")
    sys.exit(0)


if __name__ == "__main__":
    # 双击 .py 会用全局 Python，先自举切到 .venv
    if relaunch_in_venv():
        sys.exit(0)
    main()
