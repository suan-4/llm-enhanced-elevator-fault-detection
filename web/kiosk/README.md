# 板端一体机（Kiosk）模式

让 RK3588 板端**开机直接进入电梯安全评估系统**，看不到也退不出系统桌面（方案 A）。
需要维护时用界面上的「退出系统」按钮返回桌面；桌面上的快捷方式可再次启动。

当前形态是 **GTK3 + WebKit2GTK 原生窗口**（不是 Chromium），板端已预装
`libwebkit2gtk-4.0-37` / `gir1.2-webkit2-4.0` / `python3-gi`，**零新增依赖**。
Chromium 启动器 `elevator-kiosk.sh` 仍保留作为备用路径。

## 使用方式

| 场景 | 操作 |
|---|---|
| 开机 | 自动全屏进入系统，桌面不可见 |
| **退出到桌面** | 点 **「退出系统」** 按钮（有二次确认）。**登录页在卡片右上角有个 ×，主界面在侧边栏** |
| **重新启动应用** | 双击桌面上的 **「电梯安全评估系统」** 图标 |
| 运维刷新 | 按 **F5** 刷新页面 |
| 运维应急 | Ctrl+Alt+F3 切到文本控制台（不受快捷键加固影响，仍可 adb/ssh） |
| 临时停用 | 删掉 autostart 里的 elevator-kiosk.desktop |

### 为什么登录页也要有退出按钮

如果账号丢失、后端异常或界面卡住，用户连登录都进不去 —— 那时最需要退回桌面的出口。
所以 **`/api/kiosk/status` 与 `/api/kiosk/exit` 都不要求登录**。

安全边界改用「**仅允许本机调用**」：一体机就运行在板子上，请求来自 127.0.0.1；
局域网内其他机器即使知道接口也无效：

| 调用方 | status | exit |
|---|---|---|
| 板端本机 (127.0.0.1) | local=true → 按钮显示 | 可用 |
| 局域网远程 | local=false → 按钮隐藏 | **403 仅允许在本机操作** |

后端可用 `KIOSK_EXIT_ENABLED=false` 整体关闭该功能。

## 屏幕旋转自适应

面板是 1200×1920 的竖屏，默认由 GNOME 旋转成横屏 1920×1200 使用
（Mutter scale=2，逻辑视口 960×600）。**陀螺仪会自动旋转**，应用必须跟着走。

### 曾经的 bug：屏幕转了，应用还是横屏

根因是 `Gtk.Window.set_resizable(False)`。它会给窗口打上
**min == max** 的 `WM_NORMAL_HINTS`，把尺寸钉死在启动时的横屏尺寸上，
屏幕旋转后 Mutter 无法按竖屏重新布局。实测日志：

```
[10:41:29] 尺寸事件: 960x600 (期望 600x960)   <-- 偏离屏幕尺寸
```

修复后 `WM_NORMAL_HINTS` 变为 `minimum size: 0 by 0`、无 maximum，Mutter 可自由重排。

### 修复方式（两道保险）

1. **不再设 `set_resizable(False)`** —— 无边框窗口本来就没有可拖拽的边框，
   不需要靠它防拖拽。
2. **监听 `Gdk.Screen::monitors-changed` / `size-changed`**：几何一变就
   同步 `set_default_size()`（兜底尺寸必须跟着新方向走），并在 600ms 后校验
   窗口几何；若 Mutter 没跟上，就 `unfullscreen → resize → fullscreen` 强制对齐
   （最多重试 8 次，且软键盘活跃期间会让路）。

前端配套补了竖屏媒体查询 `@media (orientation: portrait), (max-width: 820px)`：
侧边栏 260px → 186px、两列表单收成单列、正文内边距收窄。
此前**完全没有媒体查询**，竖屏下侧边栏 260px 会把 600px 宽的正文挤成 340px。

### 竖屏侧边栏：用户栏按钮必须排成两行

侧边栏底部的「改密 / 用户 / 注销 / 退出系统」在 186px 宽下约需 210px，
原来靠 `.u-act{flex-shrink:0}` 锁死宽度，永远不会换行 → 最后一个按钮被裁掉。

改法是用 flex + 显式 basis 强行两行：

```css
.user-bar{flex-direction:column;align-items:stretch;gap:8px;padding:10px 14px}
.user-bar .u-act{display:flex;flex-wrap:wrap;gap:6px;flex-shrink:1;min-width:0}
.user-bar button{flex:1 1 calc(50% - 3px);min-width:0;padding:6px 4px;font-size:.66rem}
```

