@echo off
chcp 65001 > nul
setlocal

REM ============================================================
REM  电梯安全评估系统 — 通过 adb 部署到 RK3588 板端
REM  板端实测布局（Ubuntu 22.04, EM-R16, RK3588）:
REM    项目根目录 : /home/ubuntu/elevator
REM    后端       : /home/ubuntu/elevator/backend   (WorkingDirectory)
REM    前端       : /home/ubuntu/elevator/web
REM    原生应用   : /home/user/elevator_app.py      (GTK + WebKit2)
REM    服务       : systemd elevator-api.service (8081) / elevator-rkllm.service (8080)
REM ============================================================

set ROOT=/home/ubuntu/elevator

echo.
echo [0/5] 检查 adb 连接...
adb devices
adb shell "echo ok" > nul 2>&1 || (echo 板端未连接，请检查 adb devices & pause & exit /b 1)

echo.
echo [1/5] 推送前端 (web/)...
adb push web\index.html           %ROOT%/web/
adb push web\marked.min.js        %ROOT%/web/
adb push web\fslogo.png           %ROOT%/web/
adb push web\NotoSansSymbols2.ttf %ROOT%/web/

echo.
echo [2/5] 推送后端 (backend/app/)...
adb push backend\app %ROOT%/backend/

echo.
echo [3/5] 推送原生应用与一体机组件到 /tmp...
adb push native\elevator_app.py /tmp/elevator_app.py
adb push kiosk\elevator-kiosk.sh /tmp/elevator-kiosk.sh
adb push kiosk\elevator-launch.sh /tmp/elevator-launch.sh
adb push kiosk\elevator-kiosk.desktop /tmp/elevator-kiosk.desktop
adb push kiosk\elevator.desktop /tmp/elevator.desktop
adb push kiosk\harden_kiosk.sh /tmp/harden_kiosk.sh
adb push kiosk\install_kiosk.sh /tmp/install_kiosk.sh
adb push osk-helper\elevator-osk@local /tmp/elevator-osk@local

echo.
echo [4/5] 清理字节码缓存...
adb shell "find %ROOT%/backend -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null; echo cleaned"

echo.
echo [5/5] 重启后端服务...
REM 注意：必须用 systemctl 重启，不要 pkill + 手工起 —— 该服务配了 Restart=always，
REM 手工启动会和 systemd 拉起的两份进程抢 8081 端口。
adb shell "systemctl restart elevator-api.service; sleep 6; systemctl is-active elevator-api.service"

echo.
echo ============================================================
echo  部署完成
echo  板端访问: http://^<板子IP^>:8081
echo  数据库  : %ROOT%/backend/data/elevator.db  (部署不会覆盖)
echo.
echo  如需把原生应用/扩展/一体机配置也装到板端，再执行：
echo    adb shell "sudo bash /tmp/install_kiosk.sh"
echo  然后重启板端（扩展需要重新登录才能加载）。
echo ============================================================
pause
