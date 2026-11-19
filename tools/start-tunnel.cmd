@echo off
rem Start the OpenFrp tunnel (frpc) if it is not already running.
rem Keep this file ASCII-only: cmd.exe parses .cmd as ANSI.
rem frpc writes its own log to battery-hub\log\frpc.log (set in frpc.toml).
setlocal
tasklist /fi "imagename eq frpc.exe" 2>nul | findstr /i "frpc.exe" >nul
if not errorlevel 1 (
  echo [tunnel] frpc already running
  exit /b 0
)

echo [tunnel] starting frpc...
rem Use PowerShell's Start-Process: `start` from a hidden cmd proved unreliable here
powershell -NoProfile -WindowStyle Hidden -Command "Start-Process -FilePath '%~dp0frp\frp_0.72.0_windows_amd64\frpc.exe' -ArgumentList '-c','%~dp0frp\frpc.toml' -WindowStyle Hidden"
exit /b 0
