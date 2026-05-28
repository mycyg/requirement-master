$ErrorActionPreference = "Stop"

$server = $env:YQGL_SERVER
if (-not $server) { $server = "http://192.168.5.53:8080" }

$installDir = $env:YQGL_CLIENT_DIR
if (-not $installDir) { $installDir = Join-Path $env:LOCALAPPDATA "yqgl-client" }
New-Item -ItemType Directory -Force -Path $installDir | Out-Null

Write-Host "Installing yqgl client to $installDir"
$scriptRoot = $PSScriptRoot
if (-not $scriptRoot) { $scriptRoot = (Get-Location).Path }
if (Test-Path (Join-Path $scriptRoot "yqgl_tray.py")) {
  Copy-Item -Force (Join-Path $scriptRoot "*") $installDir -Recurse
} else {
  Invoke-WebRequest -UseBasicParsing "$server/client/yqgl_tray.py" -OutFile (Join-Path $installDir "yqgl_tray.py")
  Invoke-WebRequest -UseBasicParsing "$server/client/yqgl_dashboard.py" -OutFile (Join-Path $installDir "yqgl_dashboard.py")
  Invoke-WebRequest -UseBasicParsing "$server/client/requirements.txt" -OutFile (Join-Path $installDir "requirements.txt")
  Invoke-WebRequest -UseBasicParsing "$server/client/launch.ps1" -OutFile (Join-Path $installDir "launch.ps1")
}

Set-Location $installDir
if ($env:YQGL_SKIP_PIP -ne "1") {
  python -m venv .venv
  .\.venv\Scripts\python.exe -m pip install --upgrade pip
  .\.venv\Scripts\python.exe -m pip install -r requirements.txt
} else {
  Write-Host "Skipping Python dependency install because YQGL_SKIP_PIP=1"
}

$appDir = $env:YQGL_CONFIG_DIR
if (-not $appDir) { $appDir = Join-Path $env:APPDATA "yqgl" }
New-Item -ItemType Directory -Force -Path $appDir | Out-Null
$hostOnly = ([Uri]$server).Host
$port = ([Uri]$server).Port
if ($port -lt 0) { $port = 8080 }
$config = @{
  server_url = $server
  server_scheme = ([Uri]$server).Scheme
  server_ip = $hostOnly
  server_port = $port
  client_token = ""
  client_device_id = ""
  client_device_name = "$env:COMPUTERNAME"
  project_save_root = "D:\YQGL-Work"
  sync_root = "D:\YQGL-Work"
  drive_sync_root = "D:\YQGL-Work\ProjectDrive"
  drive_sync_enabled = $false
  drive_sync_mode = "download"
  availability_status = "free"
  availability_text = ""
} | ConvertTo-Json -Depth 5
$config | Out-File -Encoding utf8 (Join-Path $appDir "config.json")

function New-YqglShortcut($shortcutPath) {
  $shell = New-Object -ComObject WScript.Shell
  $shortcut = $shell.CreateShortcut($shortcutPath)
  $shortcut.TargetPath = "powershell.exe"
  $shortcut.Arguments = "-ExecutionPolicy Bypass -File `"$installDir\launch.ps1`""
  $shortcut.WorkingDirectory = $installDir
  $shortcut.WindowStyle = 7
  $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
  $shortcut.Description = "YQGL local workbench"
  $shortcut.Save()
}

$desktopDir = $env:YQGL_DESKTOP_DIR
if (-not $desktopDir) { $desktopDir = [Environment]::GetFolderPath("DesktopDirectory") }
$startupDir = $env:YQGL_STARTUP_DIR
if (-not $startupDir) { $startupDir = [Environment]::GetFolderPath("Startup") }
New-Item -ItemType Directory -Force -Path $desktopDir | Out-Null
New-Item -ItemType Directory -Force -Path $startupDir | Out-Null
New-YqglShortcut (Join-Path $desktopDir "YQGL Workbench.lnk")
New-YqglShortcut (Join-Path $startupDir "YQGL.lnk")

Write-Host "Installed. Start with:"
Write-Host "  powershell -ExecutionPolicy Bypass -File `"$installDir\launch.ps1`""
Write-Host "Desktop shortcut and startup shortcut created."
