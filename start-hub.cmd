@echo off
rem battery-hub launcher - keep this file ASCII-only, cmd.exe parses .cmd as ANSI
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

rem Optional: adb reverse tunnel as a fallback when the LAN path is blocked
rem adb connect 192.168.1.50:5555 >nul 2>&1
rem adb reverse tcp:18080 tcp:18080 >nul 2>&1

netstat -ano | findstr ":18080" | findstr "LISTENING" >nul 2>&1
if not errorlevel 1 goto HUB_RUNNING

start "" /min cmd /c "python hub\hub.py"
timeout /t 2 >nul
goto START_WIDGET

:HUB_RUNNING

:START_WIDGET
rem Public tunnel (OpenFrp HK node) so phones work on any network, not just the LAN
call "tools\start-tunnel.cmd"
start "" /min cmd /c "pythonw ui\pc_widget.py"
exit /b 0
