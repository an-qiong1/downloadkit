"""打包前环境预检 —— 由 build-release.ps1 调用，也可单独运行。

    .venv\\Scripts\\python.exe build\\check-build-env.py

为什么需要它：
PyInstaller 收集的是「它自己安装所在的环境」，而不是 PATH 上看起来对的那个。
如果 fastapi / playwright 等应用依赖没装进 .venv，打包会先跑上几分钟，
最后才在 downloadkit.spec 的 collect_all('playwright') 处抛
ModuleNotFoundError —— 既慢又难懂。这里提前失败。

单独做成 .py 而不是内联 python -c，是因为 PowerShell 向 native 命令传
含双引号与换行的多行字符串会在 Windows 下被截断（实测报
"SyntaxError: '(' was never closed"），必须落成文件。
"""
import importlib.util as util
import sys

# 与 downloadkit.spec / run.py 的实际 import 对齐
REQUIRED = [
    "fastapi",       # server.py
    "uvicorn",       # server.py + run.py 起服务
    "playwright",    # douyin_browser._launch()（抖音命脉）
    "webview",       # run.py 桌面窗口（pywebview）
    "mutagen",       # tagger.py 写 ID3
    "DrissionPage",  # sniffer._get_page()（P2 L2 嗅探，spec collect_all）
    "yt_dlp",        # generic_video（P0 解析，spec collect_all）
]


def main() -> int:
    try:
        import PyInstaller
    except ImportError:
        print("  未安装 PyInstaller")
        print("  修复: .venv\\Scripts\\python.exe -m pip install pyinstaller")
        return 1

    print("  PyInstaller %s / Python %s"
          % (PyInstaller.__version__, sys.version.split()[0]))

    missing = [m for m in REQUIRED if util.find_spec(m) is None]
    if missing:
        print("  MISSING in .venv: %s" % ", ".join(missing))
        print("  修复: .venv\\Scripts\\python.exe -m pip install "
              "-e \".[desktop,douyin,media]\"")
        return 1

    print("  依赖齐全: %s" % ", ".join(REQUIRED))
    return 0


if __name__ == "__main__":
    sys.exit(main())
