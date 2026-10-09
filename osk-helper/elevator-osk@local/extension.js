// 电梯安全评估系统 —— 屏幕键盘桥
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

const { Gio, GLib } = imports.gi;
const Main = imports.ui.main;

// 说明：这里只做两件事 —— 软键盘 D-Bus 桥 + 收掉顶栏。
//
// 关于顶栏：layout.js 里 panelBox 的参数是 trackFullscreen: true，
// 源码注释原文：
//     "the actor's visibility will be bound to the presence of fullscreen
//      windows on the same monitor (it will be hidden whenever a fullscreen
//      window is visible)"
// 所以**全屏时顶栏本来就会被 GNOME 自己收掉**。
// 但本项目用的是"铺满屏幕的普通窗口"（不是全屏状态，见 elevator_app.py
// 文件头第 5 条），顶栏不会被自动收起，因此需要这里显式收掉。
// 注意软键盘 keyboardBox 的 trackFullscreen 是 false，不会被全屏隐藏 ——
// 不要去"修"一个不存在的问题。

const BUS_NAME = 'org.gdsei.ElevatorOsk';
const OBJECT_PATH = '/org/gdsei/ElevatorOsk';

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

// 一体机不需要顶栏：收掉它既得到无干扰外观，也顺手堵死了
// 「触摸顶边唤出顶栏」这条绕过 kiosk 的路径。
//
// ★ 不能只 hide() ★
// layout.js 的注释写得很明确：
//     "Changes to @actor's visibility will NOT affect whether or not
//      the strut is present"
// 只隐藏的话 strut 仍在，最大化窗口仍会矮一条（实测 960x573 而不是 960x600），
// 于是顶栏位置会露出一条桌面背景。
//
// 正确做法是把它**移出屏幕**：_updateRegions() 用的是
//     actor.get_transformed_position()   // 含 translation
//     y1 = max(y, 0);  y2 = min(y + h, screen_height)
// translation_y = -height 之后 y1 == y2 == 0，strut 高度归零，
// 既看不见顶栏、也不占位。greeter 用的就是这个办法。
// ★ 还有一个坑：panelBox.height 在会话刚起来时是 0 ★
// 扩展是在 enable() 里调用的，那时顶栏的 allocation 往往还没算出来，
// 此时 translation_y = -0 是个**空操作**，而 hide() 又不影响 strut，
// 结果顶栏虽然看不见、却仍占着 34 逻辑像素，窗口被挤到屏幕下方
// （实测 _NET_WORKAREA = 0,68,1920,1132，窗口只能到 960x566）。
// 所以必须等到高度真正可用，并且高度变化时持续跟随。
let _panelHeightId = 0;
let _panelRetryId = 0;
let _panelTries = 0;

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

function _hidePanel() {
    let lm = Main.layoutManager;
    if (!lm || !lm.panelBox)
        return;
    let box = lm.panelBox;
    _panelSavedY = box.translation_y;
    _panelHidden = true;
    box.hide();
    _applyPanelOffset();                                   // 高度已知就立刻生效
    _panelHeightId = box.connect('notify::height', _applyPanelOffset);
    _retryPanelOffset();                                   // 高度还是 0 就持续重试
    log('[elevator-osk] 正在收掉顶栏；当前高度=' + box.height
        + '（为 0 则稍后自动重试）');
}

function _showPanel() {
    if (!_panelHidden)
        return;
    let lm = Main.layoutManager;
    if (_panelRetryId) {
        GLib.source_remove(_panelRetryId);
        _panelRetryId = 0;
    }
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
    log('[elevator-osk] 已恢复顶栏');
}

function init() {
}

function enable() {
    _hidePanel();
    _exported = Gio.DBusExportedObject.wrapJSObject(IFACE_XML, new OskBridge());
    _exported.export(Gio.DBus.session, OBJECT_PATH);
    // 必须占住这个总线名，否则调用方只能用每次登录都变的 :1.x 唯一名
    _ownerId = Gio.bus_own_name_on_connection(
        Gio.DBus.session, BUS_NAME, Gio.BusNameOwnerFlags.NONE, null, null);
    log('[elevator-osk] 已启用，总线名 ' + BUS_NAME);
}

function disable() {
    _showPanel();
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
