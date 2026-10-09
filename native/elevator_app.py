#!/usr/bin/env python3
"""电梯安全评估系统 —— 原生窗口版（GTK3 + WebKit2，不使用 Chromium）

板端已预装 libwebkit2gtk-4.0-37 / gir1.2-webkit2-4.0 / python3-gi，
零新增依赖即可得到真正的桌面应用窗口：自己的 WM_CLASS 与应用名
（GNOME 按它显示应用归属，不再是 "Chromium-browser"）、无浏览器外壳、
单实例、独立日志。

排查记录（历史坑，均已实测踩过并规避）
--------------------------------------
1) **GTK 尺寸是逻辑像素**。本机 Mutter 缩放 2×，set_default_size(1920,1200)
   会被再乘 2 → 窗口 3840×2400，内容溢出屏幕。
   → 按显示器的**逻辑**尺寸算：物理 / scale。

2) **fullscreen() 必须在窗口映射之后请求**。在 show_all() 之前、或在
   GLib.idle_add 里调用，X11 下请求都会被丢弃 → 窗口停在 GTK 默认 400×400。

3) **不能信 Gtk.Window.get_state()**。它会乐观置上 FULLSCREEN 位，
   而实际上 Mutter 可能只给了 MAXIMIZED。
   → 用 Gtk.Application（注册 application_id），并**用真实几何校验**。

4) **set_resizable(False) 会把窗口尺寸钉死**（WM_NORMAL_HINTS 里
   min == max == 启动时尺寸）。屏幕旋转后 Mutter 无法按新方向调整窗口，
   于是屏幕已竖屏、应用仍是横屏 960x600。实测日志：
       [10:41:29] 尺寸事件: 960x600 (期望 600x960)  <-- 偏离屏幕尺寸
   → **不要**设 set_resizable(False)；改为监听显示器变化并主动跟随。

5) ★ 全屏与 chrome 的真实关系（这条曾经推断错，务必看完）★
   GNOME 的 layout.js 里，软键盘与顶栏的挂载方式和参数**并不一样**：

       const defaultParams = { trackFullscreen: false, affectsStruts: false,
                               affectsInputRegion: true };

       this.panelBox = new St.BoxLayout({ name: 'panelBox', ... });
       this.addChrome(this.panelBox, {
           affectsStruts: true,
           trackFullscreen: true,          // ← 顶栏：会被全屏隐藏
       });

       this.keyboardBox = new St.BoxLayout({ name: 'keyboardBox', ... });
       this.addTopChrome(this.keyboardBox);   // ← 软键盘：没传参数
                                              //    => trackFullscreen = false

   addTopChrome/addChrome 的 doc 原文：
       "If trackFullscreen is true, the actor's visibility will be bound to
        the presence of fullscreen windows on the same monitor
        (it will be hidden whenever a fullscreen window is visible)"
   而 _updateActorVisibility() 对 trackFullscreen 为 false 的 actor 直接 return。

   ⇒ **「全屏会让 GNOME 藏掉软键盘」是错的**（那只对顶栏 panelBox 成立）。
     而且 addTopChrome 把 keyboardBox 加在 uiGroup 最末尾，
     层级高于 top_window_group（全屏窗口所在层），所以窗口也盖不住它。
     不要再基于"全屏会藏键盘"这条错误结论做任何设计。

   ★ 那为什么最终仍必须用**铺满屏幕的普通窗口**而不是 fullscreen()？★
   有两个理由，第二个是决定性的：

   (a) 几何：fullscreen 窗口在 Mutter 里进 top_window_group，顶栏随之被隐藏
       却留下一个 27px 的 strut（_NET_WORKAREA 从 y=54 起），而 strut 不会
       因 actor 隐藏而消失（layout.js 注释："Changes to @actor's visibility
       will NOT affect whether or not the strut is present"）。普通窗口在顶栏
       被扩展移出屏幕、strut 归零后，能干净地占满 960x600。

   (b) ★ 合成：全屏窗口会被 Mutter **unredirect** ★
       —— 绕过合成器、把窗口直接送到扫描输出。一旦 unredirect，
       GNOME Shell 画在最上层的软键盘（keyboardBox）就**根本没有机会被
       合成上去**。症状极具迷惑性：
           Main.keyboard.visible == true
           actor 的 mapped / opacity / 几何全部正常
           屏幕上却什么都看不到，而且**时有时无**
       （unredirect 的启停取决于当时的窗口状况，所以是间歇性的，
        极容易被误判成"测量误差"或"被窗口遮挡"）。
       本机实测：xprop 里同时出现 _NET_WM_STATE_MAXIMIZED_* 与
       _NET_WM_STATE_FULLSCREEN，**而本文件从未调用过 fullscreen()** ——
       来源是 org.gnome.mutter auto-maximize（Mutter 会自动最大化
       "比工作区大"的窗口，并进一步让它带上全屏状态）。
       对策见 _apply_geometry()：铺满后主动 unfullscreen() 兜底，
       并把 auto-maximize 关掉（harden_kiosk.sh 已固化该设置）。

6) **X11 下 GNOME 不会给外部应用自动弹软键盘**。GNOME 42 只有两条弹出通路：
   - gnome-shell 自己的 Clutter.Text 获得焦点（外部应用走不到）；
   - 输入法上报 panel-state=ON，而那是 Wayland text-input 协议才有的东西。
   底部上滑手势能用，但 EdgeDragAction 设了 set_n_touch_points(1)，
   只认真实触摸点，无法用指针事件模拟。
   → 走 GNOME Shell 扩展 elevator-osk@local 暴露的 D-Bus 显式开关。

7) ★ **「键盘弹出后一会就消失」是我们自己造成的（本文件最重要的一条）** ★
   键盘弹出前后窗口会经历焦点变化，WebKit 因此对当前输入框触发 focusout。
   我原先在页面的 focusout 里用 document.hasFocus() 做守卫来判断
   "用户是否真的离开了输入框" —— **这个值在窗口失焦时并不可靠，实测误判**，
   于是我们发出 Hide() 把键盘关掉；键盘一关窗口又拿回焦点、触发 focusin、
   再 Show() …… 这条自激振荡表现出来就是「弹出一会就消失」。
   实测日志（每 3~7 秒一轮）：
       [11:13:46] 输入框失焦 -> 收起软键盘
       [11:13:53] 输入框获得焦点 -> 呼出软键盘
       [11:13:56] 输入框失焦 -> 收起软键盘
       [11:13:57] 输入框获得焦点 -> 呼出软键盘
   → **只信 GTK 侧的权威焦点状态**（Gdk.WindowState.FOCUSED，见 _window_focused）。
     窗口根本没焦点时收到的 blur 一律忽略，绝不收键盘。
   → 同时**不要用"看门狗定期补弹"去掩盖它**：那只是把振荡周期拉长，
     反而让 GNOME 的弹出/收起动画互相打断，是治标不治本。
     另注：_onKeyFocusChanged 确实会在 stage key focus 不是 Clutter.Text 时
     close()，但那只在 shell 自身焦点变化时触发，不是本项目的主要矛盾。

用法:
    elevator_app.py [url]
"""
import os
import sys
from datetime import datetime

