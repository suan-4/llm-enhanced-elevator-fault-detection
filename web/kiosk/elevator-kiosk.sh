#!/bin/bash
# ============================================================
#  电梯安全评估系统 — 自助终端(kiosk)启动器
#  由 GNOME 自动启动调用，也可在桌面上手动运行。
# ============================================================
APP_URL="http://127.0.0.1:8081/"
# 必须用就绪探针：/api/health 在 Neo4j 尚未就绪时也返回 200，
# 用它判断会导致界面抢在 Neo4j 之前打开、立刻报「图谱查询失败」。
READY_URL="http://127.0.0.1:8081/api/health/ready"
PROFILE_DIR="$HOME/.elevator-kiosk-profile"
LOG="$HOME/.elevator-kiosk.log"

log() { echo "[$(date '+%F %T')] $*" >> "$LOG"; }

# 注意：本启动器**不碰屏幕方向与缩放**。
# 开机后 GNOME 会按自己的默认配置（~/.config/monitors.xml）设置好方向与 2x 缩放；
# 任何在此处额外执行 xrandr / Mutter 改配置的动作都会把缩放重置回 1x，
# 导致整机 UI 变成一半大小。屏幕设置完全交给系统。

# ── 单实例保护（必须有）──────────────────────────────────
# 没有它会出大事：开机自启、桌面图标、手工执行三者同时触发时会拉起多个
# 启动器，各开一个 Chromium 全屏窗口，GNOME 把屏幕平铺成一堆窗口。
PIDFILE="$HOME/.elevator-kiosk.pid"
if [ -f "$PIDFILE" ]; then
  oldpid=$(cat "$PIDFILE" 2>/dev/null)
  if [ -n "$oldpid" ] && kill -0 "$oldpid" 2>/dev/null && [ "$oldpid" != "$$" ]; then
    echo "[$(date '+%F %T')] 已有启动器在运行 (pid=$oldpid)，本次直接退出" >> "$LOG"
    exit 0
  fi
fi
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT INT TERM

log "=== 启动器触发 (pid=$$) ==="

# 0) 清理上一次遗留的 kiosk 窗口
#    正常不该有（单实例保护已挡住重复启动器），但异常退出可能留下孤儿窗口
if pgrep -f "elevator-kiosk-profile" > /dev/null 2>&1; then
  log "发现遗留 kiosk 窗口，先关闭"
  pkill -f "elevator-kiosk-profile" 2>/dev/null
  sleep 3
fi

# 1) 等待后端 + Neo4j 双双就绪（最多 180 秒）
ready=0
for i in $(seq 1 180); do
  if curl -sf --max-time 3 "$READY_URL" > /dev/null 2>&1; then
    ready=1
    log "后端与 Neo4j 均就绪 (等待 ${i}s)"
    break
  fi
  sleep 1
done
if [ "$ready" != "1" ]; then
  log "警告: 180s 内未就绪，仍尝试启动界面（前端自身还会重试）"
fi

# 2) 启动 Chromium 全屏；崩溃自动重开，用户主动关闭则退回桌面
fails=0
while true; do
  start=$(date +%s)
  chromium-browser \
    --kiosk \
    --app="$APP_URL" \
    --user-data-dir="$PROFILE_DIR" \
    --noerrdialogs \
    --no-first-run \
    --disable-infobars \
    --disable-session-crashed-bubble \
    --disable-restore-session-state \
    --disable-features=TranslateUI,Translate,MediaRouter \
    --overscroll-history-navigation=0 \
    --disable-pinch \
    --password-store=basic \
    >> "$LOG" 2>&1
  end=$(date +%s)
  ran=$((end - start))
  log "Chromium 退出，运行了 ${ran}s"

  if [ "$ran" -ge 10 ]; then
    # 正常运行一段时间后被关闭 —— 视为用户主动退出，停在桌面不再拉起
    log "判定为用户主动退出，停止自动重启"
    break
  fi

  fails=$((fails + 1))
  if [ "$fails" -ge 5 ]; then
    log "连续失败 ${fails} 次，放弃并提示"
    command -v notify-send > /dev/null 2>&1 && \
      notify-send "电梯安全评估系统" "界面连续启动失败，请检查 elevator-api.service" 2>/dev/null
    break
  fi
  sleep 3
done
log "=== 启动器结束 ==="
