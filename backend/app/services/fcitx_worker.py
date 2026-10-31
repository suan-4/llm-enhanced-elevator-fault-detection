"""One private offline pinyin context, JSON in/out. Invoked as desktop user."""
import json
import sys
import time


def lookup(actions):
    import dbus
    from dbus.mainloop.glib import DBusGMainLoop
    from gi.repository import GLib
    DBusGMainLoop(set_as_default=True)
    bus = dbus.SessionBus(private=True)
    im = dbus.Interface(bus.get_object('org.fcitx.Fcitx5', '/org/freedesktop/portal/inputmethod'),
                        'org.fcitx.Fcitx.InputMethod1')
    path, _ = im.CreateInputContext([('program', 'elevator-offline-input'), ('display', 'elevator:offline')])
    obj = bus.get_object('org.fcitx.Fcitx5', path)
    ic = dbus.Interface(obj, 'org.fcitx.Fcitx.InputContext1')
    result = {'candidates': [], 'committed': '', 'has_next': False}

    def update(preedit, cursor, up, down, candidates, index, layout, prev, next_):
        result['candidates'] = [str(c[1]) for c in candidates]
        result['has_next'] = bool(next_)

    obj.connect_to_signal('UpdateClientSideUI', update, dbus_interface='org.fcitx.Fcitx.InputContext1')
    obj.connect_to_signal('CommitString', lambda text: result.update(committed=result['committed'] + str(text)),
                          dbus_interface='org.fcitx.Fcitx.InputContext1')
    context = GLib.MainContext.default()

    def drain():
        end = time.monotonic() + .008
        while time.monotonic() < end:
            while context.pending():
                context.iteration(False)
            time.sleep(.001)

    try:
        ic.SetCapability(dbus.UInt64((1 << 39) | 4 | 2 | 1))
        ic.FocusIn()
        ic.ProcessKeyEvent(32, 0, 4, False, 0)
        for action in actions:
            if 'key' in action:
                key = action['key']
                value = 0xff08 if key == 'BackSpace' else ord(key)
                ic.ProcessKeyEvent(value, 0, 0, False, 0)
            elif 'candidate' in action:
                drain()
                if action['candidate'] not in result['candidates']:
                    raise ValueError('候选词已变化，请重新选择')
                ic.SelectCandidate(result['candidates'].index(action['candidate']))
            else:
                ic.NextPage()
            drain()
        drain()
        return result
    finally:
        ic.Reset()
        ic.FocusOut()
        ic.DestroyIC()
        bus.close()


if __name__ == '__main__':
    # 常驻进程：每次请求只复用 Python/DBus 初始化，避免每敲一个键重新启动解释器。
    for line in sys.stdin:
        try:
            result = lookup(json.loads(line))
            sys.stdout.write(json.dumps(result, ensure_ascii=False) + '\n')
        except Exception:
            sys.stdout.write(json.dumps({'error': '本机拼音输入暂不可用，请重试'},
                                         ensure_ascii=False) + '\n')
        sys.stdout.flush()
