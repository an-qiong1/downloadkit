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

# Cleanup
Write-Host ""
Write-Host "=== Cleanup ===" -ForegroundColor Cyan
foreach ($procIdToKill in $allPids) {
    Stop-Process -Id $procIdToKill -Force -ErrorAction SilentlyContinue
}
Start-Sleep -Seconds 2
Write-Host "Done" -ForegroundColor Green
