$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$tempRoot = Join-Path ([System.IO.Path]::GetTempPath()) ("yqgl-install-smoke-" + [guid]::NewGuid().ToString("N"))
$clientDir = Join-Path $tempRoot "client"
$configDir = Join-Path $tempRoot "config"
$desktopDir = Join-Path $tempRoot "desktop"
$startupDir = Join-Path $tempRoot "startup"
$webRoot = Join-Path $tempRoot "www"
$serverProc = $null

try {
  New-Item -ItemType Directory -Force -Path $tempRoot | Out-Null
  New-Item -ItemType Directory -Force -Path (Join-Path $webRoot "client") | Out-Null
  Copy-Item -Force -Recurse (Join-Path $root "client\*") (Join-Path $webRoot "client")
  Copy-Item -Force (Join-Path $root "client\install-client.ps1") (Join-Path $webRoot "client\install.ps1")

  $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
  $listener.Start()
  $port = $listener.LocalEndpoint.Port
  $listener.Stop()
  $serverProc = Start-Process -FilePath "python" -ArgumentList @("-m", "http.server", "$port", "--bind", "127.0.0.1", "--directory", $webRoot) -WindowStyle Hidden -PassThru
  Start-Sleep -Seconds 1

  $env:YQGL_CLIENT_DIR = $clientDir
  $env:YQGL_CONFIG_DIR = $configDir
  $env:YQGL_DESKTOP_DIR = $desktopDir
  $env:YQGL_STARTUP_DIR = $startupDir
  $env:YQGL_SKIP_PIP = "1"
  $env:YQGL_SERVER = "http://127.0.0.1:$port"

  iwr -UseBasicParsing "$env:YQGL_SERVER/client/install.ps1" | iex

  $expected = @(
    (Join-Path $clientDir "launch.ps1"),
    (Join-Path $clientDir "yqgl_tray.py"),
    (Join-Path $configDir "config.json"),
    (Join-Path $desktopDir "YQGL Workbench.lnk"),
    (Join-Path $startupDir "YQGL.lnk")
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
  if ($serverProc -and -not $serverProc.HasExited) {
    Stop-Process -Id $serverProc.Id -Force
  }
  if (Test-Path $tempRoot) {
    Remove-Item -LiteralPath $tempRoot -Recurse -Force
  }
}