> ⚠️ **不要用 `display:grid` 来实现两行**，这里踩过坑：
> grid + 默认 `align-self:stretch` 的项 + 按钮上的 `overflow:hidden`
> （它会改变 `min-height:auto` 的解析）三者叠加，会让 auto 行高与拉伸项
> 互相推导，实测得到 `grid-template-rows = "450.5px 450.5px"`
> —— 而网格盒只有 70px 高。按钮被拉成 451px，文字被挤出屏幕、还盖到页脚上。
> 排 CSS 问题时**必须看实测数值**，目测截图会被缩放和直觉带偏。
> 当时的定位手段：注入一段 F9 监听把 `getBoundingClientRect()` 与
> `getComputedStyle()` 回传到应用日志（排查完已删除）。

## 软键盘（重点：X11 下必须自己桥）

**GNOME 42 在 X11 会话里不会给外部应用自动弹软键盘**，原因有两条，都实测确认过：

- `keyboard.js` 的 `_onKeyFocusChanged` 只在 `global.stage.key_focus instanceof Clutter.Text`
  时自动 `open()` —— 那是 gnome-shell **自己**的输入框，外部应用走不到；
- 另一条通路是输入法上报 `panel-state = Clutter.InputPanelState.ON`，
  而 `Main.inputMethod` 是 IBus 封装，这条路只在 **Wayland 的 text-input 协议**下才成立。
  本机是 X11 + fcitx5，根本不会收到 ON。

底部上滑手势能用，但 `EdgeDragAction` 设了 `set_n_touch_points(1)`，
**只认真实触摸点**，无法用 XTest/指针事件模拟。
`org.gnome.Shell.Eval` 也被 `global.context.unsafe_mode` 挡住（该开关只能在
Looking Glass 里人工打开），且 GNOME 42 没有「切换屏幕键盘」的快捷键。

### 方案：GNOME Shell 扩展 `elevator-osk@local`

把 `Main.keyboard.open()/close()` 通过 D-Bus 暴露出来：

| 方法 | 作用 |
|---|---|
| `org.gdsei.ElevatorOsk.Show()` | 弹出软键盘 |
| `org.gdsei.ElevatorOsk.Hide()` | 收起软键盘 |
| `org.gdsei.ElevatorOsk.State()` | 返回键盘当前是否可见 |

原生应用通过 `WebKit2.UserContentManager` 往每个页面注入一段焦点探针
（**前端 HTML 无需任何改动**），在 `focusin` / `focusout`（250ms 防抖）时
通知 Python 侧调用上述 D-Bus。扩展是热加载的，`enabled-extensions` 一变即生效，
**不需要注销或重启**。

### bug 一：键盘弹出后被我们自己顶掉

早期逻辑是「丢失全屏就 2 秒后 `fullscreen() + present()` 拉回」。
软键盘弹出会引发窗口焦点变化，于是我们 2 秒后 `present()` 抢走焦点，
把刚弹出的键盘顶掉，形成死循环。实测日志：

```
[10:44:32] 状态事件: FULLSCREEN=False   ← 键盘弹出引发焦点变化
[10:44:35] 交互已停止，重新拉回全屏      ← present() 抢走焦点
[10:44:36] 状态事件: FULLSCREEN=False   ← 键盘又被顶掉
[10:44:39] 交互已停止，重新拉回全屏
```

修复：软键盘活跃期间**禁止重新全屏、禁止 `present()`**。

### bug 二：键盘弹出后一会就消失（真凶）

键盘弹出前后，窗口会经历焦点变化，WebKit 因此对当前输入框触发 `focusout`。
页面里的守卫用 `document.hasFocus()` 判断「用户是否真的离开了输入框」——
**这个值在窗口失焦时并不可靠，实测会误判**，于是应用发出 `Hide()` 把键盘关掉；
键盘一关窗口又拿回焦点、触发 `focusin`、再 `Show()`……形成自激振荡：

```
[11:13:46] 输入框失焦 -> 收起软键盘
[11:13:53] 输入框获得焦点 -> 呼出软键盘
[11:13:56] 输入框失焦 -> 收起软键盘
[11:13:57] 输入框获得焦点 -> 呼出软键盘
```

修复：**判据换成 GTK 侧的权威焦点状态**（`Gdk.WindowState.FOCUSED`，见
`_window_focused()`）。窗口根本没焦点时收到的 blur 一律忽略，绝不收键盘。

> ⚠️ **不要再用「看门狗定期补弹」去掩盖这个问题。**
> 那只是把振荡周期拉长，还会让 GNOME 的弹出/收起动画互相打断，治标不治本。

### bug 三（真正的主因）：键盘"状态正常、几何正常，但就是看不见"

这个 bug 折磨了很久，因为它**时有时无**，而且所有可查的指标都是对的：

