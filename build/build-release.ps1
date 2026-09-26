<#
.SYNOPSIS
    downloadkit one-click build script (portable build)
.DESCRIPTION
    1. Check build tool (pyinstaller)
    2. PyInstaller -> onefile standalone EXE
    3. Output: dist/downloadkit.exe (~100 MB portable, double-click to run)
.NOTES
    Portable mode: no installer, no admin rights needed, no UAC.
    Just copy dist/downloadkit.exe anywhere and double-click to launch.

    To build the optional Inno Setup installer (not built by default),
    run build-installer.ps1 after this script.
#>

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

# Force UTF-8 output (avoid mojibake on Chinese Windows)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "=== downloadkit Build Script (portable) ===" -ForegroundColor Cyan
Write-Host "Project dir: $Root" -ForegroundColor Gray

# === 1. Check build tool ===
Write-Host ""
Write-Host "[1/3] Checking build tools..." -ForegroundColor Yellow

if (-not (Get-Command "pyinstaller" -ErrorAction SilentlyContinue)) {
    Write-Host "  Installing PyInstaller..." -ForegroundColor Yellow
    pip install pyinstaller
    if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller install failed"; exit 1 }
}
Write-Host "  PyInstaller OK" -ForegroundColor Green

# === 2. Clean old build (only PyInstaller outputs, NOT spec/iss/scripts) ===
Write-Host ""
Write-Host "[2/3] Cleaning old build..." -ForegroundColor Yellow
# PyInstaller outputs to dist/ and build/downloadkit/ (intermediate cache).
# DO NOT delete the whole build/ folder - that would wipe out our spec/iss/scripts.
Remove-Item -Recurse -Force "dist" -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force "build\downloadkit" -ErrorAction SilentlyContinue
Write-Host "  Cleaned" -ForegroundColor Green

# === 3. PyInstaller build ===
Write-Host ""
Write-Host "[3/3] PyInstaller (onefile)..." -ForegroundColor Yellow
pyinstaller build\pyinstaller\downloadkit.spec
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller failed (exit $LASTEXITCODE)"; exit 1 }
if (-not (Test-Path "dist\downloadkit.exe")) { Write-Error "PyInstaller did not produce dist\downloadkit.exe"; exit 1 }
$exeSize = [math]::Round((Get-Item "dist\downloadkit.exe").Length / 1MB, 2)
Write-Host "  PyInstaller done (EXE: $exeSize MB)" -ForegroundColor Green

# === Done ===
Write-Host ""
Write-Host "=== Build Result ===" -ForegroundColor Cyan
Write-Host "  EXE: dist\downloadkit.exe ($exeSize MB)" -ForegroundColor Green
Write-Host ""
Write-Host "Next: double-click dist\downloadkit.exe to launch" -ForegroundColor Cyan
Write-Host "       (or copy it anywhere - portable, no install required)" -ForegroundColor Cyan
