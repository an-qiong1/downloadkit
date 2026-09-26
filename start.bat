@echo off
chcp 65001 >nul
cd /d "%~dp0"
title DownloadKit

echo.
echo   正在启动 DownloadKit，首次启动约需 5 秒...
echo   启动后会出现一个 DownloadKit 窗口。
echo   关闭本窗口 = 退出程序。
echo.

if not exist ".venv\Scripts\python.exe" (
    echo   [错误] 没找到虚拟环境 .venv
    echo.
    echo   请改用「检查环境.bat」查看修复方法。
    echo.
    timeout /t 10 >nul
    exit /b 1
)

".venv\Scripts\python.exe" run.py

echo.
echo   程序已退出。若上面有报错，请截图发给开发者。
echo.
pause