| 指标 | 值 |
|---|---|
| `Main.keyboard.visible` | `true` |
| `keyboardBox` 的 visible / mapped / opacity | `true` / `true` / `255` |
| `keyboardBox` 几何 | y=1920 h=531，actor `translation_y=-531` → 正好落在屏幕下三分之一 |

**根因：Mutter 的 unredirect。**

全屏窗口会被 Mutter **unredirect**（绕过合成器、直接送到扫描输出）。
一旦 unredirect，GNOME Shell 画在最上层的软键盘（`keyboardBox`，用
`addTopChrome` 挂在 `uiGroup` 最末尾，层级高于所有窗口）就**根本没有
机会被合成上去**。unredirect 的启停取决于当时的窗口状况，所以故障是
**间歇性**的 —— 极容易被误判成"截图时机不对"或"被窗口遮挡"。

**而窗口为什么会全屏？**本文件从未调用 `fullscreen()`，但 `xprop` 里
同时存在 `_NET_WM_STATE_MAXIMIZED_*` 与 `_NET_WM_STATE_FULLSCREEN`：

    org.gnome.mutter auto-maximize = true

Mutter 会把「比工作区大」的窗口**自动最大化**，并在某些情形下进一步让它
带上全屏状态。这就是全屏状态的来源。

**修复（两道）：**

1. `gsettings set org.gnome.mutter auto-maximize false`
   —— 已固化进 `harden_kiosk.sh`，重装/重启都不会丢。
2. 应用在铺满屏幕后**主动** `unfullscreen()` 兜底（见 `_apply_geometry()`）。

修复后 `_NET_WM_STATE` 只剩 `_NET_WM_STATE_FOCUSED`，键盘随即正常绘制。
实测（重启后）：

| 场景 | `State()` | 截图 |
|---|---|---|
| 开机进入登录页 | true，15 秒稳定 | 键盘可见 |
| 点背景 | false | 键盘消失 |
| 点输入框 | true | 键盘出现 |

### 一条被推翻的推断（留档，避免重犯）

曾经推断「全屏会让 GNOME 藏掉软键盘」，并据此把应用改成非全屏窗口。
**这条是错的。** 读 `layout.js` 可见两者参数并不一样：

```js
const defaultParams = { trackFullscreen: false, affectsStruts: false,
                        affectsInputRegion: true };

this.panelBox = new St.BoxLayout({...});
this.addChrome(this.panelBox, { affectsStruts: true,
                                trackFullscreen: true });  // 顶栏：会被全屏隐藏

this.keyboardBox = new St.BoxLayout({...});
this.addTopChrome(this.keyboardBox);   // 软键盘：没传参数 => trackFullscreen = false
```

`_updateActorVisibility()` 对 `trackFullscreen` 为 `false` 的 actor 直接 `return`；
且 `addTopChrome` 把 `keyboardBox` 加在 `uiGroup` 最末尾，层级高于
`top_window_group`（全屏窗口所在层）——**窗口盖不住键盘，全屏也藏不掉它**。

改用非全屏窗口的真正理由与键盘无关，是**几何**：
全屏窗口在 Mutter 里进 `top_window_group`，顶栏随之被收起并留下 27px 的 strut
（layout.js 注释：`Changes to @actor's visibility will NOT affect whether or not
the strut is present`），窗口只能到 960x573；而普通窗口在顶栏被扩展移出屏幕、
strut 归零后可以干净地占满 960x600。

### 验证结果（实测）

| 场景 | `State()` |
|---|---|
| 启动（登录页 `loginUser.focus()`） | true —— 键盘自动弹出 |
| 键入 / Tab 切换输入框 | true —— 保持，不闪断（250ms 防抖生效） |
| 点击背景失焦 | false —— 正常收起 |

> 注：`State()` 只代表 GNOME 认为"键盘该在"，不等于屏幕上一定画出来了。
> 验证渲染必须截图，而且**先截图再查 State**（或同一瞬间取），
> 否则会因为查询与截图之间的时间差而误判。

## ★ 靠下的输入框，中文候选窗被软键盘挡住 ★

**症状**：在表单靠下的输入框里打拼音，fcitx5 的候选窗出现在
**很靠下甚至被软键盘盖住**的位置，看不到候选词。

**根因（最终定位）：坐标系错位 —— WebKit 报「文档坐标」，fcitx5 当「屏幕坐标」用。**

fcitx5 靠应用上报的**光标框**决定候选窗位置。把实测数字换算一下就清楚了：

- 屏幕逻辑高度 960 / 物理 1920，**scale = 2**
- 候选窗物理 y=1817 → **逻辑 y ≈ 908**
- 聚焦的输入框在**视口**里的位置是逻辑 y ≈ 480
- 页面此时的滚动量 ≈ **428**

**480 + 428 = 908** —— 分毫不差。

