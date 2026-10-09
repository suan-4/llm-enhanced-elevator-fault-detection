#!/bin/bash
# ============================================================
#  RK3588 板端「一体机」模式安装器（方案 A）
#
#  目标形态：
#    - 开机自动全屏进入电梯安全评估系统，看不到也退不出桌面
#    - 需要退出时，用界面上的「退出系统」按钮返回桌面
#    - 桌面上的「电梯安全评估系统」快捷方式可再次启动
#
#  用法: sudo bash install_kiosk.sh          # 安装
#        sudo bash install_kiosk.sh remove   # 卸载，恢复普通桌面
#
#  依赖 /tmp 下已就位的文件（由 push.bat / deploy_rk3588.sh 推送）：
#    elevator_app.py, elevator-kiosk.sh, elevator-launch.sh,
#    elevator-kiosk.desktop, elevator.desktop, elevator-osk@local/
# ============================================================
set -u

KIOSK_USER="${KIOSK_USER:-user}"
USER_HOME=$(getent passwd "$KIOSK_USER" | cut -d: -f6)
USER_UID=$(id -u "$KIOSK_USER")
AUTOSTART_DIR="$USER_HOME/.config/autostart"
APPS_DIR="$USER_HOME/.local/share/applications"
ICONS_DIR="$USER_HOME/.local/share/icons"
EXT_PARENT="$USER_HOME/.local/share/gnome-shell/extensions"
EXT_DIR="$EXT_PARENT/elevator-osk@local"
LAUNCHER="$USER_HOME/elevator-kiosk.sh"       # Chromium 方案（备用）
LAUNCH_WRAPPER="$USER_HOME/elevator-launch.sh"  # 统一入口（当前指向 GTK 方案）
NATIVE_APP="$USER_HOME/elevator_app.py"         # GTK 原生方案（当前使用）
DESKTOP_DIR=$(su "$KIOSK_USER" -c "xdg-user-dir DESKTOP" 2>/dev/null || echo "$USER_HOME/Desktop")
DBUS="unix:path=/run/user/$USER_UID/bus"
SHORTCUT_NAME="电梯安全评估系统.desktop"

if [ ! -d "$USER_HOME" ]; then
  echo "找不到用户 $KIOSK_USER 的家目录，退出"; exit 1
fi

as_user() { su "$KIOSK_USER" -c "DBUS_SESSION_BUS_ADDRESS=$DBUS DISPLAY=:0 $*"; }

# ---------------- 卸载 ----------------
if [ "${1:-}" = "remove" ]; then
  echo "[卸载] 移除自动启动、桌面快捷方式与应用菜单项..."
  rm -f "$AUTOSTART_DIR/elevator-kiosk.desktop"
  rm -f "$APPS_DIR/elevator.desktop"
  rm -f "$DESKTOP_DIR/$SHORTCUT_NAME"
  pkill -f "elevator-kiosk.sh" 2>/dev/null
  pkill -f "elevator-kiosk-profile" 2>/dev/null
  as_user "gnome-extensions disable elevator-osk@local" >/dev/null 2>&1
  rm -rf "$EXT_DIR"
  echo "[卸载] 屏幕键盘桥扩展已移除（注销后生效）"
  bash "$(dirname "$0")/harden_kiosk.sh" revert 2>/dev/null || true
  echo "[卸载] 完成（启动器脚本保留在 $USER_HOME，可手动删除）"
  exit 0
fi

# ---------------- 安装 ----------------
echo "[1/7] 安装启动器与快捷入口"
install -m 0755 -o "$KIOSK_USER" -g "$KIOSK_USER" /tmp/elevator_app.py "$NATIVE_APP" 2>/dev/null || \
  { cp /tmp/elevator_app.py "$NATIVE_APP"; chmod 755 "$NATIVE_APP"; chown "$KIOSK_USER:$KIOSK_USER" "$NATIVE_APP"; }
echo "      $NATIVE_APP   <- 当前实际启动的应用（GTK + WebKit）"
install -m 0755 -o "$KIOSK_USER" -g "$KIOSK_USER" /tmp/elevator-kiosk.sh "$LAUNCHER" 2>/dev/null || \
  { cp /tmp/elevator-kiosk.sh "$LAUNCHER"; chmod 755 "$LAUNCHER"; chown "$KIOSK_USER:$KIOSK_USER" "$LAUNCHER"; }
install -m 0755 -o "$KIOSK_USER" -g "$KIOSK_USER" /tmp/elevator-launch.sh "$LAUNCH_WRAPPER" 2>/dev/null || \
  { cp /tmp/elevator-launch.sh "$LAUNCH_WRAPPER"; chmod 755 "$LAUNCH_WRAPPER"; chown "$KIOSK_USER:$KIOSK_USER" "$LAUNCH_WRAPPER"; }
echo "      $LAUNCHER"
echo "      $LAUNCH_WRAPPER"

echo "[2/7] 生成应用图标"
mkdir -p "$ICONS_DIR"
if [ ! -f "$ICONS_DIR/elevator.png" ]; then
  python3 - <<'PY' 2>/dev/null || echo "      (图标生成失败，将使用默认图标)"
