<#
.SYNOPSIS
    downloadkit 一键构建脚本
.DESCRIPTION
    1. 检查/安装构建工具 (pyinstaller, iscc)
    2. PyInstaller 编译 Python 项目为独立 EXE
    3. Inno Setup 制作 Windows 安装包
    4. 输出到 dist/downloadkit-setup.exe
#>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "=== downloadkit 构建脚本 ===" -ForegroundColor Cyan
Write-Host "项目目录: $Root" -ForegroundColor Gray

# Step 1: 检查/安装构建工具
Write-Host "`n[1/4] 检查构建工具..." -ForegroundColor Yellow

if (-not (Get-Command "pyinstaller" -ErrorAction SilentlyContinue)) {
    Write-Host "  安装 PyInstaller..." -ForegroundColor Yellow
    pip install pyinstaller
    if (-not $?) { Write-Error "PyInstaller 安装失败"; exit 1 }
}
Write-Host "  ✅ PyInstaller" -ForegroundColor Green

if (-not (Get-Command "iscc" -ErrorAction SilentlyContinue)) {
    Write-Host "  ⚠️  Inno Setup 未安装" -ForegroundColor Red
    Write-Host "  请手动安装 Inno Setup: https://jrsoftware.org/isdl.php" -ForegroundColor Yellow
    Write-Host "  或者运行: winget install InnoSetup" -ForegroundColor Yellow
    exit 1
}
Write-Host "  ✅ Inno Setup" -ForegroundColor Green

# Step 2: 清理旧构建
Write-Host "`n[2/4] 清理旧构建..." -ForegroundColor Yellow
Remove-Item -Recurse -Force "build\pyinstaller\dist", "build\pyinstaller\build" -ErrorAction SilentlyContinue
Write-Host "  ✅ 已清理" -ForegroundColor Green

# Step 3: PyInstaller 构建
Write-Host "`n[3/4] PyInstaller 构建..." -ForegroundColor Yellow
pyinstaller build\pyinstaller\downloadkit.spec
if (-not $?) { Write-Error "PyInstaller 构建失败"; exit 1 }
Write-Host "  ✅ PyInstaller 构建完成" -ForegroundColor Green

# Step 4: Inno Setup 制作安装包
Write-Host "`n[4/4] Inno Setup 制作安装包..." -ForegroundColor Yellow
iscc build\installer\downloadkit.iss
if (-not $?) { Write-Error "Inno Setup 打包失败"; exit 1 }
Write-Host "  ✅ Inno Setup 打包完成" -ForegroundColor Green

# 验证产出
Write-Host "`n=== 构建结果 ===" -ForegroundColor Cyan
if (Test-Path "dist\downloadkit-setup.exe") {
    $size = (Get-Item "dist\downloadkit-setup.exe").Length / 1MB
    Write-Host "  ✅ 安装包: dist\downloadkit-setup.exe ($('{0:N1}' -f $size) MB)" -ForegroundColor Green
} else {
    Write-Error "安装包未找到!"
    exit 1
}