即 **WebKit 上报的是「视口位置 + 页面滚动量」（文档坐标），
而 fcitx5 按屏幕坐标解释**。页面每往下滚一点，候选窗就跟着往下偏一点，
滚动量足够大时（表单越长越明显）就沉到软键盘底下。
也正因为如此，**页面在顶部（滚动量=0）时候选窗位置是正确的**。

排查中排除了两个错误方向：

- **不是「fcitx5 不知道键盘占了底部」** —— 这个说法本身没错，
  但解释不了「候选窗和输入框位置对不上」；
- **不是鼠标回退** —— 把指针分别移到 (200,200)/(1000,1600)/(600,700)，
  候选窗始终钉在 `+250+1817` 不动，与指针无关。

另外 classicui 里**没有**候选窗位置策略项
（只有 OverlayOffsetX/Y、PerScreenDPI、MarginConfig 等），
fcitx5 侧无法配置，只能从应用侧解决。

### 走过的两条弯路（都失败，记录以免重蹈）

1. **聚焦后把输入框滚上去** —— 改的是输入框位置，而 fcitx5 用的是错位
   的坐标，两者一起偏，等于没改。
2. **滚完重新聚焦以刷新光标框** —— 刷新拿到的**还是文档坐标**，照样偏。

两次都是在错误的层面上打转：一直在改「输入框在哪」，
而问题在「**上报的坐标系不对**」。

### 正确的修法

**让页面不产生文档级滚动**，把滚动约束在 .main 内部
（web/index.html 的  style 末尾）：

```css
html,body{height:100%;overflow:hidden}
.main{height:100vh;overflow-y:auto;overflow-x:hidden}
```

这样 window.scrollY 恒为 0，**文档坐标与视口坐标重合**，错位消失。

- .sidebar 是 position:fixed，不受影响；
- .summary-bar 是 sticky，改为相对最近的滚动祖先 .main 吸顶，观感不变；
- .main 原有 padding/max-width 都不动，只加了高度与纵向滚动。

**验证**（滚到表单中下部后点输入框打拼音）：

| | 候选窗几何（X 实测） |
|---|---|
| 修复前 | `608x63+196+1330`、`647x63+250+1817` —— 贴住或沉到键盘（上沿 1410）底下 |
| 修复后 | **`608x63+366+614`** —— 正在聚焦输入框下方，距键盘约 800px ✓ |

修好后候选窗在截图里直接可见（1.你好 2.你 3.尼 …），
此前它被软键盘挡着，截图上根本看不到。
## ★ 启动后第一次点击「没反应」（WebView 没拿到控件焦点）★

**症状**：应用启动后（无论开机自启还是双击桌面图标），
点输入框**第一次没反应、要点第二次**；「中/英」按钮同理。
用户会描述成"点击输入框无法获得焦点、输入法切换无效"。
**只要先用鼠标在窗口里点任意一下，之后就都正常了** ——
这一条是判断本问题的关键线索（第一下只是把控件焦点给过去、被吞掉了）。

**根因**：窗口映射后 GTK 的键盘焦点停在**窗口本身**，没有落到
WebView 控件上。窗口级焦点是有的（`_NET_WM_STATE_FOCUSED`、
X 输入焦点都指向应用），所以从外部查 `xprop`/`xdotool getwindowfocus`
完全看不出问题——必须从"第一下点击是否生效"才能发现。

**实测判据**：同一个位置连点两次，日志里第 1 次无任何输出、
第 2 次才出现 `输入框获得焦点`。

**修法**（`native/elevator_app.py`）：

1. `_build_webview()` 里 `self.webview.show()` 之后 `self.webview.grab_focus()`；
2. `_on_map()` 里排三次延时补焦点（200/800/2000ms）——
   WebView 可能比窗口晚构建；
3. `_apply_geometry()` 里 `present()` 之后再补一次（present 会把焦点
   重新给回窗口本身）。

**验证**（清空会话让应用停在登录页，登录框由 JS 自动聚焦，
因此**完全不点击**也能判定）：桌面图标启动后
`fcitx=1`、键盘 `State=true`、日志出现 `输入框获得焦点` ✓
登录后单击一次输入框即出现焦点日志 ✓

## ★ 界面卡顿的真实原因：启动页的无限动画没停 ★

**症状**：界面「有一点卡顿」，但不卡死。整机空载却一直很烫/风扇转。

**实测**（top 区间采样，稳态）：

| 进程 | 修复前 | 修复后 |
|---|---|---|
| python3（应用） | 21.8% | **0.1%** |
| WebKitWebProcess | 17~18% | **0.0%** |
| Xorg | 24.6% | **0.0%** |
| gnome-shell | 23.3% | **0.0%** |