from PIL import Image
logo = Image.open('/home/ubuntu/elevator/web/fslogo.png').convert('RGBA')
w = 232; h = int(logo.height * w / logo.width)
logo = logo.resize((w, h), Image.LANCZOS)
c = Image.new('RGBA', (256, 256), (255, 255, 255, 255))
c.paste(logo, ((256 - w)//2, (256 - h)//2), logo)
c.save('$ICONS_DIR/elevator.png')
PY
fi
chown -R "$KIOSK_USER:$KIOSK_USER" "$ICONS_DIR" 2>/dev/null
echo "      $ICONS_DIR/elevator.png"

echo "[3/7] 安装开机自启项"
mkdir -p "$AUTOSTART_DIR" "$APPS_DIR"
cp /tmp/elevator-kiosk.desktop "$AUTOSTART_DIR/elevator-kiosk.desktop"
chmod 644 "$AUTOSTART_DIR/elevator-kiosk.desktop"

echo "[4/7] 安装桌面快捷方式 -> $DESKTOP_DIR/$SHORTCUT_NAME"
mkdir -p "$DESKTOP_DIR"
cp /tmp/elevator.desktop "$DESKTOP_DIR/$SHORTCUT_NAME"
cp /tmp/elevator.desktop "$APPS_DIR/elevator.desktop"
chmod 755 "$DESKTOP_DIR/$SHORTCUT_NAME"
chmod 644 "$APPS_DIR/elevator.desktop"
chown -R "$KIOSK_USER:$KIOSK_USER" "$DESKTOP_DIR" "$APPS_DIR" "$AUTOSTART_DIR"
# GNOME(ding 扩展) 要求桌面图标被"信任"才允许双击启动
as_user "gio set '$DESKTOP_DIR/$SHORTCUT_NAME' metadata::trusted true" 2>/dev/null && \
  echo "      已标记为受信任（可直接双击）" || echo "      (信任标记失败，首次双击时选择「允许启动」即可)"

echo "[5/7] 安装屏幕键盘桥扩展"
mkdir -p "$EXT_DIR"
cp /tmp/elevator-osk@local/metadata.json /tmp/elevator-osk@local/extension.js "$EXT_DIR/" 2>/dev/null
if [ -f "$EXT_DIR/extension.js" ]; then
  chmod 644 "$EXT_DIR/metadata.json" "$EXT_DIR/extension.js"
  chown -R "$KIOSK_USER:$KIOSK_USER" "$EXT_PARENT"
  # 注意：gnome-extensions enable 走的是 org.gnome.Shell.Extensions D-Bus，
  # 而 Shell 还没扫描到这个新装的扩展时会直接报错。所以必须准备一条
  # 直接写 dconf 的回退路径 —— 实测 Shell 会**热加载**这个键的变化，
  # 不需要注销或重启（已验证：改完 enabled-extensions 后扩展立即生效）。
  if as_user "gnome-extensions enable elevator-osk@local" >/dev/null 2>&1; then
    echo "      $EXT_DIR （已启用）"
  else
    cat > /tmp/_ext_enable.py <<'PY'
import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio
UUID = 'elevator-osk@local'
s = Gio.Settings(schema_id='org.gnome.shell')
cur = list(s.get_strv('enabled-extensions'))
if UUID not in cur:
    cur.append(UUID)
    s.set_strv('enabled-extensions', cur)
print('enabled-extensions =', list(s.get_strv('enabled-extensions')))
PY
    if as_user "python3 /tmp/_ext_enable.py" 2>/dev/null | grep -q elevator-osk; then
      echo "      $EXT_DIR （已通过 dconf 启用，Shell 会热加载）"
    else
      echo "      $EXT_DIR （已安装，但自动启用失败）"
      echo "      请手动执行: gnome-extensions enable elevator-osk@local"
    fi
  fi
else
  echo "      (未找到 /tmp/elevator-osk@local/，跳过)"
  echo "      X11 下 GNOME 不会为外部应用自动弹软键盘，缺此扩展则输入框无法自动呼出键盘"
fi

echo "[6/7] 加固：隐藏桌面、解除退回桌面的快捷键"
bash "$(dirname "$0")/harden_kiosk.sh" apply 2>/dev/null || \
  echo "      (harden_kiosk.sh 未随附，跳过；可单独执行)"

echo "[7/7] 优化开机速度：禁用无用的 atopacct"
if systemctl is-enabled atopacct.service > /dev/null 2>&1; then
  systemctl disable atopacct.service atop.service > /dev/null 2>&1
  systemctl mask atopacct.service > /dev/null 2>&1
  echo "      已禁用 atopacct（该服务在内核缺少 TASKSTATS 时会让开机多等 90 秒）"
else
  echo "      atopacct 已处于禁用状态"
fi

echo
echo "============================================================"
echo " 安装完成"
echo ""
echo " 开机      : 自动全屏进入系统，看不到也退不出桌面"
echo " 退出到桌面: 点界面左下角「退出系统」按钮"
echo " 重新启动  : 双击桌面「电梯安全评估系统」图标"
echo " 运维应急  : Ctrl+Alt+F3 切到文本控制台（不受快捷键加固影响）"
echo " 取消安装  : sudo bash $0 remove"
echo " 日志      : $USER_HOME/.elevator-app.log   （原生应用）"
echo "             $USER_HOME/.elevator-kiosk.log （Chromium 备用方案）"
echo " 键盘桥    : 验证扩展 -> gnome-extensions info elevator-osk@local"
echo "============================================================"
