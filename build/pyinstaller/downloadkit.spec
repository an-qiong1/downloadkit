# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# Use cwd() because __file__ is not available in PyInstaller 6.x exec namespace
project_root = Path.cwd()

# 抖音路线靠 Playwright 驱动系统 Edge / 自带 Chromium。两处特殊性：
#   1) douyin_browser._launch() 是在函数体内延迟导入，静态分析扫不全
#   2) 它自带一个 89MB 的 node.exe driver，不在包里就起不来
# 必须显式收进包，否则 exe 里点「登录抖音」只会抛 ImportError。
# collect_all 只收 site-packages 里的 playwright，不会碰
# %LOCALAPPDATA%\ms-playwright 的浏览器缓存（那是 400MB+，不进包）。
pw_data, pw_binaries, pw_hiddenimports = collect_all('playwright')

a = Analysis(
    [str(project_root / 'run.py')],
    pathex=[str(project_root)],
    binaries=pw_binaries,
    datas=[
        (str(project_root / 'downloadkit' / 'static'), 'downloadkit/static'),
        (str(project_root / 'server.py'), '.'),
    ] + pw_data,
    hiddenimports=[
        # uvicorn
        'uvicorn.logging',
        'uvicorn.loops.auto',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.websockets.auto',
        # pywebview (used for the native desktop window on Windows)
        'webview',
        'webview.platforms.edgechromium',
        'webview.platforms.winforms',
        'webview.platforms.win32',
        'webview.platforms.mshtml',
        'webview.platforms.qt',
        'webview.platforms.cef',
        'webview.platforms.gtk',
        'webview.platforms.cocoa',
        'webview.platforms.android',
        'webview.http',
        'webview.util',
        'webview.localization',
        'webview.guilib',
        'webview.menu',
        'webview.models',
        'webview.screen',
        'webview.state',
        'webview.event',
        'webview.dom',
        'webview.dom.dom',
        'webview.dom.element',
        'webview.dom.event',
        'webview.dom.classlist',
        'webview.dom.propsdict',
        # pywebview dependencies
        'bottle',
        'proxy_tools',
        'clr_loader',
        'clr_loader',
        'pythonnet',
        'bottle',
    ] + pw_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Project dirs
        'tests',
        'frontend',
        'backend',
        # Heavy ML/AI libs — NOT used by downloadkit
        'torch',
        'torchvision',
        'torchaudio',
        'tensorflow',
        'tensorboard',
        'scipy',
        'scipy.signal',
        'scipy.optimize',
        'scipy.sparse',
        'scipy.linalg',
        'scipy.io',
        'scipy.integrate',
        'scipy.interpolate',
        'scipy.stats',
        'scipy.ndimage',
        'scipy.fft',
        'matplotlib',
        'pandas',
        'numpy',
        'sympy',
        'sklearn',
        'cv2',
        'opencv',
        'PIL',
        'Pillow',
        'onnxruntime',
        'numba',
        'llvmlite',
        'jedi',
        'parso',
        'black',
        'IPython',
        'ipykernel',
        'jupyter',
        'nbformat',
        'notebook',
        'pytest',
        'unittest',
        'nose',
        'mypy',
        'flake8',
        'pylint',
        'sphinx',
        'docutils',
        'bokeh',
        'plotly',
        'dash',
        'dask',
        'networkx',
        'nltk',
        'gensim',
        'statsmodels',
        'scrapy',
        'celery',
        'redis',
        'kafka',
        'zmq',
        'pyzmq',
        'cryptography',
        'bcrypt',
        'nacl',
        'opentelemetry',
        # 注意：这里曾经排除过 'playwright'，导致打包出的 exe 点抖音必抛
        # ImportError（抖音登录/抓取全废）。playwright 已改为在顶部用
        # collect_all 显式收集，绝不能放回 excludes。
        'selenium',
        'django',
        'flask',
        'sanic',
        'aiohttp',
        'gunicorn',
        'uvicorn.workers',
    ],
    noarchive=False,
    optimize=2,
)
pyz = PYZ(a.pure)

# onefile mode: a.binaries and a.datas are embedded into the EXE.
# No COLLECT step — produces a single self-contained downloadkit.exe.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='downloadkit',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / 'downloadkit.ico'),
)
