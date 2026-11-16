@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

rem 可选：让某台设备走 adb 反向隧道（网络不通时的兜底），按需取消注释并改地址
rem adb connect 192.168.1.50:5555 >nul 2>&1
rem adb reverse tcp:18080 tcp:18080 >nul 2>&1

rem 中枢已经在跑就不重复启动（按端口判断）
netstat -ano | findstr ":18080" | findstr "LISTENING" >nul 2>&1
if errorlevel 1 (
    echo [1/2] 启动电量中枢 ^(HTTP 18080^) ...
    start "battery-hub" /min cmd /c "python hub\hub.py"
    timeout /t 2 >nul
) else (
    echo [1/2] 中枢已在运行，跳过
)

echo [2/2] 启动桌面悬浮窗 ...
start "battery-widget" /min cmd /c "pythonw ui\pc_widget.py"

timeout /t 2 >nul
echo.
echo 面板:   http://127.0.0.1:18080/
echo 上报:   POST http://^<本机IP^>:18080/report
echo 悬浮窗: 拖动移动 / 点右上角 - 折叠 / x 关闭 / 右下角拖拽调宽
echo 关闭:   悬浮窗右键"退出"；再关掉那个最小化的命令行窗口
echo.
timeout /t 3 >nul
