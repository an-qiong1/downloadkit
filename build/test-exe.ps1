# Test portable EXE + new API endpoints
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$exe = Join-Path $Root "dist\downloadkit.exe"
$logFile = Join-Path $Root "dist\downloadkit.log"
$wait = 25

Remove-Item -Force $logFile -ErrorAction SilentlyContinue
Get-Process -Name "downloadkit" -ErrorAction SilentlyContinue | Stop-Process -Force

Write-Host "=== Test 1: Launch EXE ===" -ForegroundColor Cyan
$proc = Start-Process -FilePath $exe -PassThru
$procId = $proc.Id
Write-Host "Started PID: $procId" -ForegroundColor Green
Write-Host "Waiting $wait seconds..."
Start-Sleep -Seconds $wait

$proc.Refresh()
if ($proc.HasExited) {
    Write-Host "FAILED: Process exited" -ForegroundColor Red
    if (Test-Path $logFile) { Get-Content $logFile -Tail 20 }
    exit 1
}
Write-Host "OK: Process alive" -ForegroundColor Green

# Find all downloadkit processes
$allPids = @($procId)
$children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$procId" -ErrorAction SilentlyContinue
foreach ($c in $children) {
    if ($c.Name -like "downloadkit*") {
        $allPids += $c.ProcessId
    }
}

# Find port
Write-Host ""
Write-Host "=== Test 2: Find port ===" -ForegroundColor Cyan
$ports = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $allPids -contains $_.OwningProcess -and $_.LocalPort -ge 8765 -and $_.LocalPort -le 8800 } |
    Select-Object -ExpandProperty LocalPort -Unique
if (-not $ports) {
    Write-Host "FAILED: No listening port" -ForegroundColor Red
    if (Test-Path $logFile) { Get-Content $logFile -Tail 20 }
    exit 1
}
$port = $ports[0]
Write-Host "OK: Port $port listening" -ForegroundColor Green

# Test endpoints
Write-Host ""
Write-Host "=== Test 3: New API endpoints ===" -ForegroundColor Cyan

# 3a. Settings get
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/settings/get" -UseBasicParsing -TimeoutSec 5
    Write-Host "  GET /api/settings/get  : $($r.StatusCode), $($r.Content.Length) bytes" -ForegroundColor Green
} catch {
    Write-Host "  GET /api/settings/get  : FAIL: $($_.Exception.Message)" -ForegroundColor Red
}

# 3b. Download dir info (new endpoint)
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/settings/download-dir-info?path=./downloads" -UseBasicParsing -TimeoutSec 5
    $data = $r.Content | ConvertFrom-Json
    Write-Host "  GET /api/settings/download-dir-info : $($r.StatusCode), ok=$($data.ok), absolute=$($data.absolute)" -ForegroundColor Green
} catch {
    Write-Host "  GET /api/settings/download-dir-info : FAIL: $($_.Exception.Message)" -ForegroundColor Red
}

# 3c. Download dir info (absolute path)
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/settings/download-dir-info?path=D:/tmp/test_nonexistent" -UseBasicParsing -TimeoutSec 5
    $data = $r.Content | ConvertFrom-Json
    Write-Host "  GET .../download-dir-info (bad path): ok=$($data.ok), message=$($data.message)" -ForegroundColor Green
} catch {
    Write-Host "  GET .../download-dir-info (bad path): FAIL: $($_.Exception.Message)" -ForegroundColor Red
}

# 3d. Cookie load-from-browser (will probably fail without login)
try {
    $body = '{"platform":"bilibili","browser":"edge"}'
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/cookies/load-from-browser" `
        -Method POST -Body $body -ContentType "application/json" -UseBasicParsing -TimeoutSec 10
    $data = $r.Content | ConvertFrom-Json
    Write-Host "  POST /api/cookies/load-from-browser : ok=$($data.ok), count=$($data.count)" -ForegroundColor Yellow
} catch {
    Write-Host "  POST /api/cookies/load-from-browser : FAIL: $($_.Exception.Message)" -ForegroundColor Yellow
}

