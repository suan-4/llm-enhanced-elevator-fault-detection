// 电梯安全评估系统 —— 屏幕键盘桥 + 顶栏按需收放
//
// 背景：本机是 X11 会话 + fcitx5。GNOME 42 里软键盘只有两条弹出通路：
//   1) gnome-shell 自己的 Clutter.Text 获得焦点 —— 外部应用走不到；
//   2) 输入法上报 panel-state=ON —— 那是 Wayland text-input 协议才有的。
// 实测确认 org.gnome.Shell.Eval 被 global.context.unsafe_mode 挡住（且该开关
// 只能在 Looking Glass 里人工打开），底部上滑的 EdgeDragAction 又设了
// set_n_touch_points(1)，只认真实触摸点。
//
// 所以这里做一个最小桥：把 Main.keyboard.open()/close() 暴露到会话总线上，
// 让原生应用能在输入框获得焦点时确定性地弹出软键盘。
//
// ── 顶栏策略（迭代了三轮，结论在最后）────────────────────────
//
// 需求是"应用内不要顶栏，回到桌面要能用顶栏"。
//
// 第 1 轮：enable() 里**无条件**把顶栏移出屏幕
//         （translation_y = -height 再 _updateRegions() 让 strut 归零）。
//         副作用：退出应用后顶栏也永远回不来，现场反馈"顶栏完全不可用"。
//
// 第 2 轮：改成"每次事件都全量扫描窗口、用瞬时读数决定顶栏显隐"。
//         结果顶栏每 25~70 秒无规律闪现一次，日志是
//             正在收掉顶栏（窗口创建） → 已恢复顶栏（焦点变化） → …
//         机制：某次扫描瞬时时没看到应用窗口 → 误判"应用已退出" → 放出顶栏
//         → 工作区少一条 → Mutter 重新约束应用窗口 → 又触发一次尺寸事件。
//         **根因是"瞬时读数决定状态"，天生不可靠。**
//
// 第 3 轮（当前）：改成**边沿触发 + 锁存**，只有两种事件能改变结论：
//         出现：window-created 里真的看到应用窗口（或周期扫描补漏）
//         消失：窗口对象自己没了（unmanaged 信号 / 合成器 actor 为空 / 最小化）
//         **绝不把"某次扫描没看到"当作消失判据。**
//         同时不再接 notify::focus-window —— 焦点变化与"应用在不在"无关。
//
// 顶栏收起用 translation_y = -height 而不是 hide()：layout.js 的注释写明
//     "Changes to @actor's visibility will NOT affect whether or not
//      the strut is present"
// 只 hide 的话 strut 仍在，窗口会矮一条并在顶栏位置露出桌面。

const { Gio, GLib } = imports.gi;
const Main = imports.ui.main;

const BUS_NAME = 'org.gdsei.ElevatorOsk';
const OBJECT_PATH = '/org/gdsei/ElevatorOsk';

// 评估应用窗口的 WM_CLASS。
// native/elevator_app.py 里 set_wmclass(APP_ID, APP_ID)、APP_ID="elevator-assessment"，
// 板上实测：WM_CLASS(STRING) = "elevator-assessment", "elevator-assessment"
const APP_WM_CLASS = 'elevator-assessment';
const RECHECK_SECONDS = 2;      // 兜底复检周期

const IFACE_XML = `
<node>
  <interface name="org.gdsei.ElevatorOsk">
    <method name="Show">
      <arg type="b" name="ok" direction="out"/>
    </method>
    <method name="Hide">
      <arg type="b" name="ok" direction="out"/>
    </method>
    <method name="State">
      <arg type="b" name="visible" direction="out"/>
    </method>
    <method name="Debug">
      <arg type="s" name="info" direction="out"/>
    </method>
  </interface>
</node>`;

