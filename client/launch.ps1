$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $python)) {
  $python = "pythonw"
}

Start-Process -FilePath $python -ArgumentList @("yqgl_tray.py") -WindowStyle Hidden