import gi

# 版本必须全部显式锁定；Gdk 不能排在 Gtk 前导入，否则未锁版本的 Gdk 会解析到
# 已装的 4.0，随后 Gtk 3.0 再要 Gdk 3.0 就冲突。
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("WebKit2", "4.0")
from gi.repository import Gdk, Gio, GLib, Gtk, WebKit2  # noqa: E402

APP_NAME = "电梯安全评估系统"
APP_ID = "elevator-assessment"
APP_DBUS_ID = "org.gdsei.elevator-assessment"
DEFAULT_URL = "http://127.0.0.1:8081/"
LOG_PATH = os.path.expanduser("~/.elevator-app.log")
VERIFY_MS = 900
# 几何校验：显示器变化 / 尺寸偏离后，等布局稳定再纠正
GEOMETRY_SETTLE_MS = 600
GEOMETRY_RETRY_MAX = 6

# 软键盘桥（GNOME Shell 扩展 elevator-osk@local 提供）
OSK_NAME = "org.gdsei.ElevatorOsk"
OSK_PATH = "/org/gdsei/ElevatorOsk"
OSK_IFACE = "org.gdsei.ElevatorOsk"

# 注入到每个页面的焦点探针：输入框获得/失去焦点时通知原生侧。
# 软键盘的弹出时机由原生侧掌握，前端无需任何改动。
KBD_PROBE_JS = """
(function () {
  if (window.__elevatorKbdHooked) { return; }
  window.__elevatorKbdHooked = true;

  var hideId = 0;
  function post(v) {
    try { window.webkit.messageHandlers.elevatorKbd.postMessage(v); } catch (e) {}
  }
  function isText(t) {
    if (!t || !t.tagName) { return false; }
    var n = t.tagName.toUpperCase();
    return n === 'INPUT' || n === 'TEXTAREA' || t.isContentEditable === true;
  }

  // ★ 让聚焦的输入框停在软键盘之上 ★
  //
  // fcitx5 的候选窗跟随光标、默认出现在光标**下方**；而 GNOME 软键盘是
  // 覆盖在应用之上的 overlay（约占屏幕下方 28%），fcitx5 并不知道这块被占了
  // —— 于是靠下的输入框，中文候选窗会落到键盘底下看不见（实测复现）。
  // fcitx5 没有"把候选窗放到光标上方"的配置项，所以在这里把输入框滚到
  // 安全区内，为候选窗腾出空间。
  // 用 scrollIntoView({block:'center'}) 而不是直接算像素：它对
  // "谁才是真正的滚动容器"不敏感，页面结构变了也不会失效。
  var SAFE_BOTTOM_RATIO = 0.6;   // 键盘上沿约在 0.72 处
  function keepAboveKeyboard(el) {
    try {
      var r = el.getBoundingClientRect();
      var vh = window.innerHeight || document.documentElement.clientHeight || 0;
      if (vh <= 0) { return false; }
      if (r.bottom > vh * SAFE_BOTTOM_RATIO || r.top < 12) {
        el.scrollIntoView({ block: 'center', inline: 'nearest' });
        return true;
      }
    } catch (e) {}
    return false;
  }

  var refocusing = null;   // 正在为刷新光标框而重新聚焦的元素

  document.addEventListener('focusin', function (e) {
    if (!isText(e.target)) { return; }
    if (hideId) { clearTimeout(hideId); hideId = 0; }
    if (refocusing === e.target) {
      // 这次 focusin 是我们自己重新聚焦触发的，不要再滚/再聚焦，否则死循环
      refocusing = null;
      post('show');
      return;
    }
    post('show');
    var el = e.target;
    // 键盘是滑入的（约 250ms），等它到位后再校正
    setTimeout(function () {
      if (!keepAboveKeyboard(el)) { return; }
      // ★ 滚动之后必须让 WebKit 重新上报光标框 ★
      //
      // 实测：WebKit 只在输入框**获得焦点那一刻**上报一次光标位置，
      // 之后页面滚动、甚至继续打字都不会更新它。fcitx5 就是拿这个坐标
      // 决定候选窗位置的 —— 所以只把输入框滚上去是没用的，
      // 候选窗仍然停在滚动前的旧坐标（= 被软键盘挡住的那个位置）。
      //
      // 重新聚焦一次会让输入上下文重建，WebKit 随即按**新位置**上报，
      // fcitx5 也就把候选窗挪到光标下方了。
      // blur→focus 只隔 30ms，focusout 的收起键盘有 250ms 防抖，
      // 会被紧接着的 focusin 取消，所以键盘不会闪。
      refocusing = el;
      try { el.blur(); } catch (err) {}
      setTimeout(function () { try { el.focus(); } catch (err) {} }, 30);
    }, 380);
  }, true);

  document.addEventListener('focusout', function (e) {
    if (!isText(e.target)) { return; }
    // 输入框之间切换时 focusout 会先于下一个 focusin 触发，
    // 稍作延迟避免键盘闪一下
    if (hideId) { clearTimeout(hideId); }
    hideId = setTimeout(function () {
      hideId = 0;
      // ★ 关键：必须区分「用户离开了输入框」和「窗口被软键盘抢走了焦点」★
      //
      // 软键盘弹出时窗口会失去焦点，浏览器会因此对当前输入框触发 focusout。
      // 如果这时去收起键盘，键盘一关窗口又拿回焦点、触发 focusin、又弹出键盘，
      // 就成了 2 秒一轮的自激振荡（实测出现过）。
      // 这两种情况都不能收起：
      //   - 焦点只是落到了另一个输入框；
      //   - 整个文档都失去焦点了（软键盘/窗口切换导致）。
      var ae = document.activeElement;
      if (isText(ae)) { return; }
      if (!document.hasFocus()) { return; }
      post('hide');
    }, 250);
  }, true);

  // F5 刷新：WebKit 会把按键事件消费掉，Gtk.Window 的 key-press-event 收不到
  // （实测按键能到达页面本身，所以在这里监听是可靠的）。
  document.addEventListener('keydown', function (e) {
    if (e.key === 'F5') { e.preventDefault(); post('reload'); }
  }, true);


  // 吃掉 WebKit 的右键/长按菜单。
  // 一体机是触摸屏，长按输入框既是呼出软键盘的常规手势，又会弹出编辑菜单
  // （剪切/复制/粘贴）或导航菜单（后退/刷新），挡住大半个界面。
  // 注意：原生侧 connect("context-menu", -> True) 这道**实测不够**
  // （编辑菜单消失后仍会换成导航菜单），必须在 DOM 层 preventDefault。
  document.addEventListener('contextmenu', function (e) {
    e.preventDefault();
    e.stopPropagation();
    return false;
  }, true);
})();
"""