# 3e. Cookie save endpoint
try {
    $body = '{"platform":"bilibili","cookie_string":"test=value; DedeUserID=12345","save_to_config":false}'
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/cookies/save" `
        -Method POST -Body $body -ContentType "application/json" -UseBasicParsing -TimeoutSec 5
    $data = $r.Content | ConvertFrom-Json
    Write-Host "  POST /api/cookies/save : $($r.StatusCode), path=$($data.path)" -ForegroundColor Green
} catch {
    Write-Host "  POST /api/cookies/save : FAIL: $($_.Exception.Message)" -ForegroundColor Red
}

# 3f. Open-dir body parsing regression (2026-09-27): fetch sends
#     string bodies as text/plain, FastAPI 0.141+ skips body parsing
#     for non-JSON content types -> 422 "Input should be a valid
#     dictionary". Assert application/json body passes Pydantic: a 404
#     "file not found" proves parsing succeeded, and this path never
#     opens an explorer window.
try {
    $body = '{"path":"__nonexistent_regression__.txt"}'
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/open-dir" `
        -Method POST -Body $body -ContentType "application/json" -UseBasicParsing -TimeoutSec 5
    Write-Host "  POST /api/open-dir : $($r.StatusCode) (unexpected but not 422)" -ForegroundColor Green
} catch {
    $code = $null
    try { $code = [int]$_.Exception.Response.StatusCode } catch {}
    if ($code -eq 404) {
        Write-Host "  POST /api/open-dir : 404 body parsed OK (file-not-found is correct)" -ForegroundColor Green
    } else {
        Write-Host "  POST /api/open-dir : FAIL($code): $($_.Exception.Message)" -ForegroundColor Red
    }
}

# 3g. History endpoints (P5-7b)
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/history?limit=5&offset=0" -UseBasicParsing -TimeoutSec 5
    Write-Host "  GET /api/history : $($r.StatusCode), $([math]::Min($r.Content.Length, 100)) bytes" -ForegroundColor Green
} catch {
    Write-Host "  GET /api/history : FAIL: $($_.Exception.Message)" -ForegroundColor Red
}
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/history/count" -UseBasicParsing -TimeoutSec 5
    Write-Host "  GET /api/history/count : $($r.StatusCode), $($r.Content)" -ForegroundColor Green
} catch {
    Write-Host "  GET /api/history/count : FAIL: $($_.Exception.Message)" -ForegroundColor Red
}

# 3h. Collections endpoints (P5-7)
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/collections" -UseBasicParsing -TimeoutSec 5
    Write-Host "  GET /api/collections : $($r.StatusCode), $([math]::Min($r.Content.Length, 100)) bytes" -ForegroundColor Green
} catch {
    Write-Host "  GET /api/collections : FAIL: $($_.Exception.Message)" -ForegroundColor Red
}

# 3i. Bookmarks probe endpoint (P5-9)
try {
    $body = '{"items":[],"urls":[],"l2":false}'
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$port/api/bookmarks/probe" `
        -Method POST -Body $body -ContentType "application/json" -UseBasicParsing -TimeoutSec 5
    Write-Host "  POST /api/bookmarks/probe (empty) : $($r.StatusCode)" -ForegroundColor Yellow
} catch {
    $code = $null
    try { $code = [int]$_.Exception.Response.StatusCode } catch {}
    if ($code -eq 400) {
        Write-Host "  POST /api/bookmarks/probe (empty) : 400 expected (no URLs to probe)" -ForegroundColor Green
    } else {
        Write-Host "  POST /api/bookmarks/probe : FAIL($code): $($_.Exception.Message)" -ForegroundColor Red
    }
}

# Cleanup
Write-Host ""
Write-Host "=== Cleanup ===" -ForegroundColor Cyan
foreach ($procIdToKill in $allPids) {
    Stop-Process -Id $procIdToKill -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
Write-Host "Done" -ForegroundColor Green
