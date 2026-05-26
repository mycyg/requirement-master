@echo off
REM 需求管理大师托盘客户端启动器
REM 首次运行会弹窗让你填昵称 / 服务地址 / 同步目录，存到 %APPDATA%\yqgl\config.json
cd /d "%~dp0"
pythonw yqgl_tray.py