def log(msg: str) -> None:
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (datetime.now().strftime("%F %T"), msg))
    except OSError:
        pass


class ElevatorWindow(Gtk.ApplicationWindow):
    def __init__(self, application, url: str):
        super().__init__(application=application, title=APP_NAME)
        self._requested = False
        self._geometry_id = 0
        self._geometry_tries = 0
        self._geometry_why = ""
        self._tried_maximize = False
        self._last_cfg = None

        # 让 GNOME 把这个窗口归到我们的应用名下（而不是 Chromium）
        GLib.set_prgname(APP_ID)
        GLib.set_application_name(APP_NAME)
        self.set_wmclass(APP_ID, APP_ID)

        # 无边框：一体机不该出现标题栏/边框
        self.set_decorated(False)
        # ★ 不能 set_resizable(False) ★ 见文件头第 4 条
        # 不用 fullscreen() 而用"铺满屏幕的普通窗口"，理由见文件头第 5 条
        # （是几何取舍，不是"全屏会藏键盘"——那条推断已被推翻）

        _w, _h, _ = self._expected_size()
        self.set_default_size(_w, _h)

        self.connect("delete-event", lambda *_: True)   # 误触不关窗
        # F5 的实际生效路径在页面内（见 KBD_PROBE_JS）；这里留一道
        # 窗口级监听作为兜底 —— WebKit 正常会把按键消费掉，所以它通常收不到。
        self.connect("key-press-event", self._on_key)
        self.connect("map-event", self._on_map)
        self.connect("window-state-event", self._on_state_change)
        self.connect("configure-event", self._on_configure)

        # ★ 旋转自适应 ★：显示器几何一变就跟着走
        screen = self.get_screen()
        screen.connect("monitors-changed", self._on_monitors_changed)
        screen.connect("size-changed", self._on_monitors_changed)

        # ★ 尽快盖住桌面：先显示纯色窗口，WebView 稍后再建 ★
        #
        # WebKit 的首次初始化很贵 —— 实测从不进程启动到窗口映射要 4 秒
        # （要起 WebKitWebProcess / 网络进程 / GPU 进程）。
        # 如果等 WebView 构造完再 show_all()，这 4 秒里屏幕上还是 GNOME 桌面，
        # 开机就会明显看到"桌面闪一下再被应用盖住"。
        #
        # 这里先把窗口本身显示出来并涂成 #10365f（与登录页/启动页渐变的起始色
        # 一致，harden_kiosk.sh 也会把桌面壁纸设成同一个色），
        # 于是从桌面到应用的过渡在视觉上是无缝的；
        # WebView 随后在 idle 里补上，用户看到的就是启动页淡入。
        self.set_app_paintable(True)
        rgba = Gdk.RGBA()
        rgba.parse("#10365f")
        self.override_background_color(Gtk.StateFlags.NORMAL, rgba)
        self._webview_url = url
        self.show_all()
        GLib.idle_add(self._build_webview)

    # ── 延迟构建 WebView（把最贵的初始化挪出开机可见路径）────────
    def _build_webview(self):
        # 页面里的输入框焦点探针 -> Python
        self._ucm = WebKit2.UserContentManager()
        self._ucm.register_script_message_handler("elevatorKbd")
        self._ucm.connect("script-message-received::elevatorKbd", self._on_kbd_message)
        self._ucm.add_script(WebKit2.UserScript.new(
            KBD_PROBE_JS,
            WebKit2.UserContentInjectedFrames.TOP_FRAME,
            WebKit2.UserScriptInjectionTime.END,
            None, None))

        self.webview = WebKit2.WebView.new_with_user_content_manager(self._ucm)
        self.webview.get_settings().set_property("enable-developer-extras", False)
        # 触摸屏上长按输入框会**同时**触发 GNOME 软键盘和 WebKit 的编辑菜单
        # （剪切/复制/粘贴/全选…），菜单会挡住大半个界面。
        # 而长按恰恰是本机呼出键盘的常规手势，所以必须吃掉这个事件。
        try:
            self.webview.connect("context-menu", self._on_context_menu)
        except TypeError as e:
            log("无法连接 context-menu 信号：%s" % e)
        self.add(self.webview)
        self.webview.show()
        # ★ 必须主动把键盘焦点交给 WebView ★
        # 否则 GTK 的焦点停在窗口本身、没有落到 WebView 控件上，
        # 用户看到的症状是「第一次点击输入框没反应、要点第二次」——
        # 因为第一次点击只是把控件焦点给过去、被吞掉了（实测：
        # 第 1 次点击日志无任何反应，第 2 次才出现「输入框获得焦点」）。
        # 键盘事件同理，Tab 之类在拿到控件焦点前根本到不了页面。
        self.webview.grab_focus()
        log("WebView 已构建，开始加载页面")
        self.webview.load_uri(self._webview_url)
        return False

    # ── 铺满屏幕（注意：不是全屏状态）────────────────────────
    def _on_map(self, *_a):
        if self._requested:
            return False
        self._requested = True
        log("窗口已映射，开始铺满屏幕")
        self._apply_geometry("初始铺满")
        # 窗口映射后 GTK 会把焦点给窗口本身；这里再补几次，确保它落到
        # WebView 上（WebView 可能比窗口晚构建，见 _build_webview）。
        for delay in (200, 800, 2000):
            GLib.timeout_add(delay, self._grab_focus)
        GLib.timeout_add(VERIFY_MS, self._verify)
        return False

    def _grab_focus(self):
        """把键盘焦点交给 WebView（幂等，可重复调用）。"""
        view = getattr(self, "webview", None)
        if view is None:
            return False
        try:
            if not view.has_focus():
                view.grab_focus()
        except Exception:
            pass
        return False

    def _expected_size(self):
        """期望的窗口尺寸（GTK 逻辑像素）。

        get_monitor_geometry() 返回的**已经是应用像素（逻辑像素）**，
        本机 1920x1200 物理 / scale=2 = 960x600，它就直接返回 960x600。
        千万不要再除一次 scale —— 那会算成 480x300，导致把已经正确的
        窗口误判为失败并"兜底"改坏（实测踩过）。
        """
        screen = self.get_screen()
        geo = screen.get_monitor_geometry(screen.get_primary_monitor())
        return geo.width, geo.height, (self.get_scale_factor() or 1)

    def _apply_geometry(self, why: str):
        ew, eh, scale = self._expected_size()
        log("%s：move(0,0) + resize(%dx%d) (scale=%d)" % (why, ew, eh, scale))
        self.resize(ew, eh)
        self.move(0, 0)
        # ★ 不要 set_keep_above(True) ★
        # 它会给窗口加上 _NET_WM_STATE_ABOVE，把窗口提到 Mutter 的 TOP 层。
        # 一体机上本来就没有别的窗口要压，不需要它，少一个变量。
        #
        # ★ 必须主动取消全屏 ★
        # 本机 org.gnome.mutter auto-maximize = true，Mutter 会把「比工作区大」
        # 的窗口自动最大化，并在某些情形下进一步让它带上
        # _NET_WM_STATE_FULLSCREEN（实测：xprop 里 MAXIMIZED_* 与 FULLSCREEN 同时存在，
        # 而本文件从未调用过 fullscreen()）。
        #
        # 危害是决定性的：全屏窗口会被 Mutter **unredirect**（绕过合成器、
        # 直接送到扫描输出）。一旦 unredirect，GNOME Shell 画在最上层的软键盘
        # 就**根本没有机会被合成上去** —— 这正是我们反复观察到的
        # 「Main.keyboard.visible = true、actor 的 mapped/opacity/几何全部正常，
        #  屏幕上却什么都看不到」。unredirect 的启停还取决于当时的窗口状况，
        # 所以这个故障是间歇性的。
        # 主动取消全屏后窗口走普通合成路径，键盘才会被画出来。
        self.unfullscreen()
        self.present()
        # present() 之后 GTK 可能又把焦点给了窗口本身，补一次
        self._grab_focus()

    def _verify(self):
        win = self.get_window()
        if win is None:
            log("校验：GdkWindow 为空")
            return False
        ew, eh, _ = self._expected_size()
        w, h = win.get_width(), win.get_height()
        if (w, h) == (ew, eh):
            log("铺满生效（几何 %dx%d 与显示器一致）" % (w, h))
        else:
            log("铺满未达预期：几何 %dx%d，期望 %dx%d" % (w, h, ew, eh))
            self._schedule_geometry_sync("初始校验")
        return False

    # ── 旋转 / 分辨率自适应 ─────────────────────────────────
    def _on_monitors_changed(self, _screen):
        ew, eh, scale = self._expected_size()
        log("显示器变化：期望 %dx%d (scale=%d)" % (ew, eh, scale))
        self.set_default_size(ew, eh)     # 兜底尺寸必须跟着新方向走
        self._tried_maximize = False      # 新方向下允许再试一次最大化
        self._schedule_geometry_sync("显示器变化")
        return False

    def _schedule_geometry_sync(self, why: str):
        self._geometry_why = why
        if self._geometry_id:
            GLib.source_remove(self._geometry_id)
        self._geometry_id = GLib.timeout_add(GEOMETRY_SETTLE_MS, self._do_geometry_sync)

    def _do_geometry_sync(self):
        self._geometry_id = 0
        win = self.get_window()
        if win is None or not self._requested:
            return False
        ew, eh, _ = self._expected_size()
        cur = (win.get_width(), win.get_height())
        if cur == (ew, eh):
            self._geometry_tries = 0
            return False

        if self._geometry_tries < GEOMETRY_RETRY_MAX:
            self._geometry_tries += 1
            log("%s：几何 %dx%d 偏离期望 %dx%d，重新铺满（第 %d 次）"
                % (self._geometry_why, cur[0], cur[1], ew, eh, self._geometry_tries))
            self._apply_geometry(self._geometry_why)
            self._schedule_geometry_sync(self._geometry_why)
            return False

        # 反复 resize 都不认，就换最大化 —— 顶栏若未被扩展隐藏，
        # 工作区会比屏幕矮一截，此时最大化也拿不到满屏，只能记录后放弃，
        # 绝不做无限对抗。
        if not self._tried_maximize:
            self._tried_maximize = True
            self._geometry_tries = 0
            log("%s：resize 无效，改试 maximize()" % self._geometry_why)
            self.maximize()
            self._schedule_geometry_sync(self._geometry_why)
            return False

        log("%s：几何 %dx%d 始终无法达到 %dx%d，停止重试"
            "（顶栏可能未被 elevator-osk@local 隐藏）"
            % (self._geometry_why, cur[0], cur[1], ew, eh))
        return False

    def _on_configure(self, _widget, event):
        ew, eh, _ = self._expected_size()
        key = (event.width, event.height, ew, eh)
        if key != self._last_cfg:            # 去掉连续重复，日志才有用
            self._last_cfg = key
            mark = "" if (event.width, event.height) == (ew, eh) else "   <-- 偏离屏幕尺寸"
            log("尺寸事件: %dx%d (期望 %dx%d)%s"
                % (event.width, event.height, ew, eh, mark))
        return False

    def _on_state_change(self, _widget, event):
        # 这里只记录。出现 FULLSCREEN 并不是错误（见文件头第 5 条：
        # 软键盘不会被全屏隐藏，只有顶栏会），但会让窗口交给 Mutter
        # 按全屏规则摆放，所以仍值得留痕。
        st = int(event.new_window_state)
        full = bool(event.new_window_state & Gdk.WindowState.FULLSCREEN)
        log("状态事件: %d  FULLSCREEN=%s%s"
            % (st, full, "   <-- 窗口被当作全屏窗口" if full else ""))
        return False

    def _on_key(self, _w, event):
        if event.keyval == 0xFFC5:      # F5 供运维刷新
            self.webview.reload()
            return True
        return False

    def _on_context_menu(self, _view, _menu, _hit):
        """吃掉 WebKit 的右键/长按菜单（第二道防线）。

        真正生效的是页面里那道 DOM 监听（见 KBD_PROBE_JS 的 contextmenu），
        因为本版本实测：只靠这里返回 True，编辑菜单会消失但会换成
        导航菜单（后退/刷新），仍然挡界面。留着它作为兜底。
        """
        return True

    # ── 软键盘桥 ────────────────────────────────────────────
    def _on_kbd_message(self, _mgr, js_result):
        try:
            val = js_result.get_js_value().to_string()
        except Exception:
            val = ""
        if val == "show":
            log("输入框获得焦点 -> 呼出软键盘")
            self._osk_call("Show")
        elif val == "hide":
            # ★ 权威判据在 GTK 侧，不看页面自报的状态 ★
            #
            # 软键盘是 GNOME Shell 的 actor。它弹出前后，应用窗口会经历
            # 焦点变化，WebKit 会因此对当前输入框触发 focusout。
            # 页面侧的 document.hasFocus() 在这种情形下并不可靠（实测会
            # 误判成"用户离开了输入框"），于是我们发出 Hide() 把键盘关掉，
            # 键盘一关窗口又拿回焦点、触发 focusin、再 Show() ……
            # 这条自激振荡表现出来就是「键盘弹出后一会就消失」。
            #
            # 只要 GTK 认为窗口根本没有焦点，这次 blur 就一定是窗口失焦
            # 引起的，与用户的意图无关 —— 此时绝不能收键盘。
            if not self._window_focused():
                log("窗口未获焦点引起的 blur，忽略（不收键盘）")
                return False
            log("输入框失焦 -> 收起软键盘")
            self._osk_call("Hide")
        elif val == "reload":
            log("收到 F5，刷新页面")
            self.webview.reload()
        return False

    def _window_focused(self) -> bool:
        """GTK 侧的权威焦点状态。

        绝不用页面的 document.hasFocus() 做这个判断 —— 实测它会误判，
        进而把软键盘关掉，形成自激振荡。
        """
        win = self.get_window()
        if win is None:
            return False
        try:
            return bool(win.get_state() & Gdk.WindowState.FOCUSED)
        except Exception:
            return False

    def _osk_call(self, method: str, on_reply=None):
        """调用 GNOME Shell 扩展的软键盘开关。

        扩展没装/没启用时必须只记日志，绝不能让应用崩掉或卡住 ——
        所以用异步调用，且失败只告警。
        """
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        except GLib.Error as e:
            log("软键盘桥：会话总线不可用 (%s)" % e.message)
            return
        try:
            bus.call(OSK_NAME, OSK_PATH, OSK_IFACE, method,
                     None, None, Gio.DBusCallFlags.NONE, 2000, None,
                     self._on_osk_reply, (method, on_reply))
        except GLib.Error as e:
            log("软键盘桥：%s 派发失败 (%s)" % (method, e.message))

    def _on_osk_reply(self, bus, res, user_data):
        method, on_reply = user_data
        try:
            ret = bus.call_finish(res)
        except GLib.Error as e:
            log("软键盘桥：%s 失败 (%s) —— 扩展 elevator-osk@local 是否已启用？"
                % (method, e.message))
            return
        if on_reply is not None:
            try:
                on_reply(bool(ret.unpack()[0]))
            except Exception as e:
                log("软键盘桥：%s 回包解析失败 (%r)" % (method, e))


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL

    log("=== 启动 (pid=%d) url=%s ===" % (os.getpid(), url))
    app = Gtk.Application(application_id=APP_DBUS_ID,
                          flags=Gio.ApplicationFlags.FLAGS_NONE)

    def on_activate(_app):
        win = ElevatorWindow(app, url)
        win.show_all()

    app.connect("activate", on_activate)
    try:
        return app.run([])
    finally:
        log("=== 退出 ===")


if __name__ == "__main__":
    sys.exit(main())