即**应用空载就持续烧掉约 66% 的一个核**，用户每次点击/滚动都要跟它抢 CPU。

**根因**：`#splash`（启动页）隐藏时只加了 `.hide`：

```css
#splash.hide{opacity:0;visibility:hidden;pointer-events:none}   /* 不是 display:none */
.splash-spin{animation:spin .8s linear infinite}                /* 无限旋转 */
```

元素**仍然留在渲染树里**，里面那个无限 `spin` 动画就一直跑，
逼着 WebKit 每帧重新合成整个页面 —— 再叠加上 Mutter 合成与 Xorg 呈现，
就成了 Xorg + gnome-shell + WebKit 三家一起空转。

**修法**：淡出结束后真正移出渲染树（`web/index.html` 的 `hideSplash()`）：

```js
s.classList.add('hide');
setTimeout(function(){ s.style.display='none'; }, 600);   // 600ms > 过渡的 450ms
```

### 教训

- **CSS 里任何 `animation: ... infinite` 都必须确认它最终会被 `display:none`
  或移除节点**，光靠 `opacity:0`/`visibility:hidden` 停不下来。
- 排查时我先用 grep 统计 `animation:` 却**漏掉了这一处**，于是把嫌疑错误地
  排除了，走了弯路。教训是：与其 grep 猜，不如做**对照实验** ——
  这次用一个最小 GTK+WebKit 窗口分别加载 `about:blank` 和真实页面
  （WebKit 2% vs 18%），一步就把问题定性了。

### 附带验证过、但**已还原**的一项

> **性质说明：这是系统层设置，不属于本项目。**
> `/etc/environment` 是**板厂固件自带**的文件，项目里没有任何脚本
> 写入或读取它（`harden_kiosk.sh` / `install_kiosk.sh` 都没碰过）。
> 下面只是**一次排查记录**：为了定位卡顿临时试过，结论是不需要，已还原。
> 换句话说 —— **本项目对系统层的改动为零**。

排查过程中曾把 `/etc/environment` 里的
`CLUTTER_PAINT=disable-dynamic-max-render-time` 注释掉试过一次。
它是**次要因素**（gnome-shell 23.3%→14.7%），主因是上面的动画。

**该改动已还原**：`/etc/environment` 现在与厂商原始文件逐字节一致
（比对基准 `/etc/environment.bak-clutter-test`，留作日后参考）。
理由：动画修掉后系统稳态已是 0.0~0.2%，那点收益已无意义，
不如保持厂商原始配置，免引入未知回归。

> 另两个变量 `MUTTER_DEBUG_ENABLE_ATOMIC_KMS=0` 与
> `MUTTER_DEBUG_FORCE_KMS_MODE=simple` **自始至终没有动过** ——
> 它们看着是板厂为这块 DSI 屏预设的，改错有黑屏风险。

## ★ 桌面图标启动会丢环境变量（输入法失效的根因）★

**症状**：点「退出系统」回到桌面后，**双击桌面图标**重新进入，
输入框点进去没有输入上下文（`fcitx5-remote` 返回 0），
「中/英」按钮点了也没反应。
而**开机自启**进入时一切正常 —— 所以这个 bug 只在走桌面图标时复现。

**根因**：两条启动路径的环境完全不同。

| | 开机自启 | 桌面图标 |
|---|---|---|
| 由谁拉起 | gnome-session | GNOME Shell(ding) → **systemd --user** |
| `GTK_IM_MODULE` | fcitx | **缺失** |
| `XMODIFIERS` | @im=fcitx | **缺失** |
| `QT_IM_MODULE` / `CLUTTER_IM_MODULE` | 有 | **缺失** |
| `GTK_MODULES` | gail:atk-bridge | **缺失** |
| `XAUTHORITY` / `XDG_CURRENT_DESKTOP` / `LC_*` | 有 | **缺失** |

（实测对比 `/proc/<pid>/environ`：桌面图标启动的进程只剩
`DBUS_SESSION_BUS_ADDRESS` 和 `XDG_RUNTIME_DIR`，并带
`INVOCATION_ID`/`SYSTEMD_EXEC_PID`，确认是 systemd 拉起的。）

GTK 找不到 `GTK_IM_MODULE` 就**不会加载 fcitx 输入法模块**，
于是应用和 fcitx5 之间根本没有建立输入上下文。

**修法**：在 `elevator-launch.sh` 里用 `${VAR:-默认值}` 显式兜底导出。
用默认值语法而不是硬赋值，是为了**环境完整时（开机自启）保留原值、不受影响**。

## 检测项不跨重启残留（重要）

### 曾经的隐患

