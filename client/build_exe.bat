@echo off
REM 把托盘客户端打成单文件 .exe（PyInstaller）
REM 产物：dist\yqgl-tray.exe（约 30 MB，含 Python 运行时）
REM 双击即可运行，无需用户装 Python
cd /d "%~dp0"
pip install pyinstaller
pyinstaller --onefile --noconsole --name yqgl-tray ^
    --icon NONE ^
    --hidden-import plyer.platforms.win.notification ^
    yqgl_tray.py
echo.
echo 产物在 dist\yqgl-tray.exe
