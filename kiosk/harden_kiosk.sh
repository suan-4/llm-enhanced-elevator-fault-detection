#!/bin/bash
# ============================================================
#  方案 A 加固：让用户「看不到也退不出」系统桌面
#  退出桌面改由前端「退出系统」按钮承担（调用 /api/kiosk/exit）。
#  用法: sudo bash harden_kiosk.sh [apply|revert]
# ============================================================
set -u

KIOSK_USER="${KIOSK_USER:-user}"
USER_UID=$(id -u "$KIOSK_USER" 2>/dev/null)
USER_HOME=$(getent passwd "$KIOSK_USER" | cut -d: -f6)
DBUS="unix:path=/run/user/$USER_UID/bus"

as_user() { su "$KIOSK_USER" -c "DBUS_SESSION_BUS_ADDRESS=$DBUS DISPLAY=:0 $*"; }

apply() {
  echo "[加固] 关闭自动锁屏与息屏"
  as_user "gsettings set org.gnome.desktop.screensaver lock-enabled false" 2>/dev/null
  as_user "gsettings set org.gnome.desktop.screensaver idle-activation-enabled false" 2>/dev/null
  as_user "gsettings set org.gnome.desktop.session idle-delay 0" 2>/dev/null

  echo "[加固] 关闭左上角热区"
  as_user "gsettings set org.gnome.desktop.interface enable-hot-corners false" 2>/dev/null

  echo "[加固] 关闭 mutter auto-maximize（否则软键盘会被 unredirect 吞掉）"
  # 必须关掉。Mutter 会把「比工作区大」的窗口自动最大化，并在某些情形下
  # 进一步让它带上 _NET_WM_STATE_FULLSCREEN。而全屏窗口会被 Mutter
  # **unredirect**（绕过合成器、直接送到扫描输出），于是 GNOME Shell 画在
  # 最上层的软键盘根本没有机会被合成上去 —— 症状极具迷惑性：
  # Main.keyboard.visible = true、actor 的 mapped/opacity/几何全部正常，
  # 屏幕上却什么都看不到，而且时有时无（unredirect 的启停取决于窗口状况）。
  # 应用侧也会在铺满后主动 unfullscreen() 兜底，两边都要有。
  as_user "gsettings set org.gnome.mutter auto-maximize false" 2>/dev/null && \
    echo "    auto-maximize 已关闭"

  echo "[加固] 关闭无障碍屏幕放大器（避免误触把整屏放大 2 倍）"
  as_user "gsettings set org.gnome.desktop.a11y.applications screen-magnifier-enabled false" 2>/dev/null

  echo "[加固] 关闭 NetworkManager 联网检测（消除开机的「网络登录/热点登录」误报）"
  # 本机是完全离线的一体机：后端、Neo4j、RKLLM 全部在本地。
  # NM 默认拿 connectivity-check.ubuntu.com 做联网检测；板子没有公网出口时
  # 检测必然超时，NM 判定为「受限(limited)」，GNOME 便据此认为处在需要登录的
  # 热点/酒店网络中，于是 D-Bus 拉起 gnome-shell-portal-helper 并弹出
  # 「网络登录」通知 —— 而那个窗口只会显示 "Could not connect: Network is
  # unreachable"。关掉检测即可从源头消除；关掉后 CONNECTIVITY 变为「未知」，
  # GNOME 不会再走门户分支。
  mkdir -p /etc/NetworkManager/conf.d
  cat > /etc/NetworkManager/conf.d/20-no-connectivity-check.conf <<'NMEOF'
# 由 elevator kiosk 安装器写入：本机离线运行，不需要联网检测。
# 保留此文件可避免开机弹出「网络登录/热点登录」误报。
[connectivity]
enabled=false
NMEOF
  if systemctl reload NetworkManager 2>/dev/null; then
    echo "    已关闭（NetworkManager 已重载）"
  else
    echo "    (NetworkManager 重载失败，重启后生效)"
  fi

  echo "[加固] 把「等待应用启动」期间的桌面做成空屏（消除开机闪一下桌面的观感）"
  # 即使在自启项里把延迟降到 0，GNOME Shell 先就绪、应用后映射窗口，
  # 中间仍会露出一小段桌面。若桌面是 Ubuntu 紫色壁纸 + 桌面图标 + 左侧 Dock，
  # 这一段就非常显眼；做成与应用同色系的纯色空屏后，视觉上几乎看不出接缝。
  # ★ 不能只把 picture-uri 设成空串 ★
  #   实测 GNOME 不接受空 URI，会自己把默认壁纸回填回去
  #   （canvas_by_roytanck.jpg / warty-final-ubuntu.png 都出现过），
  #   于是桌面又变成花哨壁纸。这里直接生成一张与登录页同色系的纯色 PNG
  #   并指向它，最稳。色值取应用启动页渐变的起始色 #10365f。
  BG_PNG="$USER_HOME/.elevator-bg.png"
  python3 - "$BG_PNG" <<'PY' 2>/dev/null || true
import sys
try:
    from PIL import Image
    Image.new("RGB", (16, 16), (0x10, 0x36, 0x5F)).save(sys.argv[1])
except Exception:
    pass
PY
  if [ -f "$BG_PNG" ]; then
    chown "$KIOSK_USER:$KIOSK_USER" "$BG_PNG" 2>/dev/null
    chmod 644 "$BG_PNG" 2>/dev/null
    as_user "gsettings set org.gnome.desktop.background picture-uri 'file://$BG_PNG'" 2>/dev/null
    as_user "gsettings set org.gnome.desktop.background picture-uri-dark 'file://$BG_PNG'" 2>/dev/null
    as_user "gsettings set org.gnome.desktop.background picture-options 'scaled'" 2>/dev/null
  fi
  as_user "gsettings set org.gnome.desktop.background primary-color '#10365f'" 2>/dev/null
  as_user "gsettings set org.gnome.desktop.background color-shading-type 'solid'" 2>/dev/null
  as_user "gsettings set org.gnome.desktop.background show-desktop-icons false" 2>/dev/null
  # 桌面图标（ding 扩展）
  as_user "gsettings set org.gnome.shell.extensions.ding show-home false" 2>/dev/null
  as_user "gsettings set org.gnome.shell.extensions.ding show-trash false" 2>/dev/null
  as_user "gsettings set org.gnome.shell.extensions.ding show-volumes false" 2>/dev/null
  # 左侧 Dock（Ubuntu dock 即 dash-to-dock）：改成自动隐藏
  as_user "gsettings set org.gnome.shell.extensions.dash-to-dock dock-fixed false" 2>/dev/null
  as_user "gsettings set org.gnome.shell.extensions.dash-to-dock autohide true" 2>/dev/null
  as_user "gsettings set org.gnome.shell.extensions.dash-to-dock intellihide true" 2>/dev/null
  echo "    壁纸已改纯色 #10365f、桌面图标已关、Dock 已自动隐藏"

  echo "[加固] 解除退回桌面的快捷键（退出请用界面上的「退出系统」按钮）"
  # Alt+F4 关闭窗口 —— 这是原先退回桌面的主要途径
  as_user "gsettings set org.gnome.desktop.wm.keybindings close \"[]\"" 2>/dev/null && echo "    Alt+F4 已解除"
  # Super 打开活动概览
  as_user "gsettings set org.gnome.mutter overlay-key ''" 2>/dev/null && echo "    Super 概览键已解除"
  # Super+S 概览
  as_user "gsettings set org.gnome.shell.keybindings toggle-overview \"[]\"" 2>/dev/null
  # Alt+F1 应用菜单
  as_user "gsettings set org.gnome.desktop.wm.keybindings panel-main-menu \"[]\"" 2>/dev/null

  echo
  echo "  注意：Ctrl+Alt+F3 仍可切到文本控制台（运维应急用），不受上述限制。"
  echo "  恢复：sudo bash $0 revert"
}

