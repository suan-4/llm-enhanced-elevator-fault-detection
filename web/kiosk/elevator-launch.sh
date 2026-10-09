#!/bin/bash
# 桌面快捷方式 / 开机自启的**统一入口**。
# 后台启动后立即返回，避免图标长时间显示"正在启动"。
#
# 当前实现：GTK 原生窗口（native/elevator_app.py，WebKit 渲染，不使用 Chromium）。
#   - 自带单实例保护：重复双击/自启只会激活已有窗口，不会开出多个
#   - 窗口策略见该文件头部注释（铺满屏幕的普通窗口，**不是** fullscreen）
#
# 若要切回 Chromium 方案，把最后那行换成：
#   setsid nohup /home/user/elevator-kiosk.sh >/dev/null 2>&1 </dev/null &

# ★★★ 必须显式兜底导出会话/输入法环境 ★★★
#
# 开机自启是 gnome-session 直接拉起的，环境完整；
# 而**桌面图标是 GNOME Shell(ding) 经 systemd --user 拉起的**，
# 那条路的环境是精简的 —— 实测只剩 DBUS_SESSION_BUS_ADDRESS 与
# XDG_RUNTIME_DIR，下面这些全都没有：
#
#     GTK_IM_MODULE / QT_IM_MODULE / CLUTTER_IM_MODULE / XMODIFIERS
#     GTK_MODULES(gail:atk-bridge) / XAUTHORITY / XDG_CURRENT_DESKTOP / LC_*
#
# 后果：GTK 找不到 GTK_IM_MODULE 就**不会加载 fcitx 输入法模块**，
# 于是「退出系统 → 双击桌面图标重新进入」后，输入框点进去也没有输入上下文
# （fcitx5-remote 返回 0），中英文切换自然无效。
# 开机自启那条路一切正常，所以这个 bug **只在走桌面图标时复现**。
#
# 用 ${VAR:-默认值} 而不是硬赋值：
#   - 环境完整时（开机自启）保留原值，完全不受影响；
#   - 环境被精简时（桌面图标）补上正确的值。
if [ -z "${XDG_RUNTIME_DIR:-}" ]; then export XDG_RUNTIME_DIR="/run/user/$(id -u)"; fi
export DBUS_SESSION_BUS_ADDRESS="${DBUS_SESSION_BUS_ADDRESS:-unix:path=$XDG_RUNTIME_DIR/bus}"
export DISPLAY="${DISPLAY:-:0}"
export GTK_IM_MODULE="${GTK_IM_MODULE:-fcitx}"
export QT_IM_MODULE="${QT_IM_MODULE:-fcitx}"
export CLUTTER_IM_MODULE="${CLUTTER_IM_MODULE:-xim}"
export XMODIFIERS="${XMODIFIERS:-@im=fcitx}"
export GTK_MODULES="${GTK_MODULES:-gail:atk-bridge}"
export LANG="${LANG:-zh_CN.UTF-8}"
export LANGUAGE="${LANGUAGE:-zh_CN:zh:en_US:en}"
export LC_ALL="${LC_ALL:-zh_CN.UTF-8}"
export XDG_CURRENT_DESKTOP="${XDG_CURRENT_DESKTOP:-ubuntu:GNOME}"
# X 授权文件那条路也没有，缺了会连不上 X
if [ -z "${XAUTHORITY:-}" ] && [ -f "$XDG_RUNTIME_DIR/gdm/Xauthority" ]; then
  export XAUTHORITY="$XDG_RUNTIME_DIR/gdm/Xauthority"
fi

setsid nohup /home/user/elevator_app.py > /dev/null 2>&1 < /dev/null &