草稿（`/api/draft`）过去同时保存 **基本信息** 和 **检测项勾选**
（`items_data`），并在每次启动时全部回填。后果是：
上一次那台电梯的合格/不合格判定会被带到下一次评估上，
看起来就像"新电梯一进来就已经评估过了"，很容易被误当成有效结果 ——
现场也确实造成过一次误判。

### 现在的策略

| 内容 | 跨重启 | 说明 |
|---|---|---|
| 基本信息（委托单位、地点、型号…） | **保留** | 填写成本高，保留是合理的 |
| 检测项合格/不合格标记 | **一律重置** | 必须针对当前这台电梯重新逐项核验 |

做法是从源头断掉：`flushDraft()` **只提交 `form_data`，不再提交 `items_data`**。
即使数据库里还留着旧版本存的 `items_data`，页面启动时也**故意不应用**
（`loadDraftFromServer()` 里显式调 `applyItemsData(null)`）。

### 「恢复默认」按钮

「评估项目」的统计条上，`生成 AI 报告` 旁边有一个 **恢复默认** 按钮，
随时可清除全部标记重来（只清检测项，不影响已填写的基本信息）。
若当前有标记会先弹确认框并带上数量。

> ⚠️ 实现上有个坑：`applyItemsData(obj)` 原本在 `if(!obj)return;` 处提前返回，
> 而 `updateSummary()` 写在它**后面** —— 于是 `applyItemsData(null)`
> （「恢复默认」正是用它）会把卡片清空、却**不更新统计数字**。
> 已改为 `if(!obj){updateSummary();return;}`。

> 注：统计里的「异常」计数按 `selected.size > 0` 统计 ——
> 只把某项标成"不合格"但没勾选具体的异常状态时，它不计入异常数。
> 这是原有设计（必须指明具体异常状态），不是 bug。

## 报告导出（Word / PDF）

评估报告区右上角有 **导出 PDF** / **导出 Word** 两个按钮，
点击后由后端生成文件并保存到 GUI 用户家目录的 `~/导出/`，
界面弹窗给出完整路径与大小。

**实现**（`backend/app/services/export_service.py`）：

    HTML --(--infilter "HTML (StarWriter)")-->  .docx   (MS Word 2007 XML)
                                            +-->  .pdf    (writer_pdf_Export)

- 内容直接用页面里已渲染的 `#reportArea` HTML —— 导出的就是屏幕上看到的，
  后端也不必再实现一遍 markdown；
- 版式（标题层级、A4 分页、页边距、表格边框）交给板端**本来就有的**
  LibreOffice 处理，**零新增依赖**（板端完全离线，apt 不可用，这是硬约束）；
- 实测单次转换约 **1.7 秒**，产物 PDF ≈ 40 KB / DOCX ≈ 6 KB。

### 两个必须记住的坑

1. **必须加 `--infilter="HTML (StarWriter)"`。**
   否则 LibreOffice 用 Writer/Web 模块打开 HTML，而该模块**没有 DOCX
   导出过滤器**，直接报 `Error: no export filter for xxx.docx found`。

2. **表格边框只能用 HTML 属性，CSS 无效。** 实测对比：
   | 写法 | 结果 |
   |---|---|
   | CSS 简写 `td{border:1px solid #999}` | 无边框 |
   | CSS 长写 `td{border-width/style/color}` | 无边框 |
   | `<table border="1">` | **有边框** ✓ |

   报告正文的表格取自页面 HTML，没有这个属性，所以
   `_borderize()` 会给每个 `<table>` 注入
   `border="1" cellspacing="0" cellpadding="4" width="100%"`。

## 中文输入法（板端本来就有，只需给个开关）

**不需要安装任何输入法。** 板端早已具备完整能力：

- `fcitx5` + `libpinyin`（`/usr/share/fcitx5/inputmethod/pinyin.conf`，
  profile 里 `DefaultIM=pinyin`）
- GTK 的 `im-fcitx5.so` 在，应用环境里 `GTK_IM_MODULE=fcitx`、
  `XMODIFIERS=@im=fcitx` 齐全
- 实测：输入框获得焦点后 fcitx5 立即建立输入上下文（状态 1），
  输入 `nihao` 能弹出「1.你好 2.你 3.尼 …」候选窗并正常上屏

**唯一缺的是"切到中文"这个动作** —— fcitx5 默认停在英文态，
而 GNOME 软键盘上没有 Ctrl+Space（fcitx 的触发键），按不出来。
所以在界面右上角放了一个 **中/英** 按钮：

| 接口 | 说明 |
|---|---|
| `GET /api/ime/status` | 返回 `{state, label}`，`label` 为 中 / 英 |
| `POST /api/ime/toggle` | 切换并返回新状态 |