revert() {
  echo "[还原] 恢复默认快捷键与桌面行为"
  as_user "gsettings reset org.gnome.desktop.wm.keybindings close" 2>/dev/null
  as_user "gsettings reset org.gnome.mutter overlay-key" 2>/dev/null
  as_user "gsettings reset org.gnome.shell.keybindings toggle-overview" 2>/dev/null
  as_user "gsettings reset org.gnome.desktop.wm.keybindings panel-main-menu" 2>/dev/null
  as_user "gsettings reset org.gnome.desktop.screensaver lock-enabled" 2>/dev/null
  as_user "gsettings reset org.gnome.desktop.screensaver idle-activation-enabled" 2>/dev/null
  as_user "gsettings reset org.gnome.desktop.session idle-delay" 2>/dev/null
  as_user "gsettings reset org.gnome.desktop.interface enable-hot-corners" 2>/dev/null
  as_user "gsettings reset org.gnome.mutter auto-maximize" 2>/dev/null
  as_user "gsettings reset org.gnome.desktop.a11y.applications screen-magnifier-enabled" 2>/dev/null
  rm -f /etc/NetworkManager/conf.d/20-no-connectivity-check.conf
  systemctl reload NetworkManager 2>/dev/null
  as_user "gsettings reset org.gnome.desktop.background picture-uri" 2>/dev/null
  as_user "gsettings reset org.gnome.desktop.background picture-uri-dark" 2>/dev/null
  as_user "gsettings reset org.gnome.desktop.background picture-options" 2>/dev/null
  as_user "gsettings reset org.gnome.desktop.background primary-color" 2>/dev/null
  as_user "gsettings reset org.gnome.desktop.background color-shading-type" 2>/dev/null
  rm -f "$USER_HOME/.elevator-bg.png"
  as_user "gsettings reset org.gnome.shell.extensions.ding show-home" 2>/dev/null
  as_user "gsettings reset org.gnome.shell.extensions.ding show-trash" 2>/dev/null
  as_user "gsettings reset org.gnome.shell.extensions.ding show-volumes" 2>/dev/null
  as_user "gsettings reset org.gnome.shell.extensions.dash-to-dock autohide" 2>/dev/null
  as_user "gsettings reset org.gnome.shell.extensions.dash-to-dock intellihide" 2>/dev/null
  as_user "gsettings reset org.gnome.shell.extensions.dash-to-dock dock-fixed" 2>/dev/null
  echo "[还原] 完成"
}

case "${1:-apply}" in
  apply)  apply  ;;
  revert) revert ;;
  *) echo "用法: $0 [apply|revert]"; exit 1 ;;
esac
