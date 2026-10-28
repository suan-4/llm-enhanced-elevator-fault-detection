@echo off
chcp 65001 > nul
setlocal

REM ============================================================
REM  电梯安全评估系统 — 构建并部署到 RK3588 板端（adb）
REM  板端实测布局（Ubuntu 22.04, EM-R16, RK3588）:
REM    项目根目录 : /home/ubuntu/elevator
REM    后端       : /home/ubuntu/elevator/backend   (WorkingDirectory)
REM    前端产物   : /home/ubuntu/elevator/web/dist   ← Vite 构建输出
REM    原生应用   : /home/user/elevator_app.py       (GTK + WebKit2)
REM    服务       : elevator-api.service (8081) / elevator-rkllm.service (8080)
REM    快照目录   : /userdata/releases/<时间戳>       ← 每次部署前的存档
REM ============================================================

set ROOT=/home/ubuntu/elevator

echo.
echo [0/7] 检查 adb 连接...
adb devices
adb shell "echo ok" > nul 2>&1 || (echo 板端未连接，请检查 adb devices & pause & exit /b 1)

echo.
echo [1/7] 构建前端...
pushd web
call npm run build
if errorlevel 1 (
  popd
  echo.
  echo 前端构建失败，已中止部署。请先修复构建错误。
  pause
  exit /b 1
)
popd

echo.
echo [2/7] 快照板端当前状态（失败可回滚）...
adb shell "TS=$(date +%%Y%%m%%d_%%H%%M%%S); mkdir -p /userdata/releases/$TS; cp -a %ROOT%/backend/app /userdata/releases/$TS/app 2>/dev/null; cp -a %ROOT%/web /userdata/releases/$TS/web 2>/dev/null; echo   快照: /userdata/releases/$TS"

echo.
echo [3/7] 推送前端构建产物到 web/dist ...
REM 先推到 dist.new，再原子替换。
REM   - 不能先 rm -rf 旧产物：一体机界面可能正停在旧 index.html 上，
REM     它引用的 hash 文件被删掉就会变成整片空白（已复现）。
REM   - 也不就地覆盖：就地覆盖期间页面可能读到"半份产物"。
REM 历史 hash 文件由构建脚本按时间清理（web/scripts/prune-dist.mjs）。
adb shell "rm -rf %ROOT%/web/dist.new"
adb push web\dist %ROOT%/web/dist.new
adb shell "cd %ROOT%/web && rm -rf dist.old && if [ -d dist ]; then mv dist dist.old; fi && mv dist.new dist && rm -rf dist.old && echo   已原子替换 dist"

echo.
echo [4/7] 推送后端 (backend/app/) ...
adb push backend\app %ROOT%/backend/

REM 知识图谱 v2 只读索引（8MB，不进 Git）：有就一并部署，没有则跳过。
if exist backend\data\kg_v2.sqlite (
  echo   推送知识图谱索引 kg_v2.sqlite ...
  adb shell "mkdir -p %ROOT%/backend/data"
  adb push backend\data\kg_v2.sqlite %ROOT%/backend/data/kg_v2.sqlite
)

echo.
echo [5/7] 推送原生应用与一体机组件到 /tmp ...
adb push native\elevator_app.py /tmp/elevator_app.py
adb push kiosk\elevator-kiosk.sh /tmp/elevator-kiosk.sh
adb push kiosk\elevator-launch.sh /tmp/elevator-launch.sh
adb push kiosk\elevator-kiosk.desktop /tmp/elevator-kiosk.desktop
adb push kiosk\elevator.desktop /tmp/elevator.desktop
adb push kiosk\harden_kiosk.sh /tmp/harden_kiosk.sh
adb push kiosk\install_kiosk.sh /tmp/install_kiosk.sh
adb push osk-helper\elevator-osk@local /tmp/elevator-osk@local

echo.
echo [6/7] 清理字节码缓存并重启后端...
adb shell "find %ROOT%/backend -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null; echo   cleaned"
REM 必须用 systemctl 重启：该服务配了 Restart=always，
REM 手工启动会和 systemd 拉起的进程抢 8081 端口。
adb shell "systemctl restart elevator-api.service; sleep 6; systemctl is-active elevator-api.service"

echo.
echo [7/7] 校验部署结果...
REM 白屏在板端极难排查，因此这里必须自动校验：接口、首页、以及页面真正引用的产物。
adb shell "curl -sf -o /dev/null -w '  健康检查  %%{http_code}\n' http://127.0.0.1:8081/api/health"
adb shell "curl -sf -o /dev/null -w '  就绪探针  %%{http_code}\n' http://127.0.0.1:8081/api/health/ready"
adb shell "curl -sf -o /dev/null -w '  首页      %%{http_code}\n' http://127.0.0.1:8081/"
adb shell "J=$(ls -1 %ROOT%/web/dist/assets/*.js 2>/dev/null | head -1); echo   产物文件: $J; curl -sf -o /dev/null -w '  产物访问  %%{http_code}\n' http://127.0.0.1:8081/assets/$(basename $J)"
adb shell "curl -sf -o /dev/null -w '  条目目录  %%{http_code}\n' http://127.0.0.1:8081/api/report/jte-items"

echo.
echo ============================================================
echo  部署完成
echo  板端访问 : 只在板子本机 http://127.0.0.1:8081
echo             （服务已收紧为仅监听回环；若确实需要从电脑访问，
echo               把 /etc/systemd/system/elevator-api.service 里的
echo               --host 127.0.0.1 改回 0.0.0.0 再 daemon-reload + restart）
echo  调试用   : adb forward tcp:18081 tcp:8081  ^(电脑上访问 127.0.0.1:18081^)
echo  业务库   : /userdata/elevator/elevator.db  （部署不覆盖；已迁到持久分区）
echo  备份     : /userdata/backup/  每日 03:30 自动备份（elevator-backup.timer）
echo  回滚快照 : /userdata/releases/ 下的最新目录
echo.
echo  注意：条目目录接口返回 401 属正常（未带登录令牌时会鉴权拦截），
echo        只要不是 404/500 即说明路由与数据文件都在。
echo.
echo  如需把原生应用/扩展/一体机配置装到板端：
echo    adb shell "sudo bash /tmp/install_kiosk.sh"
echo  然后重启板端（扩展需要重新登录桌面才会加载）。
echo ============================================================
pause
