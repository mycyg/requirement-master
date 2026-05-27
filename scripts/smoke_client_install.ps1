$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("yqgl-install-smoke-" + [guid]::NewGuid().ToString("N"))
$clientDir = Join-Path $tempRoot "client"
$configDir = Join-Path $tempRoot "config"
$desktopDir = Join-Path $tempRoot "desktop"
$startupDir = Join-Path $tempRoot "startup"

try {
  New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
  $env:YQGL_CLIENT_DIR = $clientDir
  $env:YQGL_CONFIG_DIR = $configDir
  $env:YQGL_DESKTOP_DIR = $desktopDir
  $env:YQGL_STARTUP_DIR = $startupDir
  $env:YQGL_SKIP_PIP = "1"
  $env:YQGL_SERVER = "http://192.168.5.53:8080"

  & (Join-Path $root "client\install-client.ps1")

  $expected = @(
    (Join-Path $clientDir "launch.ps1"),
    (Join-Path $clientDir "yqgl_tray.py"),
    (Join-Path $configDir "config.json"),
    (Join-Path $desktopDir "需求管理大师 本地工作台.lnk"),
    (Join-Path $startupDir "需求管理大师.lnk")
  )
  foreach ($path in $expected) {
    if (-not (Test-Path $path)) {
      throw "missing expected install artifact: $path"
    }
  }
  Write-Host "client install smoke ok"
} finally {
  Set-Location $root
  $env:YQGL_CLIENT_DIR = $null
  $env:YQGL_CONFIG_DIR = $null
  $env:YQGL_DESKTOP_DIR = $null
  $env:YQGL_STARTUP_DIR = $null
  $env:YQGL_SKIP_PIP = $null
  $env:YQGL_SERVER = $null
  if (Test-Path $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
  }
}