const OskBridge = class OskBridge {
    // 软键盘要贴在哪块屏幕上。焦点屏拿不到就退回主屏。
    _monitor() {
        let lm = Main.layoutManager;
        let m = lm.focusIndex;
        if (m === undefined || m === null || m < 0)
            m = lm.primaryIndex;
        if (m === undefined || m === null || m < 0)
            m = 0;
        return m;
    }

    Show() {
        if (!Main.keyboard) {
            log('[elevator-osk] Show 失败：Main.keyboard 不存在（screen-keyboard-enabled 是否为 false？）');
            return false;
        }
        try {
            Main.keyboard.open(this._monitor());
            return true;
        } catch (e) {
            logError(e, '[elevator-osk] Show');
            return false;
        }
    }

    Hide() {
        if (!Main.keyboard)
            return false;
        try {
            Main.keyboard.close();
            return true;
        } catch (e) {
            logError(e, '[elevator-osk] Hide');
            return false;
        }
    }

    State() {
        return !!(Main.keyboard && Main.keyboard.visible);
    }

    // 诊断：keyboard.js 的 visible 只是"应该显示"的意愿，不代表真的画出来了。
    // 这里把真实的几何/透明度/层级倒出来。
    Debug() {
        let lm = Main.layoutManager;
        let box = lm.keyboardBox;
        let actor = Main.keyboard ? Main.keyboard.keyboardActor : null;
        let stage = global.stage;
        let names = stage.get_children().map(function (c) {
            return (c.get_name ? c.get_name() : '?') + ':' + c.get_width() + 'x' + c.get_height();
        });
        let winNames = global.window_group.get_children().map(function (c) {
            let w = c.meta_window;
            return (w ? (w.get_wm_class() || '?') + (w.is_fullscreen() ? '[FS]' : '') : '?');
        });
        return JSON.stringify({
            stageW: stage.get_width(), stageH: stage.get_height(),
            // 顶栏按需收放的现场状态（排查"顶栏该收没收/该放没放"先看这三个）
            panelHidden: _panelHidden,
            panelTranslationY: lm.panelBox ? lm.panelBox.translation_y : null,
            appWindows: _appWins.size,
            visible: !!(Main.keyboard && Main.keyboard.visible),
            keyboardIndex: lm.keyboardIndex, focusIndex: lm.focusIndex,
            primaryIndex: lm.primaryIndex,
            keyboardMonitor: lm.keyboardMonitor
                ? {x: lm.keyboardMonitor.x, y: lm.keyboardMonitor.y,
                   w: lm.keyboardMonitor.width, h: lm.keyboardMonitor.height} : null,
            box: box ? {x: box.x, y: box.y, w: box.width, h: box.height,
                        vis: box.visible, mapped: box.mapped, op: box.opacity} : null,
            actor: actor ? {x: actor.x, y: actor.y, w: actor.width, h: actor.height,
                            vis: actor.visible, mapped: actor.mapped, op: actor.opacity,
                            ty: actor.translation_y} : null,
            stageChildren: names,
            windowChildren: winNames,
        });
    }
};

let _exported = null;
let _ownerId = 0;
let _panelHidden = false;
let _panelSavedY = 0;
let _panelHeightId = 0;
let _panelRetryId = 0;
let _panelTries = 0;
let _syncId = 0;                 // 周期兜底复检的定时器 id
let _displaySignals = [];        // [[信号发出者, 连接 id], ...]
let _winSignals = new Map();     // Meta.Window -> 其 unmanaged 信号 id
let _appWins = new Set();        // ★ 已确认存在的评估应用窗口（锁存，不作全量扫描判据）

// ── 顶栏移出屏幕 ─────────────────────────────────────────────
//
// ★ 不能只 hide() ★ layout.js 的注释写得很明确：
//     "Changes to @actor's visibility will NOT affect whether or not
//      the strut is present"
// 只隐藏的话 strut 仍在，最大化窗口仍会矮一条（实测 960x573 而不是 960x600），
// 于是顶栏位置会露出一条桌面背景。
//
// 正确做法是把它**移出屏幕**：_updateRegions() 用的是
//     actor.get_transformed_position()   // 含 translation
//     y1 = max(y, 0);  y2 = min(y + h, screen_height)
// translation_y = -height 之后 y1 == y2 == 0，strut 高度归零，
// 既看不见顶栏、也不占位。
//
// ★ 还有一个坑：panelBox.height 在会话刚起来时是 0 ★
// enable() 时顶栏的 allocation 往往还没算出来，此时 translation_y = -0 是个
// 空操作，而 hide() 又不影响 strut，结果顶栏虽然看不见却仍占着 34 逻辑像素，
// 窗口被挤到屏幕下方（实测 _NET_WORKAREA = 0,68,1920,1132）。所以必须等到
// 高度真正可用，并且在高度变化时持续跟随。
function _applyPanelOffset() {
    let lm = Main.layoutManager;
    if (!_panelHidden || !lm || !lm.panelBox)
        return false;
    let box = lm.panelBox;
    if (box.height > 0) {
        box.translation_y = -box.height;
        if (lm._updateRegions)
            lm._updateRegions();      // 必须主动重算，否则旧 strut 仍生效
        _panelTries = 0;
    }
    return false;
}

