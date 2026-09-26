@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title DownloadKit - 环境自检

echo.
echo ============================================
echo   DownloadKit  环境自检
echo ============================================
echo.

set "PY=.venv\Scripts\python.exe"
set "FAIL=0"

if not exist "%PY%" (
    echo   [失败] 未找到虚拟环境 .venv
    echo.
    echo   请按住 Shift 右键本文件夹 -^> 在此处打开 PowerShell 窗口
    echo   然后依次执行：
    echo.
    echo     python -m venv .venv
    echo     .venv\Scripts\pip install -e ".[media,dev,douyin,desktop]"
    echo     .venv\Scripts\python -m playwright install chromium
    echo.
    goto :done
)
echo   [1/5] 虚拟环境 .venv        正常

"%PY%" -c "import sys; sys.exit(0 if sys.version_info>=(3,10) else 1)" 2>nul
if errorlevel 1 (
    echo   [失败] Python 版本过低，需要 3.10 以上
    set "FAIL=1"
) else (
    for /f "delims=" %%v in ('"%PY%" -V 2^>^&1') do echo   [2/5] %%v            正常
)

"%PY%" -c "import uvicorn, fastapi" 2>nul
if errorlevel 1 (
    echo   [失败] 缺少 uvicorn / fastapi
    set "FAIL=1"
) else (
    echo   [3/5] 后端依赖 uvicorn     正常
)

"%PY%" -c "import webview" 2>nul
if errorlevel 1 (
    echo   [失败] 缺少 pywebview，桌面窗口无法显示
    set "FAIL=1"
) else (
    echo   [4/5] 桌面窗口 pywebview  正常
)

"%PY%" -c "import playwright" 2>nul
if errorlevel 1 (
    echo   [失败] 缺少 playwright，抖音功能不可用
    set "FAIL=1"
) else (
    if exist "%LOCALAPPDATA%\ms-playwright" (
        echo   [5/5] 浏览器内核          已下载
    ) else (
        echo   [警告] 浏览器内核未下载，请执行：
        echo         .venv\Scripts\python -m playwright install chromium
        set "FAIL=1"
    )
)

if exist "C:\Program Files (x86)\Microsoft\EdgeWebView\Application" goto :wv2ok
if exist "C:\Program Files\Microsoft\EdgeWebView\Application" goto :wv2ok
echo   [警告] 未检测到 WebView2，窗口可能打不开
goto :wv2done
:wv2ok
echo   [附加] WebView2 运行时       正常
:wv2done

echo.
echo ============================================
if "%FAIL%"=="0" (
    echo   全部通过
    echo ============================================
    echo.
    echo   现在双击「启动DownloadKit.bat」即可使用
) else (
    echo   存在问题，请按上面提示修复
    echo ============================================
)
echo.
echo   本窗口不会自动关闭，看完请按任意键
echo.
pause >nul
goto :eof

:done
echo.
pause >nul
