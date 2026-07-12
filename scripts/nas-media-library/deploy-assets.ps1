param(
    [string]$NasHost = "192.168.5.15",
    [string]$NasUser = "wuyang",
    [string]$RemoteDir = "/vol1/1000/影视/scripts/nas-media-library"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$NasDir = Join-Path $Root "nas"
$AssetsDir = Join-Path $Root "assets"

if (-not (Test-Path -LiteralPath $NasDir)) {
    throw "缺少目录：$NasDir"
}
if (-not (Test-Path -LiteralPath $AssetsDir)) {
    throw "缺少目录：$AssetsDir"
}

Write-Host "验证 SSH 免密..."
ssh -o BatchMode=yes -o ConnectTimeout=8 "$NasUser@$NasHost" "hostname" | Write-Host

Write-Host "创建远程目录：$RemoteDir"
ssh "$NasUser@$NasHost" "mkdir -p '$RemoteDir/assets'"

Write-Host "上传 NAS 脚本..."
scp (Join-Path $NasDir "*.sh") "$NasUser@$NasHost`:$RemoteDir/"

Write-Host "上传补丁资产..."
scp (Join-Path $AssetsDir "sites.py") "$NasUser@$NasHost`:$RemoteDir/assets/sites.py"

Write-Host "设置脚本执行权限..."
ssh "$NasUser@$NasHost" "chmod +x '$RemoteDir'/*.sh"

Write-Host "部署资产上传完成：$RemoteDir"
