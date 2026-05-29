# Installs the 需求管理大师 desktop client (Rust / Tauri v2) on Windows.
#
# This downloads and runs the real NSIS installer that the server serves at
# /downloads/yqgl-client-setup.exe (built on a windows-latest CI runner).
# It does NOT install the legacy Python/pywebview tray client anymore.
$ErrorActionPreference = "Stop"

$server = $env:YQGL_SERVER
if (-not $server) { $server = "http://192.168.5.53:8080" }

Write-Host "需求管理大师 客户端安装"
Write-Host "服务器: $server"

# 1) Download the installer.
$tmp = Join-Path $env:TEMP "yqgl-client-setup.exe"
Write-Host "下载安装包 ..."
Invoke-WebRequest -UseBasicParsing "$server/downloads/yqgl-client-setup.exe" -OutFile $tmp
# Clear mark-of-the-web so SmartScreen doesn't block the silent run.
Unblock-File -Path $tmp -ErrorAction SilentlyContinue

# 2) Pre-seed the server config so first-run onboarding has the IP filled in.
#    The Tauri client migrates this legacy %APPDATA%\yqgl\config.json on first launch.
$appDir = $env:YQGL_CONFIG_DIR
if (-not $appDir) { $appDir = Join-Path $env:APPDATA "yqgl" }
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
$port = ([Uri]$server).Port
if ($port -lt 0) { $port = 8080 }
$config = @{
  server_url         = $server
  server_scheme      = ([Uri]$server).Scheme
  server_ip          = ([Uri]$server).Host
  server_port        = $port
  client_token       = ""
  client_device_id   = ""
  client_device_name = "$env:COMPUTERNAME"
  project_save_root  = "D:\YQGL-Work"
  sync_root          = "D:\YQGL-Work"
  drive_sync_root    = "D:\YQGL-Work\ProjectDrive"
  drive_sync_enabled = $false
  drive_sync_mode    = "download"
  availability_status = "free"
  availability_text  = ""
} | ConvertTo-Json -Depth 5
$config | Out-File -Encoding utf8 (Join-Path $appDir "config.json")

# 3) Run the installer.
#    Tauri NSIS installs per-user (no admin), creates Start Menu + desktop
#    shortcuts. Pass /S for an unattended install when YQGL_SILENT=1.
Write-Host "安装中 ..."
if ($env:YQGL_SILENT -eq "1") {
  Start-Process -FilePath $tmp -ArgumentList "/S" -Wait
} else {
  Start-Process -FilePath $tmp -Wait
}

Write-Host ""
Write-Host "安装完成。从开始菜单或桌面快捷方式启动「需求管理大师」即可。"
Write-Host "首次启动：确认服务器 IP -> 起昵称 -> 选本地工作目录 -> 完成设备注册。"
