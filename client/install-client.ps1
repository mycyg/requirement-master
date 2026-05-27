$ErrorActionPreference = "Stop"

$server = $env:YQGL_SERVER
if (-not $server) { $server = "http://192.168.5.53:8080" }

$installDir = Join-Path $env:LOCALAPPDATA "yqgl-client"
New-Item -ItemType Directory -Force -Path $installDir | Out-Null

Write-Host "Installing yqgl client to $installDir"
if (Test-Path (Join-Path $PSScriptRoot "yqgl_tray.py")) {
  Copy-Item -Force (Join-Path $PSScriptRoot "*") $installDir -Recurse
} else {
  Invoke-WebRequest "$server/client/yqgl_tray.py" -OutFile (Join-Path $installDir "yqgl_tray.py")
  Invoke-WebRequest "$server/client/yqgl_dashboard.py" -OutFile (Join-Path $installDir "yqgl_dashboard.py")
  Invoke-WebRequest "$server/client/requirements.txt" -OutFile (Join-Path $installDir "requirements.txt")
  Invoke-WebRequest "$server/client/launch.ps1" -OutFile (Join-Path $installDir "launch.ps1")
}

Set-Location $installDir
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

$appDir = Join-Path $env:APPDATA "yqgl"
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
$hostOnly = ([Uri]$server).Host
$port = ([Uri]$server).Port
if ($port -lt 0) { $port = 8080 }
$config = @{
  server_url = $server
  server_scheme = ([Uri]$server).Scheme
  server_ip = $hostOnly
  server_port = $port
  project_save_root = "D:\工作需求"
  sync_root = "D:\工作需求"
  drive_sync_root = "D:\工作需求\项目网盘"
  drive_sync_enabled = $false
  drive_sync_mode = "download"
  availability_status = "free"
  availability_text = ""
} | ConvertTo-Json -Depth 5
$config | Out-File -Encoding utf8 (Join-Path $appDir "config.json")

Write-Host "Installed. Start with:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$installDir\launch.ps1`""