> ⚠️ 前端必须写 `onmousedown="event.preventDefault()"`。
> 否则点按钮的瞬间当前输入框失焦，fcitx5 随即失去输入上下文，
> 切换请求会落空（实测踩过）。

接口**不要求登录**（登录页也要用），改为按「仅限本机」管控
（局域网调用返回 403，与 `/api/kiosk/*` 同一套口径）。

## 界面弹窗已改为自绘

原来用浏览器原生 `confirm()/alert()/prompt()`，在 WebKit 里会渲染成
**`JavaScript-http://127.0.0.1:8081/` + 英文 `Cancel` / `OK`** 的系统弹窗，
中文一体机上非常突兀；而且 `confirm` 是**阻塞**的（弹窗期间页面完全卡住，
连 F5 刷新都不生效，实测）。
现已全部替换为页面内自绘模态框（按钮为 取消 / 确定），
共 16 处调用点。

## 开机的「网络登录 / 热点登录」是误报（已消除）

开机时 GNOME 会弹出一张写着 **「网络登录」** 的通知（正文
`"gnome-shell-portal-helper"已就绪`），点开会得到一个全屏窗口，
内容只有一句 `Could not connect: Network is unreachable`。

**它不是真的有热点要登录，是 GNOME 的强制门户（captive portal）误判。**

板子是完全离线的一体机：后端、Neo4j、RKLLM 全在本地，没有公网出口。
而 NetworkManager 默认要拿 `connectivity-check.ubuntu.com` 做联网检测：

```
connectivity-check.ubuntu.com              → HTTP 000（连不上）
nmcheck.gnome.org/check_network_status.txt → HTTP 000（连不上）
nmcli general status                       → CONNECTIVITY 受限
journalctl | grep PortalHelper             → Activating service
                                              'org.gnome.Shell.PortalHelper'
                                              requested by gnome-shell
```

检测超时 → NM 判定「受限(limited)」→ GNOME 认为处在需要登录的热点/酒店 WiFi
→ D-Bus 拉起 `gnome-shell-portal-helper` 并通知用户去登录。

**修法**（已固化进 `harden_kiosk.sh`，`revert` 会删除）：

```ini
# /etc/NetworkManager/conf.d/20-no-connectivity-check.conf
[connectivity]
enabled=false
```

关掉后 `CONNECTIVITY` 从「受限」变为「完全」，GNOME 不再走门户分支，
开机通知与那个空窗口一并消失。

> 注意：这**不影响局域网**。RJ45 照样拿 IP、板子照样能被访问，
> 只是不再去公网"探活"。对离线一体机来说这正是想要的行为。

## 开机速度（顺手修掉的一个大坑）

板厂预装的 atopacct.service 因内核缺少 TASKSTATS netlink 家族而启动失败，
日志为 "receive NETLINK family, errno -2"，但它是 enabled 且
WantedBy=multi-user.target，于是**干等 90 秒超时**，把整条启动链路拖住。

安装脚本会 disable + mask 它（atop 只是性能记录工具，一体机用不到）：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| kernel | 2.828s | 2.867s |
| **userspace** | **1min 31.780s** | **8.799s** |
| **总计** | **1min 34.609s** | **11.666s** |

**省了 83 秒（88%）。** 想恢复：`systemctl unmask atopacct.service && systemctl enable atopacct.service`

## 适用环境（实测）

| 项 | 值 |
|---|---|
| 设备 | RK3588（`rockchip,rk3588-evb1-lp4-v10`），主机名 EM-R16 |
| 系统 | Ubuntu 22.04.4 LTS |
| 显示 | X11 + GDM3（已配自动登录 user）+ GNOME Shell 42.9 |
| 屏幕 | 内置 DSI 面板，物理 1200×1920，旋转为横向 1920×1200，Mutter scale=2 |
| 触摸 | `goodix-ts`（XInput2），配合 GNOME 内置软键盘 |
| 输入法 | fcitx5（`GTK_IM_MODULE=fcitx`） |
| 运行时 | WebKitGTK 2.44.2（`libwebkit2gtk-4.0-37`）+ python3-gi 3.42.1 |
| 备用浏览器 | `chromium-browser` 114（deb 包，非 snap） |
| GUI 用户 | `user`（uid 1002，家目录 `/home/user`） |
| 项目位置 | `/home/ubuntu/elevator`（root 所有） |

> 注意：GUI 登录用户是 `user`，而项目放在 `/home/ubuntu`。autostart 必须装在
> `/home/user/.config/autostart/`，不是 `/home/ubuntu`。

## 安装

```bat
REM 主机侧：一次性推送全部组件到 /tmp
push.bat

REM 板端执行安装
adb shell "bash /tmp/install_kiosk.sh"
```