function _retryPanelOffset() {
    _panelRetryId = 0;
    if (!_panelHidden)
        return false;
    let lm = Main.layoutManager;
    let box = lm ? lm.panelBox : null;
    if (box && box.height > 0) {
        _applyPanelOffset();
        return false;
    }
    if (_panelTries++ < 40) {                 // 最多等 20 秒
        _panelRetryId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 500, _retryPanelOffset);
    } else {
        log('[elevator-osk] 顶栏高度始终为 0，放弃移出屏幕（窗口会矮一条）');
    }
    return false;
}

function _hidePanel(why) {
    let lm = Main.layoutManager;
    if (!lm || !lm.panelBox)
        return;
    // ★ 必须是幂等的 ★ 会被多次调用；重复进入会把 _panelSavedY 记成 -height，
    // 之后恢复时顶栏就再也回不到原位了。
    if (_panelHidden)
        return;
    let box = lm.panelBox;
    _panelSavedY = box.translation_y;
    _panelHidden = true;
    box.hide();
    _applyPanelOffset();                                   // 高度已知就立刻生效
    if (!_panelHeightId)
        _panelHeightId = box.connect('notify::height', _applyPanelOffset);
    _retryPanelOffset();                                   // 高度还是 0 就持续重试
    log('[elevator-osk] 正在收掉顶栏（' + (why || '') + '）；当前高度=' + box.height
        + '（为 0 则稍后自动重试）');
}

function _showPanel(why) {
    if (!_panelHidden)
        return;
    let lm = Main.layoutManager;
    if (_panelRetryId) {
        GLib.source_remove(_panelRetryId);
        _panelRetryId = 0;
    }
    _panelTries = 0;
    if (lm && lm.panelBox) {
        if (_panelHeightId) {
            lm.panelBox.disconnect(_panelHeightId);
            _panelHeightId = 0;
        }
        lm.panelBox.show();
        lm.panelBox.translation_y = _panelSavedY;
        if (lm._updateRegions)
            lm._updateRegions();
    }
    _panelHidden = false;
    log('[elevator-osk] 已恢复顶栏（' + (why || '') + '）');
}

// ── 判据与锁存 ──────────────────────────────────────────────
function _isAppWindow(w) {
    if (!w)
        return false;
    try {
        let cls = (w.get_wm_class ? w.get_wm_class() : null) || '';
        let inst = (w.get_wm_class_instance ? w.get_wm_class_instance() : null) || '';
        if (cls !== APP_WM_CLASS && inst !== APP_WM_CLASS)
            return false;
        // 最小化的窗口视为"用户没在用"，这时应该把顶栏还回去
        if (w.minimized)
            return false;
        return true;
    } catch (e) {
        logError(e, '[elevator-osk] _isAppWindow');
        return false;
    }
}

function _syncPanel(why) {
    try {
        let present = _appWins.size > 0;
        if (present && !_panelHidden)
            _hidePanel(why);
        else if (!present && _panelHidden)
            _showPanel(why);
    } catch (e) {
        // 绝不能让异常冒到 shell 主循环里
        logError(e, '[elevator-osk] _syncPanel');
    }
    return false;
}

// 明确判定"这个应用窗口没了"，才解锁并还回顶栏
function _forgetWindow(w, why) {
    if (!_appWins.has(w))
        return false;
    _appWins.delete(w);
    let id = _winSignals.get(w);
    if (id) {
        try { w.disconnect(id); } catch (e) {}
        _winSignals.delete(w);
    }
    log('[elevator-osk] 应用窗口已消失（' + why + '），剩余 ' + _appWins.size + ' 个');
    _syncPanel(why);
    return true;
}

// 只在"真的看到应用窗口"时锁存。返回前不触碰顶栏，除非状态真的变了 ——
// 这一条是修掉"顶栏每 25~70 秒闪现一次"的关键。
function _noteWindow(w, why) {
    if (!w)
        return;
    try {
        if (!_isAppWindow(w)) {
            // WM_CLASS 可能在窗口创建之后才设上，也可能被改掉；
            // 这里只负责"纠正已缓存但已不成立"的情况
            if (_appWins.has(w))
                _forgetWindow(w, 'wm-class 变化');
            return;
        }
        if (_appWins.has(w))
            return;
        _appWins.add(w);
        // 'unmanaged' = 窗口被销毁（用户点「退出系统」pkill 掉进程时也会走到）
        _winSignals.set(w, w.connect('unmanaged', function () {
            _forgetWindow(w, 'unmanaged');
        }));
        // WM_CLASS 后置设置 / 被修改
        w.connect('notify::wm-class', function () { _noteWindow(w, 'wm-class 变化'); });
        log('[elevator-osk] 发现应用窗口（' + why + '），共 ' + _appWins.size + ' 个');
    } catch (e) {
        logError(e, '[elevator-osk] _noteWindow');
    }
    _syncPanel(why);
}

