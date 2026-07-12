@echo off
chcp 65001 >nul
title downloadkit Server

echo Starting downloadkit...
echo.

if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" run.py
) else (
  python run.py
)

pause