安装脚本会做 7 件事：
1. 装原生应用 `elevator_app.py`、启动器 `elevator-kiosk.sh`（备用）与统一入口 `elevator-launch.sh`
2. 生成应用图标 `~/.local/share/icons/elevator.png`（用 web/fslogo.png 合成）
3. 注册自动启动项 `~/.config/autostart/elevator-kiosk.desktop`（延迟 6s）
4. 装桌面快捷方式 `~/桌面/电梯安全评估系统.desktop`（chmod +x + gio set metadata::trusted true）并放入应用菜单
5. 安装并启用软键盘桥扩展 `elevator-osk@local`
6. 执行 `harden_kiosk.sh`：关闭锁屏/息屏/热区，**解除 Alt+F4、Super 等退回桌面的快捷键**
7. 禁用 `atopacct` 优化开机速度

> 第 5 步的坑：`gnome-extensions enable` 走的是 `org.gnome.Shell.Extensions` D-Bus，
> 而 **Shell 还没扫描到这个新装的扩展时会直接报错**。所以脚本准备了回退路径 ——
> 直接写 `org.gnome.shell enabled-extensions`，Shell 会热加载。

## 卸载

```bash
adb shell "bash /tmp/install_kiosk.sh remove"
```

移除自动启动项、桌面项与软键盘桥扩展，恢复原始桌面行为（启动器脚本保留，可手动删）。

## 日常使用与排查

| 操作 | 命令 |
|---|---|
| 手动启动 | `sudo -u user /home/user/elevator-launch.sh` |
| **应用日志** | `cat /home/user/.elevator-app.log` |
| 备用启动器日志 | `cat /home/user/.elevator-kiosk.log` |
| 键盘桥状态 | `gnome-extensions info elevator-osk@local` |
| 键盘桥自测 | `gdbus call --session --dest org.gdsei.ElevatorOsk --object-path /org/gdsei/ElevatorOsk --method org.gdsei.ElevatorOsk.State` |
| 扩展日志 | `journalctl -b -o cat _COMM=gnome-shell \| grep elevator-osk` |
| 停掉当前实例 | `pkill -f elevation_app[.]py` |

**界面出现两个半屏窗口** → 有重复实例（Chromium 备用方案下），
执行 `pkill -f elevator-kiosk-profile` 后重启启动器。原生应用由
`Gtk.Application` 保证单实例。

**软键盘不弹** → 依次确认：扩展是否 ENABLED、D-Bus 名是否被占用、
应用日志里有没有「输入框获得焦点 -> 呼出软键盘」。

**关于截图**：`xwd -root` 在 Mutter 这类合成型窗口管理器下**不可靠** ——
它截的是 root window 内容，会混入已关闭窗口的陈旧像素，看起来像有多个窗口。
要确认真实状态，查窗口几何与状态：

```bash
su user -c "DISPLAY=:0 xprop -root _NET_CLIENT_LIST"
su user -c "DISPLAY=:0 xwininfo -id <窗口id>" | grep -E 'Width|Height|Absolute'
su user -c "DISPLAY=:0 xprop -id <窗口id> _NET_WM_STATE"
# 正确状态应为: Width 1920 / Height 1200 / +0+0 且含 _NET_WM_STATE_FULLSCREEN + FOCUSED
```

## 屏幕方向与 2x 缩放：不要碰（重要）

**结论：屏幕方向与缩放完全交给系统，安装脚本与启动器都不做任何设置。**

系统默认已经是正确的：

- GNOME 按 `~/.config/monitors.xml` 在登录时应用 **`<scale>2</scale>` + `<rotation>right</rotation>`**
- 板厂自带的 `/etc/rotate_screen.sh`（`xrandr --output DSI-1 --rotate right`）
  在已旋转状态下是空操作，不会影响缩放
- 实测重启后：`Mutter scale=2.0 / transform=3(right)`，窗口 1920×1200 全屏

### 踩坑记录：手动改屏幕设置会把 2x 缩放打掉

调试期间曾出现「整机 UI 突然变成一半大小」。原因是**在会话里额外执行了显示设置命令**
（`xrandr --rotate …` 或 Mutter `ApplyMonitorsConfig`）。这类命令会重建显示配置，
使 GNOME 的 2x 缩放回落到 1x。

**因此：**

- ❌ 不要用 `xrandr` 改方向
- ❌ 不要在启动脚本里重设缩放
- ❌ 不要把 `ApplyMonitorsConfig` 写进开机流程
- ✅ 屏幕设置交给系统；重启即为正确状态

> 注：陀螺仪自动旋转（`iio-sensor-proxy` + GNOME）是系统自带行为，走 Mutter 同一套配置，
> 正常旋转不会重置缩放 —— 不要去干预它。应用侧靠 `monitors-changed` 自适应即可。