function _onWindowCreated(_display, win) {
    _noteWindow(win, '窗口创建');
    return false;
}

// 清掉确实已经不存在的窗口。
// ★ 判据必须是"窗口对象自己没了"（合成器 actor 为空 / 已最小化），
//   而**不是**"这次扫描的列表里没有它"。★
function _pruneDead() {
    let dead = [];
    _appWins.forEach(function (w) {
        let gone = false;
        try {
            if (w.get_compositor_private && !w.get_compositor_private())
                gone = true;                    // actor 已销毁
            else if (w.minimized)
                gone = true;                    // 用户回到桌面了，顶栏要还回去
        } catch (e) {
            gone = true;
        }
        if (gone)
            dead.push(w);
    });
    for (let i = 0; i < dead.length; i++)
        _forgetWindow(dead[i], 'actor 已销毁或已最小化');
}

// 兜底复检：只做两件"安全方向"的事 ——
//   1) 把扫描到的应用窗口补进锁存（补 window-created 漏掉的情况）
//   2) 清掉确实已销毁的窗口
// 永远不会因为"某次扫描没看到"就把顶栏放出来。
function _recheck() {
    try {
        let actors = global.get_window_actors();
        for (let i = 0; i < actors.length; i++)
            _noteWindow(actors[i].meta_window, '周期扫描');
    } catch (e) {
        logError(e, '[elevator-osk] 周期扫描失败');
    }
    _pruneDead();
    return true;                 // true = 保持定时器
}

function init() {
}

function enable() {
    // 热重载时可能残留上一轮的状态，先清干净
    _appWins.clear();
    _winSignals.clear();
    _displaySignals = [];

    // ★ 先连接信号、再立刻判一次当前状态 ★
    // enable() 不一定发生在登录那一刻：扩展被热启用、Shell 重启时，
    // 评估应用可能已经在跑了，这时必须马上把顶栏收掉。
    //
    // 注意这里**不接 notify::focus-window**：焦点变化与"应用在不在"无关，
    // 接了只会平白多算一遍（顶栏显隐曾经就是被它错误触发的）。
    try {
        let d = global.display;
        _displaySignals.push([d, d.connect('window-created', _onWindowCreated)]);
    } catch (e) {
        logError(e, '[elevator-osk] 连接窗口信号失败（顶栏将退化为仅周期复检）');
    }
    try {
        let actors = global.get_window_actors();
        for (let i = 0; i < actors.length; i++)
            _noteWindow(actors[i].meta_window, '扩展启用扫描');
    } catch (e) {
        logError(e, '[elevator-osk] 初始窗口扫描失败');
    }
    _syncPanel('扩展启用');
    _syncId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, RECHECK_SECONDS, _recheck);

    _exported = Gio.DBusExportedObject.wrapJSObject(IFACE_XML, new OskBridge());
    _exported.export(Gio.DBus.session, OBJECT_PATH);
    // 必须占住这个总线名，否则调用方只能用每次登录都变的 :1.x 唯一名
    _ownerId = Gio.bus_own_name_on_connection(
        Gio.DBus.session, BUS_NAME, Gio.BusNameOwnerFlags.NONE, null, null);
    log('[elevator-osk] 已启用，总线名 ' + BUS_NAME
        + '，应用窗口数=' + _appWins.size
        + '，顶栏当前' + (_panelHidden ? '已收起' : '可见'));
}

function disable() {
    if (_syncId) {
        GLib.source_remove(_syncId);
        _syncId = 0;
    }
    for (let i = 0; i < _displaySignals.length; i++) {
        try { _displaySignals[i][0].disconnect(_displaySignals[i][1]); } catch (e) {}
    }
    _displaySignals = [];
    _winSignals.forEach(function (id, win) {
        try { win.disconnect(id); } catch (e) {}
    });
    _winSignals.clear();
    _appWins.clear();

    _showPanel('扩展停用');
    if (_ownerId) {
        Gio.bus_unown_name(_ownerId);
        _ownerId = 0;
    }
    if (_exported) {
        _exported.unexport();
        _exported = null;
    }
    log('[elevator-osk] 已停用');
}
